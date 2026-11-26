"""REV-6 (unit-test-5): starts that do not come from the create job can be cancelled too."""

import threading
import time
from unittest.mock import Mock

from conftest import network_body
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.models import NetworkStatus
from wilab.wifi import manager as manager_module
from wilab.wifi.manager import StartupFailure

# A fake start that ignores the cancel gives up after this long, so a failing test
# never hangs; every assertion below expects far less.
IGNORED_CANCEL_SECONDS = 3.0


def _blocking_start(started: threading.Event):
    """_start_network that runs until it is cancelled, as hostapd waiting for the AP does."""

    def start(device, req, expires_at, allow_internal_retry, cancelled=None):
        started.set()
        end = time.monotonic() + IGNORED_CANCEL_SECONDS
        while time.monotonic() < end:
            if cancelled is not None and cancelled():
                raise StartupFailure("AP start cancelled", stage="hostapd")
            time.sleep(0.01)
        raise StartupFailure("AP start never cancelled", stage="hostapd")

    return start


def _restorable(device):
    return NetworkStatus(
        interface=device, active=True, ssid="net", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4,
    )


def test_release_during_a_watchdog_restore_is_immediate(monkeypatch):
    """unit-test-5 (a): the release stops a watchdog restore instead of waiting for it."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(300)
    device = reservation.device_id
    started = threading.Event()
    monkeypatch.setattr(manager, "release_device", Mock())
    monkeypatch.setattr(manager, "_start_network", _blocking_start(started))
    quarantine = Mock()
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)

    restore = threading.Thread(
        target=manager.watchdog._restore_ap,
        args=(reservations, reservation, _restorable(device), False),
    )
    restore.start()
    assert started.wait(2)
    begin = time.monotonic()
    assert reservations.delete(reservation.reservation_id)
    elapsed = time.monotonic() - begin
    restore.join(timeout=5)
    assert elapsed < 1.0, elapsed
    assert device not in manager.active
    quarantine.assert_not_called()
    assert manager.watchdog.state(reservation) is None


def test_shutdown_cancels_a_running_create(monkeypatch):
    """unit-test-5 (b): shutdown_all cancels a create instead of waiting for its lock."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    monkeypatch.setattr(dependencies.get_channel_manager(), "validate_network", Mock())
    started = threading.Event()
    monkeypatch.setattr(manager, "_start_network", _blocking_start(started))
    release = Mock()
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(create_app()) as client:
        rid = client.post(
            "/api/v2/reservations", headers=headers, json={"duration_seconds": 300},
        ).json()["reservation_id"]
        body = network_body(ssid="shutdown", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
        assert client.post(f"/api/v2/reservations/{rid}/network", headers=headers, json=body).status_code == 202
        assert started.wait(2)
        monkeypatch.setattr(manager, "release_device", release)
        begin = time.monotonic()
        manager.shutdown_all()
        elapsed = time.monotonic() - begin
    assert elapsed < 1.0, elapsed
    assert not manager.start_jobs
    assert not manager.active
    assert release.called


def test_recovery_probe_avoids_dfs_channels(monkeypatch):
    """REV-6: the probe of a recovered radio never waits for a radar check under the lock."""
    manager = dependencies.get_manager(dependencies.get_config())
    device = manager.config.antennas[0].device_id
    start = Mock()
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", Mock(return_value=True))
    monkeypatch.setattr(manager.dhcp_server, "start", Mock())
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager, "release_device", Mock())
    monkeypatch.setattr(manager_module, "execute_ip", Mock())
    manager.probe_recovered_radio(device, "5ghz", 100)
    assert start.call_args.kwargs["channel"] == manager_module.PROBE_5GHZ_CHANNEL
    manager.probe_recovered_radio(device, "5ghz", 149)
    assert start.call_args.kwargs["channel"] == 149
    manager.probe_recovered_radio(device, "2.4ghz", 6)
    assert start.call_args.kwargs["channel"] == 6


def _three_antennas(monkeypatch, manager) -> list[str]:
    """The configured antenna plus two with an active network: shutdown_all releases all of them."""
    for extra in ("wlx-b", "wlx-c"):
        monkeypatch.setitem(manager.active, extra, NetworkStatus(interface=extra, active=True))
    return sorted({n.device_id for n in manager.config.antennas} | manager.active.keys())


def test_shutdown_releases_the_antennas_in_parallel(monkeypatch):
    """STAB-8: slow releases overlap, so the shutdown fits the unit's stop timeout."""
    manager = dependencies.get_manager(dependencies.get_config())
    devices = _three_antennas(monkeypatch, manager)
    released: list[str] = []

    def slow_release(device):
        time.sleep(0.3)
        released.append(device)

    monkeypatch.setattr(manager, "release_device", slow_release)
    begin = time.monotonic()
    manager.shutdown_all()
    assert time.monotonic() - begin < 0.3 * len(devices) - 0.1
    assert sorted(released) == sorted(devices)


def test_shutdown_gives_up_on_a_stuck_release(monkeypatch, caplog):
    """A release that never ends is logged, and the shutdown still returns in time."""
    manager = dependencies.get_manager(dependencies.get_config())
    stuck = threading.Event()
    monkeypatch.setattr(manager_module, "SHUTDOWN_TIMEOUT", 0.2)
    monkeypatch.setattr(manager, "release_device", lambda device: stuck.wait(5))
    begin = time.monotonic()
    manager.shutdown_all()
    stuck.set()
    assert time.monotonic() - begin < 1.0
    assert any("not released within" in r.getMessage() for r in caplog.records)


def test_a_failed_release_does_not_stop_the_others(monkeypatch, caplog):
    manager = dependencies.get_manager(dependencies.get_config())
    devices = _three_antennas(monkeypatch, manager)
    released: list[str] = []

    def release(device):
        if device == devices[0]:
            raise RuntimeError("hostapd did not stop")
        released.append(device)

    monkeypatch.setattr(manager, "release_device", release)
    manager.shutdown_all()
    assert sorted(released) == devices[1:]
    assert any(devices[0] in r.getMessage() and r.exc_info for r in caplog.records)
