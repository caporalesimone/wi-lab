"""Tests for keeping host network managers away from Wi-Lab radios."""

from wilab.network import unmanaged


def _setup(monkeypatch, tmp_path):
    (tmp_path / "systemd").mkdir()
    monkeypatch.setattr(unmanaged, "NETWORKD_RUNTIME_DIR", tmp_path / "systemd" / "network")
    monkeypatch.setattr(unmanaged, "NETWORKD_RULES", tmp_path / "systemd" / "network" / "00-wilab-unmanaged.network")
    commands: list[list[str]] = []
    monkeypatch.setattr(unmanaged, "execute_command", lambda cmd, **kwargs: commands.append(cmd) or "")
    return commands


def test_only_named_radios_are_touched_and_networkmanager_is_never_reloaded(monkeypatch, tmp_path):
    commands = _setup(monkeypatch, tmp_path)

    for _ in range(2):
        unmanaged.exclude_from_host_managers(["wlx2", "wlx1", "bad;name", "wlx1"])

    assert unmanaged.NETWORKD_RULES.read_text() == "[Match]\nName=wlx1 wlx2\n\n[Link]\nUnmanaged=yes\n"
    release = [["nmcli", "device", "set", n, "managed", "no"] for n in ("wlx1", "wlx2")]
    assert commands == [*release, ["networkctl", "reload"], *release]
    assert not any(c[:2] == ["nmcli", "general"] for c in commands)

    commands.clear()
    unmanaged.exclude_from_host_managers(["wlx1", "wlx2", "wlx3"])
    assert "wlx3" in unmanaged.NETWORKD_RULES.read_text()
    assert commands[-1] == ["networkctl", "reload"]


def test_no_networkd_rule_without_systemd(monkeypatch, tmp_path):
    commands = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(unmanaged, "NETWORKD_RUNTIME_DIR", tmp_path / "absent" / "network")
    unmanaged.exclude_from_host_managers(["wlx1"])
    assert commands == [["nmcli", "device", "set", "wlx1", "managed", "no"]]
    assert not (tmp_path / "absent").exists()
