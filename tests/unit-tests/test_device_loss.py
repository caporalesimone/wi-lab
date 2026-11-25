"""Adapters that disconnect, and quarantined adapters that must come back.

Fable WD-4 (quarantine has no way out), WD-5 (a vanished interface cannot be
cleaned up) and the classification of a vanished interface as a radio fault.
Reproduces the 2026-11-23 12:23 incident: the USB adapter dropped during a
create, the rollback failed on "Cannot find device", the adapter came back
6 s later but stayed "unavailable" until the service was restarted.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import network_body
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.models import NetworkCreateRequest
from wilab.network.commands import CommandError
from wilab.reservation import ReservationManager
from wilab.wifi import hostapd, recovery
from wilab.wifi import manager as manager_module
from wilab.wifi.interface import InterfaceError
from wilab.wifi.manager import StartupFailure

RESERVE = "/api/v1/reservations"
PAYLOAD = {
    "ssid": "loss-test", "channel": 36, "band": "5ghz",
    "encryption": "open", "tx_power_level": 4,
}
REQUEST = NetworkCreateRequest.model_validate(PAYLOAD)


def _manager():
    return dependencies.get_manager(dependencies.get_config())


# --- WD-5: stopping hostapd on an interface that no longer exists ----------------------


def test_hostapd_stop_skips_reset_of_a_vanished_interface(monkeypatch, tmp_path):
    mgr = hostapd.HostapdManager()
    control_dir = tmp_path / "ap" / "ctrl"
    control_dir.mkdir(parents=True)
    config_file = tmp_path / "ap" / "hostapd.conf"
    config_file.write_text("interface=wlan0\n")
    process = SimpleNamespace(stop=Mock())
    mgr._instances["wlan0"] = {
        "interface": "wlan0", "config_file": str(config_file), "control_dir": str(control_dir),
        "process": process, "ssid": "x",
    }
    run = Mock(side_effect=CommandError('Cannot find device "wlan0"'))
    monkeypatch.setattr(hostapd, "execute_command", run)
    monkeypatch.setattr(hostapd, "interface_present", lambda iface: False)

    mgr.stop("wlan0")

    run.assert_not_called()
    process.stop.assert_called_once()
    assert "wlan0" not in mgr._instances
    assert not config_file.exists()


def test_hostapd_stop_still_resets_a_present_interface(monkeypatch, tmp_path):
    mgr = hostapd.HostapdManager()
    control_dir = tmp_path / "ap" / "ctrl"
    control_dir.mkdir(parents=True)
    mgr._instances["wlan0"] = {
        "interface": "wlan0", "config_file": str(tmp_path / "none.conf"),
        "control_dir": str(control_dir), "process": None, "ssid": "x",
    }
    run = Mock(return_value="")
    monkeypatch.setattr(hostapd, "execute_command", run)
    monkeypatch.setattr(hostapd, "interface_present", lambda iface: True)

    mgr.stop("wlan0")

    assert [c.args[0][:2] for c in run.call_args_list] == [["ip", "link"], ["iw", "dev"], ["ip", "addr"]]


def test_release_device_succeeds_after_the_adapter_vanished(monkeypatch, tmp_path):
    """Before WD-5 this raised RuntimeError forever and the adapter could not be reused."""
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    control_dir = tmp_path / "ap" / "ctrl"
    control_dir.mkdir(parents=True)
    mgr.hostapd_manager._instances[device] = {
        "interface": device, "config_file": str(tmp_path / "h.conf"),
        "control_dir": str(control_dir), "process": None, "ssid": "x",
    }
    monkeypatch.setattr(
        hostapd, "execute_command", Mock(side_effect=CommandError(f'Cannot find device "{device}"')),
    )
    monkeypatch.setattr(hostapd, "interface_present", lambda iface: False)

    mgr.release_device(device)

    assert device not in mgr.hostapd_manager._instances
    assert device not in mgr.active


# --- Classification: a vanished interface is a radio failure -----------------------------


def test_interface_vanishing_during_start_is_a_radio_failure(monkeypatch):
    """The 12:23 case: hostapd exits with code 1 because the USB adapter dropped."""
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    present = {"value": True}
    monkeypatch.setattr(manager_module, "interface_present", lambda iface: present["value"])

    def start(**kwargs):
        present["value"] = False
        raise hostapd.HostapdError(f"hostapd exited with code 1 on {device}")

    start_mock = Mock(side_effect=start)
    monkeypatch.setattr(mgr.hostapd_manager, "start", start_mock)

    with pytest.raises(StartupFailure) as error:
        mgr.start_network(device, REQUEST)

    assert error.value.radio is True
    assert error.value.cleanup_failed is False
    assert "disappeared" in str(error.value)
    start_mock.assert_called_once()  # no internal retry while the adapter is gone
    assert device not in mgr.active


def test_interface_vanishing_with_failed_cleanup_is_still_a_radio_failure(monkeypatch):
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    present = {"value": True}
    monkeypatch.setattr(manager_module, "interface_present", lambda iface: present["value"])

    def start(**kwargs):
        present["value"] = False
        raise hostapd.HostapdError("hostapd exited with code 1")

    monkeypatch.setattr(mgr.hostapd_manager, "start", start)
    releases = iter([None, RuntimeError("cleanup failed")])

    def release(device_id):
        result = next(releases)
        if result is not None:
            raise result

    monkeypatch.setattr(mgr, "release_device", release)

    with pytest.raises(StartupFailure) as error:
        mgr.start_network(device, REQUEST)
    assert (error.value.radio, error.value.cleanup_failed) == (True, True)


@pytest.mark.parametrize("present, expected", [(False, StartupFailure), (True, ValueError)])
def test_missing_interface_at_validation(monkeypatch, present, expected):
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    monkeypatch.setattr(manager_module, "interface_present", lambda iface: present)

    def missing(iface):
        raise InterfaceError(f"Interface {iface} does not exist")

    monkeypatch.setattr(manager_module, "validate_interface_exists", missing)
    with pytest.raises(expected) as error:
        mgr.start_network(device, REQUEST)
    if expected is StartupFailure:
        assert error.value.radio is True


def test_api_vanished_interface_returns_retry_later_not_quarantine(monkeypatch):
    """Client contract: 409/1001 with Retry-After; reservation and adapter are kept."""
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    present = {"value": True}
    monkeypatch.setattr(manager_module, "interface_present", lambda iface: present["value"])

    def start(**kwargs):
        present["value"] = False
        raise hostapd.HostapdError("hostapd exited with code 1")

    monkeypatch.setattr(mgr.hostapd_manager, "start", start)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(create_app()) as client:
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).json()["reservation_id"]
        result = client.post(f"/api/v1/reservations/{rid}/network", headers=headers, json=network_body(**PAYLOAD))
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == 1001
        assert result.headers["Retry-After"] == "5"
        assert client.get(f"{RESERVE}/{rid}", headers=headers).status_code == 200
        assert dependencies.get_reservation_manager(config).recovery_snapshot() == {}


# --- WD-4: unavailable adapters are re-probed with backoff ------------------------------


@pytest.fixture
def unavailable(monkeypatch):
    """One quarantined adapter with no recovery running, and mocked probe steps."""
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    reservations = ReservationManager([device])
    reservations.quarantine(reservations.create(60), recovering=False)
    steps = SimpleNamespace(
        release=Mock(), quiesce=Mock(), idle=Mock(), probe=Mock(), present=True,
    )
    monkeypatch.setattr(mgr, "release_device", steps.release)
    monkeypatch.setattr(mgr, "probe_recovered_radio", steps.probe)
    monkeypatch.setattr(recovery, "_quiesce", steps.quiesce)
    monkeypatch.setattr(recovery, "_require_idle", steps.idle)
    monkeypatch.setattr(recovery, "interface_present", lambda iface: steps.present)
    return mgr, device, reservations, steps


def test_unavailable_adapter_is_reprobed_and_released(unavailable):
    mgr, device, reservations, steps = unavailable

    mgr.recovery.reprobe_unavailable(reservations, now=0.0)
    steps.probe.assert_not_called()  # first attempt waits REPROBE_DELAYS[0]
    mgr.recovery.reprobe_unavailable(reservations, now=recovery.REPROBE_DELAYS[0] - 0.1)
    steps.probe.assert_not_called()

    mgr.recovery.reprobe_unavailable(reservations, now=recovery.REPROBE_DELAYS[0])

    steps.probe.assert_called_once_with(device, *recovery.DEFAULT_PROBE_RADIO)
    steps.release.assert_called_once_with(device)
    assert reservations.recovery_snapshot() == {}
    assert reservations.create(60).device_id == device


def test_failed_reprobes_back_off(unavailable):
    mgr, device, reservations, steps = unavailable
    steps.probe.side_effect = CommandError("probe failed")
    delays = recovery.REPROBE_DELAYS

    now = 0.0
    mgr.recovery.reprobe_unavailable(reservations, now=now)
    now += delays[0]
    for failures in range(1, len(delays) + 2):
        mgr.recovery.reprobe_unavailable(reservations, now=now)
        assert steps.probe.call_count == failures
        delay = delays[min(failures, len(delays) - 1)]
        assert mgr.recovery._reprobe[device] == (failures, now + delay)
        mgr.recovery.reprobe_unavailable(reservations, now=now + delay - 1)
        assert steps.probe.call_count == failures
        now += delay
    assert reservations.recovery_snapshot() == {device: False}


def test_absent_adapter_is_not_probed(unavailable):
    mgr, device, reservations, steps = unavailable
    steps.present = False
    mgr.recovery.reprobe_unavailable(reservations, now=0.0)
    mgr.recovery.reprobe_unavailable(reservations, now=1000.0)
    steps.probe.assert_not_called()
    steps.release.assert_not_called()
    assert mgr.recovery._reprobe[device][0] == 1
    assert reservations.recovery_snapshot() == {device: False}


def test_recovering_adapter_is_left_to_usb_recovery(monkeypatch):
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    reservations = ReservationManager([device])
    reservations.quarantine(reservations.create(60), recovering=True)
    probe = Mock()
    monkeypatch.setattr(mgr, "probe_recovered_radio", probe)
    mgr.recovery.reprobe_unavailable(reservations, now=0.0)
    mgr.recovery.reprobe_unavailable(reservations, now=10_000.0)
    probe.assert_not_called()
    assert mgr.recovery._reprobe == {}


def test_reprobe_uses_the_band_and_channel_of_the_last_network(unavailable):
    mgr, device, reservations, steps = unavailable
    mgr.recovery.remember_radio(device, "5ghz", 36)
    mgr.recovery.reprobe_unavailable(reservations, now=0.0)
    mgr.recovery.reprobe_unavailable(reservations, now=recovery.REPROBE_DELAYS[0])
    steps.probe.assert_called_once_with(device, "5ghz", 36)


def test_quarantine_remembers_radio(monkeypatch):
    mgr = _manager()
    device = mgr.config.antennas[0].device_id
    reservations = ReservationManager([device])
    mgr.quarantine_radio(
        reservations, reservations.create(60), radio_fault=False, band="5ghz", channel=36,
    )
    assert mgr.recovery._last_radio[device] == ("5ghz", 36)


def test_api_cleanup_failure_quarantine_heals_without_restart(monkeypatch):
    """Fable WD-4 reproduction: cleanup_failed -> unavailable -> probe OK -> allocatable."""
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    monkeypatch.setattr(
        mgr, "start_network",
        Mock(side_effect=StartupFailure("rollback failed", cleanup_failed=True)),
    )
    schedule = Mock()
    monkeypatch.setattr(mgr.recovery, "schedule", schedule)
    monkeypatch.setattr(mgr, "probe_recovered_radio", Mock())
    monkeypatch.setattr(recovery, "_quiesce", Mock())
    monkeypatch.setattr(recovery, "_require_idle", Mock())
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(create_app()) as client:
        reservations = dependencies.get_reservation_manager(config)
        device = config.antennas[0].device_id
        # Keep the other adapters busy so the quarantined one is the only candidate.
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).json()["reservation_id"]
        assert reservations.get(rid).device_id == device
        for _ in config.antennas[1:]:
            assert client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).status_code == 200
        result = client.post(f"/api/v1/reservations/{rid}/network", headers=headers, json=network_body(**PAYLOAD))
        assert (result.status_code, result.json()["detail"]["code"]) == (503, 1003)
        schedule.assert_not_called()
        status = client.get("/api/v1/status", headers=headers).json()
        assert status["status"] == "degraded"
        assert status["networks"][0]["recovery_state"] == "unavailable"
        assert client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).status_code == 503

        mgr.recovery.reprobe_unavailable(reservations, now=0.0)
        mgr.recovery.reprobe_unavailable(reservations, now=recovery.REPROBE_DELAYS[0])

        status = client.get("/api/v1/status", headers=headers).json()
        assert "recovery_state" not in status["networks"][0]
        assert client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).status_code == 200
