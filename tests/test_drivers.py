"""Reloading the kernel driver of the WiFi adapters (wilab/network/drivers.py, main.py --reload-drivers)."""

import pytest

import main as cli
from wilab.network import drivers
from wilab.network.commands import CommandError
from wilab.network.drivers import DriverError, reload_driver, reload_drivers


class FakeSystem:
    """Three adapters, two of them on one module. Records what modprobe is asked to do.

    Time is simulated: sleeping advances a fake clock, so nothing really waits.
    """

    def __init__(self, monkeypatch, modules=None):
        self.modules = modules or {"wlan0": "rtw88_8822bu", "wlan1": "rtw88_8822bu", "wlan2": "mt76x2u"}
        self.present = set(self.modules)
        self.commands = []
        self.modprobe_error = None
        self.returns_after = 1.0  # seconds after loading before the adapters reappear (None: never)
        self.now = 0.0
        self._loaded_at = None
        self._unloaded = set()
        monkeypatch.setattr(drivers, "_read_module", self.read_module)
        monkeypatch.setattr(drivers, "_interface_present", lambda i: i in self.present)
        monkeypatch.setattr(drivers, "execute_command", self.execute)
        monkeypatch.setattr(drivers.time, "sleep", self.sleep)
        monkeypatch.setattr(drivers.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(drivers, "REAPPEAR_TIMEOUT", 5.0)

    def read_module(self, interface):
        if interface not in self.modules:
            raise DriverError(f"Cannot find the driver of {interface}")
        return self.modules[interface]

    def execute(self, cmd, **kwargs):
        self.commands.append(cmd)
        if self.modprobe_error and cmd[0] == "modprobe":
            raise CommandError(self.modprobe_error)
        if cmd[:2] == ["modprobe", "-r"]:
            gone = {i for i, m in self.modules.items() if m == cmd[2]}
            self._unloaded |= gone
            self.present -= gone
        elif cmd[0] == "modprobe":
            self._loaded_at = self.now
        return ""

    def sleep(self, seconds):
        self.now += seconds
        if (
            self._loaded_at is not None and self.returns_after is not None
            and self.now - self._loaded_at >= self.returns_after
        ):
            self.present |= self._unloaded


class TestDriverModule:
    def test_the_module_of_an_interface(self, monkeypatch):
        FakeSystem(monkeypatch)
        assert drivers.driver_module("wlan0") == "rtw88_8822bu"

    def test_an_unexpected_module_name_is_refused(self, monkeypatch):
        FakeSystem(monkeypatch, modules={"wlan0": "bad; rm -rf /"})
        with pytest.raises(DriverError, match="Unexpected driver name"):
            drivers.driver_module("wlan0")

    def test_an_interface_that_is_not_there_is_an_error(self, monkeypatch):
        FakeSystem(monkeypatch)
        with pytest.raises(DriverError, match="wlan9"):
            drivers.driver_module("wlan9")


class TestReloadDriver:
    def test_unloads_then_loads_the_module_and_waits_for_the_adapter(self, monkeypatch):
        system = FakeSystem(monkeypatch)
        assert reload_driver("wlan0") == "rtw88_8822bu"
        assert system.commands == [["modprobe", "-r", "rtw88_8822bu"], ["modprobe", "rtw88_8822bu"]]
        assert "wlan0" in system.present

    def test_a_modprobe_failure_is_reported(self, monkeypatch):
        system = FakeSystem(monkeypatch)
        system.modprobe_error = "Module is in use"
        with pytest.raises(DriverError, match="Cannot reload driver rtw88_8822bu.*in use"):
            reload_driver("wlan0")

    def test_an_interface_that_does_not_come_back_is_an_error(self, monkeypatch):
        system = FakeSystem(monkeypatch)
        system.returns_after = None
        with pytest.raises(DriverError, match="wlan0 did not come back"):
            reload_driver("wlan0")


class TestReloadDrivers:
    def test_a_module_shared_by_two_adapters_is_reloaded_once(self, monkeypatch):
        system = FakeSystem(monkeypatch)
        results = reload_drivers(["wlan0", "wlan1", "wlan2"])
        assert [(r.module, r.interfaces, r.ok) for r in results] == [
            ("rtw88_8822bu", ["wlan0", "wlan1"], True),
            ("mt76x2u", ["wlan2"], True),
        ]
        assert [c for c in system.commands if c[1] == "-r"] == [
            ["modprobe", "-r", "rtw88_8822bu"], ["modprobe", "-r", "mt76x2u"]
        ]

    def test_an_unknown_interface_does_not_stop_the_others(self, monkeypatch):
        FakeSystem(monkeypatch)
        results = reload_drivers(["wlan9", "wlan2"])
        assert [(r.module, r.ok) for r in results] == [("unknown", False), ("mt76x2u", True)]
        assert "wlan9" in results[0].error

    def test_a_failing_module_does_not_stop_the_others(self, monkeypatch):
        system = FakeSystem(monkeypatch)
        real = system.execute

        def fail_one(cmd, **kwargs):
            if cmd == ["modprobe", "-r", "rtw88_8822bu"]:
                raise CommandError("busy")
            return real(cmd, **kwargs)

        monkeypatch.setattr(drivers, "execute_command", fail_one)
        results = reload_drivers(["wlan0", "wlan2"])
        assert {r.module: r.ok for r in results} == {"rtw88_8822bu": False, "mt76x2u": True}


class TestServiceCheck:
    @pytest.mark.parametrize("state, running", [
        ("active", True), ("activating", True), ("inactive", False), ("failed", False),
    ])
    def test_service_states(self, monkeypatch, state, running):
        monkeypatch.setattr(drivers, "execute_command", lambda cmd, **kw: state + "\n")
        assert drivers.service_is_running() is running

    def test_without_systemd_there_is_no_service(self, monkeypatch):
        def missing(cmd, **kw):
            raise CommandError("Command not found: systemctl")

        monkeypatch.setattr(drivers, "execute_command", missing)
        assert drivers.service_is_running() is False


class TestReloadDriversCommand:
    @pytest.fixture
    def config(self, write_config):
        return str(write_config())

    def test_it_is_refused_while_the_service_runs(self, config, monkeypatch, capsys):
        monkeypatch.setattr(drivers, "service_is_running", lambda: True)
        called = []
        monkeypatch.setattr(drivers, "reload_drivers", lambda interfaces: called.append(interfaces))

        assert cli.main(["--config", config, "--reload-drivers"]) == cli.EXIT_SERVICE_RUNNING
        err = capsys.readouterr().err
        assert "Wi-Lab is running" in err and "all the networks must be turned off" in err
        assert called == []

    def test_it_reloads_the_configured_interfaces(self, config, monkeypatch, capsys):
        monkeypatch.setattr(drivers, "service_is_running", lambda: False)
        seen = []

        def fake(interfaces):
            seen.extend(interfaces)
            return [drivers.ReloadResult("rtw88_8822bu", list(interfaces))]

        monkeypatch.setattr(drivers, "reload_drivers", fake)
        assert cli.main(["--config", config, "--reload-drivers"]) == cli.EXIT_OK
        assert seen and "OK      rtw88_8822bu: reloaded" in capsys.readouterr().out

    def test_a_failed_reload_exits_with_an_error(self, config, monkeypatch, capsys):
        monkeypatch.setattr(drivers, "service_is_running", lambda: False)
        monkeypatch.setattr(
            drivers, "reload_drivers",
            lambda interfaces: [drivers.ReloadResult("rtw88_8822bu", list(interfaces), error="busy")],
        )
        assert cli.main(["--config", config, "--reload-drivers"]) == cli.EXIT_INVALID
        assert "FAILED  rtw88_8822bu" in capsys.readouterr().out

    def test_an_invalid_config_is_reported_and_nothing_is_reloaded(self, write_config, monkeypatch):
        path = str(write_config(remove=["networks"]))
        monkeypatch.setattr(drivers, "service_is_running", lambda: False)
        monkeypatch.setattr(drivers, "reload_drivers", lambda interfaces: pytest.fail("must not reload"))
        assert cli.main(["--config", path, "--reload-drivers"]) == cli.EXIT_INVALID
