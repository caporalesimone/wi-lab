"""Tests for runtime exclusion of Wi-Lab radios from host network managers."""

from wilab.network import unmanaged


def test_rules_are_written_once_and_reloaded_only_on_change(monkeypatch, tmp_path):
    (tmp_path / "nm").mkdir()
    (tmp_path / "systemd").mkdir()
    monkeypatch.setattr(unmanaged, "NM_RUNTIME_DIR", tmp_path / "nm")
    monkeypatch.setattr(unmanaged, "NM_RULES", tmp_path / "nm" / "conf.d" / "90-wilab-unmanaged.conf")
    monkeypatch.setattr(unmanaged, "NETWORKD_RUNTIME_DIR", tmp_path / "systemd" / "network")
    monkeypatch.setattr(unmanaged, "NETWORKD_RULES", tmp_path / "systemd" / "network" / "00-wilab-unmanaged.network")
    reloads: list[list[str]] = []
    monkeypatch.setattr(unmanaged, "execute_command", lambda cmd, **kwargs: reloads.append(cmd) or "")

    for _ in range(2):
        unmanaged.exclude_from_host_managers(["wlx2", "wlx1", "bad;name", "wlx1"])

    assert unmanaged.NM_RULES.read_text() == (
        "[device-wilab-unmanaged]\nmatch-device=interface-name:wlx1;interface-name:wlx2\nmanaged=0\n"
    )
    assert "unmanaged-devices" not in unmanaged.NM_RULES.read_text()
    assert unmanaged.NETWORKD_RULES.read_text() == "[Match]\nName=wlx1 wlx2\n\n[Link]\nUnmanaged=yes\n"
    release = [["nmcli", "device", "set", n, "managed", "no"] for n in ("wlx1", "wlx2")]
    assert reloads == [["nmcli", "general", "reload", "conf"], *release, ["networkctl", "reload"], *release]

    reloads.clear()
    unmanaged.exclude_from_host_managers(["wlx1", "wlx2", "wlx3"])
    assert "interface-name:wlx3" in unmanaged.NM_RULES.read_text()
    assert [c for c in reloads if "reload" in c] == [["nmcli", "general", "reload", "conf"], ["networkctl", "reload"]]
    assert not any("ens18" in " ".join(c) for c in reloads)


def test_nothing_is_written_without_the_managers(monkeypatch, tmp_path):
    monkeypatch.setattr(unmanaged, "NM_RUNTIME_DIR", tmp_path / "absent-nm")
    monkeypatch.setattr(unmanaged, "NETWORKD_RUNTIME_DIR", tmp_path / "absent" / "network")
    monkeypatch.setattr(unmanaged, "execute_command", lambda cmd, **kwargs: (_ for _ in ()).throw(AssertionError))
    unmanaged.exclude_from_host_managers(["wlx1"])
    assert list(tmp_path.iterdir()) == []
