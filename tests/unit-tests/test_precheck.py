"""NM-1: startup prechecks (fatal stops the service with 78, warnings only log)."""

import logging
from pathlib import Path

import pytest

import main
from wilab import precheck
from wilab.network.commands import CommandError


@pytest.fixture
def host(monkeypatch):
    """A host where every check passes; tests change one thing at a time."""
    state = {"uid": 0, "missing": set(), "nm": "inactive\n", "rules": {"nat": [], "forward": []}}

    def systemctl(cmd, **kwargs):
        assert cmd[:2] == ["systemctl", "is-active"]
        if isinstance(state["nm"], Exception):
            raise state["nm"]
        return state["nm"]

    monkeypatch.setattr(precheck.os, "geteuid", lambda: state["uid"])
    monkeypatch.setattr(precheck.shutil, "which", lambda cmd: None if cmd in state["missing"] else f"/usr/bin/{cmd}")
    monkeypatch.setattr(precheck, "execute_command", systemctl)
    monkeypatch.setattr(precheck, "list_wilab_rules", lambda: state["rules"])
    return state


def test_all_good_gives_no_finding(host, caplog):
    caplog.set_level(logging.INFO)
    findings = precheck.run_prechecks()
    assert findings == []
    assert precheck.log_findings(findings) is False
    assert "Startup prechecks passed" in caplog.text


def test_not_root_is_fatal(host):
    host["uid"] = 1000
    assert [(f.check, f.level) for f in precheck.run_prechecks()] == [("root", "fatal")]


def test_missing_command_is_fatal_and_named(host):
    host["missing"] = {"hostapd", "usbreset"}
    [finding] = precheck.run_prechecks()
    assert (finding.check, finding.level) == ("commands", "fatal")
    assert "hostapd" in finding.message and "usbreset" in finding.message


def test_commands_match_the_installer():
    installer = Path("install/01-preconditions/04-tools.sh").read_text()
    block = installer.split("REQUIRED_CMDS=(", 1)[1].split(")", 1)[0]
    listed = {line.strip().strip('"') for line in block.splitlines() if line.strip()}
    assert listed - {"python3", "systemctl"} == set(precheck.REQUIRED_COMMANDS)


def test_active_network_manager_is_a_warning(host):
    host["nm"] = "active\n"
    [finding] = precheck.run_prechecks()
    assert (finding.check, finding.level) == ("network_manager", "warning")
    assert "systemctl mask NetworkManager" in finding.message


def test_no_systemctl_says_nothing_about_network_manager(host):
    host["nm"] = CommandError("systemctl: not found")
    assert precheck.run_prechecks() == []


def test_leftover_rules_are_a_warning(host):
    host["rules"] = {"nat": ["wilab-nat x"], "forward": ["wilab-fwd y", "wilab-fwd z"]}
    [finding] = precheck.run_prechecks()
    assert (finding.check, finding.level) == ("leftover_rules", "warning")
    assert "3" in finding.message


def test_broken_check_does_not_stop_the_others(host, monkeypatch):
    monkeypatch.setattr(precheck, "list_wilab_rules", lambda: 1 / 0)
    host["uid"] = 1000
    assert [f.check for f in precheck.run_prechecks()] == ["root"]


def test_wpa_supplicant_warns_only_for_the_radios_it_manages(tmp_path):
    (tmp_path / "wlx01").touch()
    (tmp_path / "wlan9").touch()  # a host interface, not a Wi-Lab radio
    findings = precheck.wpa_supplicant_findings(["wlx01", "wlx02"], run_dir=tmp_path)
    assert [(f.check, f.level) for f in findings] == [("wpa_supplicant", "warning")]
    assert "wlx01" in findings[0].message
    assert precheck.wpa_supplicant_findings(["wlx02"], run_dir=tmp_path) == []


def test_wpa_supplicant_warning_is_logged_once_per_radio(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(precheck, "_wpa_warned", set())
    (tmp_path / "wlx01").touch()
    precheck.warn_wpa_supplicant(["wlx01"], run_dir=tmp_path)
    precheck.warn_wpa_supplicant(["wlx01"], run_dir=tmp_path)
    assert caplog.text.count("wpa_supplicant manages wlx01") == 1


def test_main_exits_78_on_a_fatal_finding(monkeypatch):
    monkeypatch.setattr(main, "run_prechecks", lambda: [precheck.Finding("root", "fatal", "x")])
    monkeypatch.setattr(main, "create_app", lambda: pytest.fail("create_app must not run"))
    monkeypatch.setattr(main, "get_config", lambda: pytest.fail("config must not load"))
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 78


def test_main_starts_with_only_warnings(monkeypatch, config):
    started = []
    monkeypatch.setattr(main, "run_prechecks", lambda: [precheck.Finding("network_manager", "warning", "x")])
    monkeypatch.setattr(main, "get_config", lambda: config)
    monkeypatch.setattr(main, "log_host_impact_warning", lambda: None)
    monkeypatch.setattr(main.uvicorn, "run", lambda *a, **k: started.append(1))
    main.main()
    assert started == [1]


def test_unit_does_not_restart_on_78():
    assert "RestartPreventExitStatus=78" in Path("install/systemd/wi-lab.service.template").read_text()
