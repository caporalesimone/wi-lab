"""ARCH-11 D1: `make reload-drivers` reloads each module once, never the host's own."""

from unittest.mock import Mock

import pytest

import main
from wilab.network.commands import CommandError
from wilab.wifi import drivers


@pytest.fixture
def modprobe(monkeypatch):
    calls: list[list[str]] = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return ""

    monkeypatch.setattr(drivers, "execute_command", run)
    monkeypatch.setattr(drivers, "_present", lambda interface: True)
    return calls


MODULES = {"wlx1": "mt7921u", "wlx2": "mt7921u", "wlx3": "rtw88_8822bu", "ens18": "virtio_net", "wlp0": "iwlwifi"}


def module_of(interface):
    if interface not in MODULES:
        raise drivers.DriverError(f"no module for {interface}")
    return MODULES[interface]


def test_each_module_is_reloaded_once(modprobe):
    results = drivers.reload_drivers(["wlx1", "wlx2", "wlx3"], ["ens18"], module_of)
    assert [(r.module, r.interfaces, r.ok) for r in results] == [
        ("mt7921u", ["wlx1", "wlx2"], True), ("rtw88_8822bu", ["wlx3"], True),
    ]
    assert modprobe == [
        ["modprobe", "-r", "mt7921u"], ["modprobe", "mt7921u"],
        ["modprobe", "-r", "rtw88_8822bu"], ["modprobe", "rtw88_8822bu"],
    ]


def test_a_module_of_the_host_network_is_never_reloaded(modprobe):
    # A host on Wi-Fi: the upstream radio shares nothing, but a Wi-Lab radio could.
    MODULES["wlx4"] = "iwlwifi"
    try:
        results = drivers.reload_drivers(["wlx4", "wlx3"], ["wlp0", "lo"], module_of)
    finally:
        del MODULES["wlx4"]
    refused = next(r for r in results if r.module == "iwlwifi")
    assert not refused.ok and "wlp0" in refused.error
    assert ["modprobe", "-r", "iwlwifi"] not in modprobe
    assert ["modprobe", "-r", "rtw88_8822bu"] in modprobe


def test_a_failure_is_reported_and_the_others_go_on(monkeypatch, modprobe):
    def run(cmd, **kwargs):
        if cmd[-1] == "mt7921u":
            raise CommandError("in use")
        modprobe.append(cmd)
        return ""

    monkeypatch.setattr(drivers, "execute_command", run)
    results = drivers.reload_drivers(["wlx1", "wlx3", "wlx9"], [], module_of)
    assert {r.module: r.ok for r in results} == {"unknown": False, "mt7921u": False, "rtw88_8822bu": True}


def test_refused_while_the_service_runs(monkeypatch, capsys):
    monkeypatch.setattr(drivers, "execute_command", Mock(return_value="active\n"))
    assert main.reload_drivers_only(None) == main.EXIT_SERVICE_RUNNING
    assert "make stop" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["mt7921u", "rtw88_8822bu"])
def test_module_names_are_checked(monkeypatch, name):
    monkeypatch.setattr(drivers.os.path, "realpath", lambda link, strict: f"/sys/module/{name}")
    assert drivers.driver_module("wlx1") == name
    monkeypatch.setattr(drivers.os.path, "realpath", lambda link, strict: "/sys/module/bad;name")
    with pytest.raises(drivers.DriverError):
        drivers.driver_module("wlx1")
