import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from wilab.network.commands import (
    CommandError,
    CommandStuck,
    CommandTimeout,
    ForegroundProcess,
    execute_command,
    execute_ip,
    execute_iptables,
    execute_sysctl,
    start_foreground,
    stop_process,
    stuck_commands,
)
from wilab.wifi.hostapd import _classify_output


class TestCommandExecution:
    """Tests for basic command execution."""

    def test_execute_command_uses_default_timeout(self):
        """Test default timeout is 8 seconds."""
        with patch('wilab.network.commands._run', return_value=(0, 'ok', '')) as mock_run:
            execute_command(['echo', 'hello'])
            assert mock_run.call_args.args[1] == 8.0

    def test_the_timeout_given_is_the_timeout_used(self):
        """PERF-5: no silent 5 s minimum."""
        with patch('wilab.network.commands._run', return_value=(0, 'ok', '')) as mock_run:
            execute_command(['echo', 'hello'], timeout=1.0)
            assert mock_run.call_args.args[1] == 1.0

    def test_deadline_clamps_timeout_and_does_not_leak(self, monkeypatch):
        from wilab.network import commands

        now = 10.0
        monkeypatch.setattr(commands, "time", SimpleNamespace(monotonic=lambda: now))
        with patch.object(commands, "_run", return_value=(0, "", "")) as run:
            with commands.command_deadline(10.5):
                execute_command(["ip", "addr", "show"])
                assert run.call_args.args[1] == 0.5
                now = 10.5
                with pytest.raises(CommandError, match="Deadline expired"):
                    execute_command(["dnsmasq", "--test"])
                assert run.call_count == 1
            execute_command(["ip", "addr", "show"])
            assert run.call_args.args[1] == 8.0
    
    def test_execute_command_success(self):
        """Test successful command execution."""
        result = execute_command(['echo', 'hello'])
        assert 'hello' in result
    
    def test_execute_command_failure(self):
        """Test command failure raises error."""
        with pytest.raises(CommandError):
            execute_command(['false'])  # Command that always fails
    
    def test_execute_command_not_found(self):
        """Test command not found raises error."""
        with pytest.raises(CommandError, match="not found"):
            execute_command(['nonexistent-command-xyz'])
    
    def test_execute_command_timeout(self):
        """Test command timeout raises error."""
        with pytest.raises(CommandError, match="timed out|timeout"):
            # Explicit timeout below 5 is clamped to 5, so use sleep 6.
            execute_command(['sleep', '6'], check=True, timeout=1.0)

    def test_execute_command_custom_timeout(self):
        """Test custom timeout allows longer-running command."""
        # timeout=3 is clamped to 5, which is still enough for sleep 2
        result = execute_command(['sleep', '2'], check=True, timeout=3.0)
        assert result == ''
    
    def test_execute_command_check_false(self):
        """Test command with check=False doesn't raise."""
        result = execute_command(['false'], check=False)
        # Should not raise
        assert result is not None


class TestStopProcess:
    def test_waits_until_process_exits(self, monkeypatch):
        from wilab.network import commands

        checks = iter([True, True, False])

        def check_process(pid, signal):
            if not next(checks):
                raise ProcessLookupError

        calls = []
        monkeypatch.setattr(commands, "os", SimpleNamespace(kill=check_process))
        monkeypatch.setattr(commands, "execute_command", lambda cmd: calls.append(cmd))
        monkeypatch.setattr(commands, "time", SimpleNamespace(sleep=lambda _: None))
        stop_process(123)
        assert calls == [["kill", "123"]]

    def test_failed_signal_is_not_hidden(self, monkeypatch):
        from wilab.network import commands

        monkeypatch.setattr(commands, "os", SimpleNamespace(kill=lambda pid, signal: None))

        def fail(cmd):
            raise CommandError("permission denied")

        monkeypatch.setattr(commands, "execute_command", fail)
        with pytest.raises(CommandError, match="permission denied"):
            stop_process(123)

    def test_process_that_survives_force_kill_is_not_released(self, monkeypatch):
        from wilab.network import commands

        calls = []
        monkeypatch.setattr(commands, "os", SimpleNamespace(kill=lambda pid, signal: None))
        monkeypatch.setattr(commands, "time", SimpleNamespace(sleep=lambda _: None))
        monkeypatch.setattr(commands, "execute_command", lambda cmd: calls.append(cmd))
        with pytest.raises(CommandError, match="did not exit"):
            stop_process(123)
        assert calls == [["kill", "123"], ["kill", "-9", "123"]]

    def test_failed_dnsmasq_stop_preserves_tracking_for_retry(self, tmp_path):
        from wilab.network.dhcp import DhcpServer, DhcpServerError

        manager = DhcpServer.__new__(DhcpServer)
        config_file = tmp_path / "daemon.conf"
        config_file.write_text("", encoding="utf-8")
        process = MagicMock()
        process.stop.side_effect = [CommandError("permission denied"), None]
        manager._instances = {"dev0": {"process": process, "config_file": str(config_file)}}
        with pytest.raises(DhcpServerError):
            manager.stop("dev0")
        assert "dev0" in manager._instances
        assert config_file.exists()

        manager.stop("dev0")
        assert "dev0" not in manager._instances
        assert process.stop.call_count == 2


class TestHostapdInterfaceCleanup:
    def test_stop_leaves_interface_managed_and_down(self, tmp_path, monkeypatch):
        from wilab.wifi import hostapd

        manager = hostapd.HostapdManager.__new__(hostapd.HostapdManager)
        instance_dir = tmp_path / "ap"
        instance_dir.mkdir()
        config_file = instance_dir / "hostapd.conf"
        config_file.write_text("", encoding="utf-8")
        calls = []
        manager._instances = {
            "dev0": {
                "interface": "wlan0", "config_file": str(config_file),
                "control_dir": str(instance_dir / "ctrl"), "ssid": "test",
                "process": SimpleNamespace(stop=lambda: calls.append(("stop",))),
            }
        }
        monkeypatch.setattr(hostapd, "execute_command", lambda cmd: calls.append(("command", cmd)))

        manager.stop("dev0")

        assert calls == [
            ("stop",),
            ("command", ["ip", "link", "set", "wlan0", "down"]),
            ("command", ["iw", "dev", "wlan0", "set", "type", "managed"]),
            ("command", ["ip", "addr", "flush", "dev", "wlan0"]),
        ]
        assert "dev0" not in manager._instances

    @pytest.mark.parametrize("failure", ["process", "interface"])
    def test_cleanup_failure_is_retryable(self, tmp_path, monkeypatch, failure):
        from wilab.wifi import hostapd

        manager = hostapd.HostapdManager.__new__(hostapd.HostapdManager)
        instance_dir = tmp_path / "ap"
        instance_dir.mkdir()
        config_file = instance_dir / "hostapd.conf"
        config_file.write_text("", encoding="utf-8")
        stopped = []
        fail = True

        def stop():
            if fail and failure == "process":
                raise CommandTimeout("process did not exit")
            stopped.append(True)

        process = SimpleNamespace(stop=stop)
        manager._instances = {
            "dev0": {
                "interface": "wlan0", "config_file": str(config_file),
                "control_dir": str(instance_dir / "ctrl"), "ssid": "test",
                "process": process,
            }
        }

        def fail_on_managed(cmd):
            if fail and failure == "interface" and cmd[:2] == ["iw", "dev"]:
                raise CommandError("mode change failed")

        monkeypatch.setattr(hostapd, "execute_command", fail_on_managed)
        with pytest.raises(hostapd.HostapdError, match="mode change failed|process did not exit"):
            manager.stop("dev0")
        assert manager._instances["dev0"]["process"] is (process if failure == "process" else None)
        assert config_file.exists() == (failure == "process")
        fail = False
        manager.stop("dev0")
        assert stopped == [True]
        assert "dev0" not in manager._instances


@pytest.mark.parametrize("exits_after_kill", [True, False])
def test_foreground_stop_escalates_and_verifies_exit(exits_after_kill):
    child = MagicMock(pid=123)
    child.poll.return_value = None
    timeout = subprocess.TimeoutExpired("hostapd", 2)
    child.wait.side_effect = [timeout, 0 if exits_after_kill else timeout]
    process = ForegroundProcess(child)
    if exits_after_kill:
        process.stop()
    else:
        with pytest.raises(CommandStuck, match="stuck in the kernel"):
            process.stop()
        assert stuck_commands() == 1
        child.poll.return_value = 0  # it finally exits
        assert stuck_commands() == 0
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert child.wait.call_count == 2


def test_foreground_drains_large_output_and_keeps_only_recent_allowlisted_events():
    cmd = [
        sys.executable, "-c",
        (
            "import sys; out=sys.stderr.buffer; "
            "out.write(b'ssid=private-network\\n' * 5000); "
            "out.write(b'wlan0: AP-ENABLED\\n' * 20); "
            "out.write(b'x' * 4096 + b'wlan0: AP-DISABLED\\n'); "
            "out.write(b'nl80211: Scan timeout - try to abort it\\n')"
        ),
    ]
    process = start_foreground(cmd, classify_output=_classify_output)
    deadline = time.monotonic() + 5
    try:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert process.poll() == 0
        assert process.output_events(exited=True) == ("ap_enabled",) * 11 + ("scan_timeout",)
    finally:
        process.stop()


class TestIptablesWrapper:
    """Tests for iptables command wrapper."""
    
    def test_execute_iptables(self):
        """Test iptables wrapper."""
        # We can't actually run iptables in test, but we can mock it
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_iptables(['-L', '-n'])
            mock.assert_called_once()
            # Check that 'iptables' was prepended
            assert mock.call_args[0][0][0] == 'iptables'


class TestIpWrapper:
    """Tests for ip command wrapper."""
    
    def test_execute_ip(self):
        """Test ip command wrapper."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_ip(['addr', 'show'])
            mock.assert_called_once()
            assert mock.call_args[0][0][0] == 'ip'
    
    def test_execute_ip_addr_add(self):
        """Test ip addr add command."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = ''
            execute_ip(['addr', 'add', '192.168.1.1/24', 'dev', 'eth0'])
            call_args = mock.call_args[0][0]
            assert call_args[0] == 'ip'
            assert 'addr' in call_args
            assert 'add' in call_args


class TestSysctlWrapper:
    """Tests for sysctl command wrapper."""
    
    def test_sysctl_read(self):
        """Test reading sysctl value."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = '1\n'
            execute_sysctl('net.ipv4.ip_forward')
            mock.assert_called_once()
            call_args = mock.call_args[0][0]
            assert 'sysctl' in call_args
            assert '-n' in call_args
    
    def test_sysctl_write(self):
        """Test writing sysctl value."""
        with patch('wilab.network.commands.execute_command') as mock:
            mock.return_value = 'net.ipv4.ip_forward = 1\n'
            execute_sysctl('net.ipv4.ip_forward', '1')
            mock.assert_called_once()
            call_args = mock.call_args[0][0]
            assert 'sysctl' in call_args
            assert '-w' in call_args


class TestPkillWrapper:
    """Tests for pkill command wrapper."""
    
class TestCommandError:
    """Tests for CommandError exception."""
    
    def test_command_error_message(self):
        """Test CommandError contains useful message."""
        try:
            raise CommandError("Test error message")
        except CommandError as e:
            assert "Test error message" in str(e)
    
    def test_command_error_from_exception(self):
        """Test CommandError with from clause."""
        try:
            try:
                raise RuntimeError("Original error")
            except RuntimeError as e:
                raise CommandError("Wrapper error") from e
        except CommandError as e:
            assert "Wrapper error" in str(e)


class TestCommandIntegration:
    """Integration tests for command wrappers."""
    
    def test_command_output_captured(self):
        """Test that command output is captured correctly."""
        result = execute_command(['echo', 'test output'])
        assert 'test output' in result
        assert isinstance(result, str)
    
    def test_multiple_commands_sequence(self):
        """Test executing multiple commands in sequence."""
        result1 = execute_command(['echo', 'first'])
        result2 = execute_command(['echo', 'second'])
        assert 'first' in result1
        assert 'second' in result2
    
    def test_command_with_arguments(self):
        """Test command with multiple arguments."""
        result = execute_command(['echo', 'arg1', 'arg2', 'arg3'])
        assert 'arg1' in result
        assert 'arg2' in result
        assert 'arg3' in result


class TestCommandEdgeCases:
    """Tests for edge cases in command execution."""
    
    def test_empty_command_list(self, monkeypatch):
        """Test handling of empty command list."""
        run = MagicMock()
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(CommandError, match="Empty command"):
            execute_command([])
        run.assert_not_called()
    
    def test_command_with_pipes(self):
        """Test command with complex arguments."""
        # Note: pipes don't work directly with list form, must use actual pipe
        result = execute_command(['echo', 'test'])
        assert result is not None
    
    def test_command_with_unicode(self):
        """Test command handling unicode output."""
        result = execute_command(['echo', 'test-äöü'])
        assert 'test' in result


class _HungChild:
    """A Popen stand-in whose process ignores SIGKILL until released (STAB-1)."""

    def __init__(self, *args, **kwargs):
        import threading
        self.args = args[0] if args else kwargs.get("args")
        self.pid = 4242
        self.returncode = None
        self.killed = False
        self.released = threading.Event()

    def communicate(self, timeout=None):
        if not self.released.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.returncode = -9
        return "", ""

    def kill(self):
        self.killed = True

    def poll(self):
        return -9 if self.released.is_set() else None


class TestStuckCommands:
    """STAB-1: a command stuck in the kernel must not block the caller forever."""

    @pytest.fixture(autouse=True)
    def _no_stuck_children(self, monkeypatch):
        from wilab.network import commands

        monkeypatch.setattr(commands, "_stuck_children", [])

    def test_command_stuck_after_sigkill_raises_within_grace(self, monkeypatch):
        from wilab.network import commands

        children: list[_HungChild] = []

        def popen(*args, **kwargs):
            children.append(_HungChild(*args, **kwargs))
            return children[-1]

        monkeypatch.setattr(commands.subprocess, "Popen", popen)
        monkeypatch.setattr(commands, "KILL_GRACE", 0.2)
        start = time.monotonic()
        with pytest.raises(CommandStuck, match="stuck in the kernel: ip link set wlan0 down"):
            execute_command(["ip", "link", "set", "wlan0", "down"], timeout=0.1)
        assert time.monotonic() - start < 2
        assert children[0].killed
        assert stuck_commands() == 1
        children[0].released.set()  # the kernel finally lets it go
        assert stuck_commands() == 0

    def test_stuck_is_a_timeout_so_callers_keep_their_handling(self):
        assert issubclass(CommandStuck, CommandTimeout)
        assert issubclass(CommandStuck, CommandError)

    def test_killed_command_that_exits_is_a_plain_timeout(self):
        with pytest.raises(CommandTimeout) as info:
            execute_command(["sleep", "5"], timeout=0.2)
        assert not isinstance(info.value, CommandStuck)
        assert stuck_commands() == 0

    def test_non_utf8_output_does_not_raise(self):
        out = execute_command([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok\\xff')"])
        assert out.startswith("ok")


# --------------------------------------------------------------------------- NET-5

def test_expected_failures_are_not_logged_as_errors(monkeypatch, caplog):
    """A missing rule, nothing to delete or an unsupported setting is an answer, not an error."""
    import logging

    from wilab.network import commands, nat

    # The real runners (conftest replaces them), on top of a command that always fails.
    monkeypatch.setattr(commands, "_run", lambda cmd, timeout: (1, "", "Bad rule (does a matching rule exist?)"))
    monkeypatch.setattr(nat, "execute_iptables", execute_iptables)
    caplog.set_level(logging.DEBUG)
    assert nat.NatManager(upstream_interface="eth0")._rule_exists("nat", ["POSTROUTING", "-j", "MASQUERADE"]) is False
    with pytest.raises(CommandError):
        execute_command(["tc", "qdisc", "del", "dev", "wlan0", "root"], quiet=True)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    with pytest.raises(CommandError):
        execute_command(["tc", "qdisc", "add", "dev", "wlan0", "root"])
    assert [r.levelname for r in caplog.records if r.levelno >= logging.WARNING] == ["ERROR"]


def test_hostapd_failure_report_keeps_config_and_output_without_secrets(tmp_path):
    from wilab.wifi.hostapd import DEBUG_MAX_FILES, save_failure

    class Process:
        def poll(self):
            return -11

        def output_tail(self, *, exited=False):
            return ["wlan0: interface state UNINITIALIZED->COUNTRY_UPDATE", "nl80211: Set beacon"]

    for _ in range(DEBUG_MAX_FILES + 3):
        (tmp_path / f"0000-old-{_:03d}.log").write_text("x")
    config = "interface=wlan0\nssid=net\nwpa_passphrase=secret-pass\nsae_password=secret-sae\n"
    path = save_failure(str(tmp_path), "wlan0", RuntimeError("hostapd segfault on wlan0"), Process(), config)
    assert path is not None
    with open(path) as f:
        report = f.read()
    assert "exit code: -11" in report and "nl80211: Set beacon" in report and "ssid=net" in report
    assert "secret" not in report and "wpa_passphrase=<removed>" in report
    assert len(list(tmp_path.glob("*.log"))) == DEBUG_MAX_FILES


def test_foreground_process_keeps_the_last_output_lines_only_on_request():
    process = start_foreground(
        [sys.executable, "-c", "print('\\n'.join(str(i) for i in range(10)))"],
        classify_output=lambda line: None, keep_lines=3,
    )
    process._process.wait(timeout=5)
    assert process.output_tail(exited=True) == ["7", "8", "9"]
    quiet = start_foreground([sys.executable, "-c", "print(1)"], classify_output=lambda line: None)
    quiet._process.wait(timeout=5)
    assert quiet.output_tail(exited=True) == []


def test_any_oserror_from_popen_is_a_command_error(monkeypatch):
    """REV-1: EMFILE, ENOMEM, EACCES fail the command like any other error, so the rollback runs."""
    from wilab.network import commands

    def popen(*args, **kwargs):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(commands.subprocess, "Popen", popen)
    with pytest.raises(CommandError, match="Too many open files") as failure:
        execute_command(["ip", "link"])
    assert failure.value.returncode is None


def test_failed_command_carries_its_exit_code():
    with pytest.raises(CommandError) as failure:
        execute_command([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert failure.value.returncode == 3

