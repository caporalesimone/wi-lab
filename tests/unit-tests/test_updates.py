"""Security updates that need a restart: detected, shown in /status, never acted on."""

import logging

import pytest
from fastapi.testclient import TestClient

from wilab import updates

MAPS = """\
7f1c00000000-7f1c00021000 r-xp 00000000 08:01 1234 /usr/lib/x86_64-linux-gnu/libexpat.so.1.10.2 (deleted)
7f1c00100000-7f1c00121000 r-xp 00000000 08:01 1235 /usr/lib/x86_64-linux-gnu/libssl.so.3
7f1c00200000-7f1c00201000 rw-s 00000000 00:01 99 /memfd:wayland (deleted)
7f1c00300000-7f1c00301000 rw-s 00000000 00:05 98 /dev/shm/sem.x (deleted)
7f1c00400000-7f1c00401000 r--p 00000000 08:01 97 /usr/bin/python3.14 (deleted)
7f1c00500000-7f1c00501000 r--p 00000000 08:01 96 /usr/share/locale/it/LC_MESSAGES/x.mo (deleted)
"""


def test_replaced_libraries_are_found_and_unrelated_deleted_maps_ignored(tmp_path):
    maps = tmp_path / "maps"
    maps.write_text(MAPS)
    assert updates.replaced_libraries(maps) == [
        "/usr/bin/python3.14", "/usr/lib/x86_64-linux-gnu/libexpat.so.1.10.2",
    ]


def test_reboot_required_with_its_packages(tmp_path):
    flag, pkgs = tmp_path / "reboot-required", tmp_path / "reboot-required.pkgs"
    assert updates.reboot_packages(flag, pkgs) is None
    flag.write_text("*** System restart required ***\n")
    pkgs.write_text("linux-image-7.0.0-45-generic\nlinux-base\nlinux-base\n")
    assert updates.reboot_packages(flag, pkgs) == ["linux-base", "linux-image-7.0.0-45-generic"]


def test_status_shows_the_restart_without_degrading(monkeypatch, tmp_path, context, app, caplog):
    headers = {"Authorization": f"Bearer {context.config.auth_token}"}
    with TestClient(app) as client:
        status = client.get("/api/v2/status", headers=headers).json()
        assert status["restart_required"] is None
        maps = tmp_path / "maps"
        maps.write_text(MAPS)
        monkeypatch.setattr(updates, "MAPS", maps)
        with caplog.at_level(logging.WARNING):
            status = client.get("/api/v2/status", headers=headers).json()
        required = status["restart_required"]
        assert required["service"] is True and required["system"] is False
        assert "restart Wi-Lab" in required["message"] and required["since"]
        assert status["status"]["health"] == "good"   # informational, not degraded
        assert sum("Security updates need a restart" in r.getMessage() for r in caplog.records) == 1
        since = required["since"]
        assert client.get("/api/v2/status", headers=headers).json()["restart_required"]["since"] == since
        detail = client.get("/api/v2/monitoring", headers=headers).json()["checks"]["updates"]
        assert detail["replaced_libraries"] == [
            "/usr/bin/python3.14", "/usr/lib/x86_64-linux-gnu/libexpat.so.1.10.2",
        ]
        flag = tmp_path / "reboot-required"
        flag.write_text("")
        monkeypatch.setattr(updates, "REBOOT_REQUIRED", flag)
        required = client.get("/api/v2/status", headers=headers).json()["restart_required"]
        assert required["system"] is True and "reboot" in required["message"]


# --------------------------------------------------------------------------- beyond Ubuntu


def _modules(tmp_path, *releases):
    root = tmp_path / "modules"
    for release in releases:
        (root / release).mkdir(parents=True)
        (root / release / "modules.dep").write_text("")
    return root


@pytest.mark.parametrize(("running", "installed", "expected"), [
    ("7.0.0-44-generic", ["7.0.0-43-generic", "7.0.0-44-generic"], None),                # Ubuntu, up to date
    ("7.0.0-44-generic", ["7.0.0-44-generic", "7.0.0-45-generic"], "7.0.0-45-generic"),  # Ubuntu, new kernel
    ("7.0.0-44-generic", ["7.0.0-44-generic", "7.0.0-45-lowlatency"], None),             # another flavour
    ("6.11.4-301.fc41.x86_64", ["6.11.4-301.fc41.x86_64", "6.12.1-200.fc41.x86_64"], "6.12.1-200.fc41.x86_64"),
    ("6.12.1-arch1-1", ["6.13.0-arch1-1"], "6.13.0-arch1-1"),                            # Arch: replaced in place
    ("6.4.0-150600.23-default", ["6.4.0-150600.23-default"], None),                      # openSUSE
])
def test_a_newer_kernel_is_found_on_any_distribution(tmp_path, running, installed, expected):
    assert updates.newer_kernel(running, _modules(tmp_path, *installed)) == expected


def test_reboot_from_a_new_kernel_or_zypper(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.os, "uname", lambda: type("U", (), {"release": "7.0.0-44-generic"})())
    monkeypatch.setattr(updates, "MODULES", _modules(tmp_path, "7.0.0-44-generic", "7.0.0-45-generic"))
    assert updates.reboot_packages(tmp_path / "none", tmp_path / "none") == ["kernel 7.0.0-45-generic"]
    monkeypatch.setattr(updates, "MODULES", _modules(tmp_path / "b", "7.0.0-44-generic"))
    assert updates.reboot_packages(tmp_path / "none", tmp_path / "none") is None
    needed = tmp_path / "reboot-needed"
    needed.write_text("")
    monkeypatch.setattr(updates, "REBOOT_NEEDED", needed)
    assert updates.reboot_packages(tmp_path / "none", tmp_path / "none") == []
