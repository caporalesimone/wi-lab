"""A hostapd that crashes while starting must be reported as a crash, not as a bare exit code."""

from unittest.mock import MagicMock, patch

import pytest

from wilab.network.commands import CommandError, execute_command
from wilab.wifi import hostapd
from wilab.wifi.hostapd import HostapdError, HostapdManager


def completed(returncode: int) -> MagicMock:
    return MagicMock(returncode=returncode, stdout="", stderr="")


class TestSignalDetection:
    def test_a_command_killed_by_a_signal_is_named(self):
        with patch("wilab.network.commands.subprocess.run", return_value=completed(-11)):
            with pytest.raises(CommandError) as exc:
                execute_command(["hostapd", "-B", "x.conf"])
        assert exc.value.killed_by_signal == "SIGSEGV"
        assert exc.value.returncode == -11

    def test_a_normal_failure_is_not_a_signal(self):
        with patch("wilab.network.commands.subprocess.run", return_value=completed(1)):
            with pytest.raises(CommandError) as exc:
                execute_command(["hostapd", "-B", "x.conf"])
        assert exc.value.killed_by_signal is None

    def test_an_unknown_signal_number_is_still_reported(self):
        assert CommandError("x", returncode=-200).killed_by_signal == "signal 200"


class TestHostapdStart:
    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hostapd, "HOSTAPD_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(hostapd, "HOSTAPD_PID_DIR", str(tmp_path / "pids"))
        monkeypatch.setattr(hostapd.time, "sleep", lambda s: None)
        return HostapdManager()

    def start(self, manager, monkeypatch, error: CommandError):
        def fake(cmd, **kwargs):
            if cmd[0] == "hostapd":
                raise error
            return ""

        monkeypatch.setattr(hostapd, "execute_command", fake)
        monkeypatch.setattr(hostapd, "execute_iw", lambda args: "")
        return manager.start("net", "wlan0", "ssid", 6, "open", None, False, "2.4ghz")

    def test_a_crash_points_to_the_driver(self, manager, monkeypatch):
        with pytest.raises(HostapdError) as exc:
            self.start(manager, monkeypatch, CommandError("failed with code -11", returncode=-11))
        message = str(exc.value)
        assert "crashed (SIGSEGV)" in message and "wlan0" in message
        assert "dmesg" in message and "driver" in message

    def test_a_normal_failure_keeps_the_hostapd_message(self, manager, monkeypatch):
        error = CommandError("Command 'hostapd' failed with code 1: bad config", returncode=1)
        with pytest.raises(HostapdError, match="hostapd failed to start.*bad config"):
            self.start(manager, monkeypatch, error)
