"""AP watchdog: restore budget (WD-1), retries after a failed restore (WD-2) and DHCP repair (WD-3)."""

from unittest.mock import Mock

import pytest
from conftest import network_body
from fastapi.testclient import TestClient

from wilab import heartbeat
from wilab.api import create_app, dependencies
from wilab.models import NetworkStatus
from wilab.wifi import watchdog as watchdog_module
from wilab.wifi.manager import StartupFailure


@pytest.fixture(autouse=True)
def _no_heartbeat(monkeypatch):
    # The tests replace time.monotonic with a scripted clock; heartbeats would consume it.
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)


def _setup(monkeypatch, times, recreate_at=None):
    """Run the watch loop once per value in `times` with hostapd always dead."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(manager.active, device, NetworkStatus(interface=device, active=True))
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=False))
    clock = iter(times)
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: next(clock))
    flags: list[bool] = []

    def restore(_reservations, _reservation, _status, exhausted):
        flags.append(exhausted)
        if recreate_at is not None and len(flags) == recreate_at:
            # The client deleted and recreated the network: a new status object.
            manager.active[device] = NetworkStatus(interface=device, active=True)

    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(
        manager.watchdog.stopping, "wait", Mock(side_effect=[False] * len(times) + [True]),
    )
    manager.watchdog._watch(reservations, device)
    return flags


def test_second_ap_failure_is_restored_not_quarantined(monkeypatch):
    # Before WD-1 the second failure in the life of a network quarantined the adapter.
    assert _setup(monkeypatch, [0.0, 86400.0]) == [False, False]


def test_budget_is_three_restores_per_hour(monkeypatch):
    assert _setup(monkeypatch, [0.0, 600.0, 1200.0, 1800.0]) == [False, False, False, True]


def test_old_restores_leave_the_window(monkeypatch):
    times = [0.0, 1000.0, 2000.0, 3601.0, 3700.0]
    # At 3601 the restore at 0 is older than an hour; at 3700 three restores
    # (1000, 2000, 3601) are inside the window again.
    assert _setup(monkeypatch, times) == [False, False, False, False, True]


def test_recreating_the_network_does_not_reset_the_budget(monkeypatch):
    flags = _setup(monkeypatch, [0.0, 10.0, 20.0, 30.0], recreate_at=2)
    assert flags == [False, False, False, True]


@pytest.mark.parametrize("exhausted", [False, True])
def test_exhausted_budget_quarantines_instead_of_restarting(monkeypatch, exhausted):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    device = reservation.device_id
    status = NetworkStatus(
        interface=device, active=True, ssid="net", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4,
    )
    monkeypatch.setattr(manager, "release_device", Mock())
    start = Mock()
    quarantine = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)
    manager.watchdog._restore_ap(reservations, reservation, status, exhausted)
    assert start.called is not exhausted
    assert quarantine.called is exhausted


# --------------------------------------------------------------------------- WD-2

def _restorable(device):
    return NetworkStatus(
        interface=device, active=True, ssid="net", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4,
    )


def _failed_restore(monkeypatch, now=1000.0):
    """A restore that fails for a non-radio reason; returns the pieces of the setup."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setattr(manager, "release_device", Mock())
    start = Mock(side_effect=StartupFailure("gateway setup failed"))
    monkeypatch.setattr(manager, "start_network", start)
    quarantine = Mock()
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: now)
    manager.watchdog._restore_ap(reservations, reservation, _restorable(device), False)
    return config, manager, reservations, reservation, start, quarantine


def test_failed_restore_is_reported_and_scheduled(monkeypatch):
    _, manager, _, reservation, start, quarantine = _failed_restore(monkeypatch)
    assert start.call_args.kwargs["allow_internal_retry"] is True
    quarantine.assert_not_called()
    assert manager.watchdog.state(reservation) == "restore_failed"
    pending = manager.watchdog._pending[reservation.device_id]
    assert (pending.failures, pending.next_try) == (1, 1000.0 + watchdog_module.RETRY_BACKOFF[0])


def _run_ticks(monkeypatch, manager, reservations, device, times):
    """One watch-loop tick at each time in `times`; the clock stays put within a tick."""
    pending_times = list(times)
    now = [pending_times[0]]

    def wait(_seconds):
        if not pending_times:
            return True
        now[0] = pending_times.pop(0)
        return False

    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(manager.watchdog.stopping, "wait", wait)
    manager.watchdog._watch(reservations, device)


def test_watchdog_retries_with_backoff_until_the_ap_is_back(monkeypatch):
    _, manager, reservations, reservation, start, _ = _failed_restore(monkeypatch)
    device = reservation.device_id
    calls = []

    def start_again(target, request, expires_at, *, allow_internal_retry):
        calls.append(allow_internal_retry)
        if len(calls) == 1:
            raise StartupFailure("gateway setup failed again")
        manager.active[device] = _restorable(device)

    start.side_effect = start_again
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", Mock(return_value=True))
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
    # 1010: not due; 1015: retry 1 fails (next at 1015 + 30); 1040: not due;
    # 1045: retry 2 succeeds; 1050: normal supervision of the restored AP.
    _run_ticks(monkeypatch, manager, reservations, device, [1010.0, 1015.0, 1040.0, 1045.0, 1050.0])
    assert calls == [True, True]
    assert device not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None
    assert reservations.get(reservation.reservation_id) is reservation


def test_radio_failure_on_retry_quarantines(monkeypatch):
    _, manager, reservations, reservation, start, quarantine = _failed_restore(monkeypatch)
    start.side_effect = StartupFailure("beacon setup failed", radio=True)
    _run_ticks(monkeypatch, manager, reservations, reservation.device_id, [1015.0])
    quarantine.assert_called_once()
    assert quarantine.call_args.kwargs["radio_fault"] is True
    assert reservation.device_id not in manager.watchdog._pending


def test_release_stops_the_retries(monkeypatch):
    _, manager, reservations, reservation, start, _ = _failed_restore(monkeypatch)
    reservation.release_requests += 1
    _run_ticks(monkeypatch, manager, reservations, reservation.device_id, [1015.0])
    assert start.call_count == 1  # only the original restore
    assert reservation.device_id not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None


def test_api_reports_restore_failed_and_delete_stops_retries(monkeypatch):
    config, manager, _, reservation, _, _ = _failed_restore(monkeypatch)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v1/reservations/{reservation.reservation_id}/network"
    with TestClient(create_app()) as client:
        network = client.get(path, headers=headers).json()
        assert (network["active"], network["runtime_state"]) == (False, "restore_failed")
        system = client.get("/api/v1/status", headers=headers).json()
        assert system["status"] == "degraded"
        assert system["networks"][0]["runtime_state"] == "restore_failed"
        assert client.delete(path, headers=headers).status_code == 200
        assert manager.watchdog.state(reservation) is None
        assert client.delete(path, headers=headers).status_code == 409
        assert client.get(f"/api/v1/reservations/{reservation.reservation_id}", headers=headers).status_code == 200


def test_new_create_replaces_the_pending_restore(monkeypatch):
    config, manager, _, reservation, start, _ = _failed_restore(monkeypatch)
    start.side_effect = None
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v1/reservations/{reservation.reservation_id}/network"
    body = network_body(ssid="new", channel=1, band="2.4ghz", encryption="open", tx_power_level=4)
    with TestClient(create_app()) as client:
        assert client.post(path, headers=headers, json=body).status_code == 200
    assert reservation.device_id not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None


# --------------------------------------------------------------------------- WD-3

def _dhcp_setup(monkeypatch, ticks, dhcp_restart_works=True):
    """Run the watch loop once per (time, dnsmasq running) tick with hostapd healthy.

    Returns the events: "dhcp" for a DHCP-only restart, "ap" for a network restore.
    """
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(
        manager.active, device, NetworkStatus(interface=device, active=True, subnet="192.0.2.0/24"),
    )
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", Mock(return_value=True))
    clock = {"now": 0.0, "dhcp": True}
    tick_iter = iter(ticks)

    def wait(_timeout):
        try:
            clock["now"], clock["dhcp"] = next(tick_iter)
        except StopIteration:
            return True
        return False

    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(manager.dhcp_server, "is_running", lambda _device: clock["dhcp"])
    monkeypatch.setattr(manager.watchdog.stopping, "wait", wait)
    events: list[str] = []
    states: list[str | None] = []

    def restore_dhcp(_reservations, res, _status):
        events.append("dhcp")
        if dhcp_restart_works:
            manager.watchdog.states.pop(device, None)
        else:
            manager.watchdog.states[device] = (res, "dhcp_failed")
        states.append(manager.watchdog.state(res))

    def restore_ap(_reservations, _res, _status, exhausted):
        events.append("ap-exhausted" if exhausted else "ap")

    monkeypatch.setattr(manager.watchdog, "_restore_dhcp", restore_dhcp)
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore_ap)
    manager.watchdog._watch(reservations, device)
    return events


def test_dnsmasq_death_is_repaired_more_than_once(monkeypatch):
    # Before WD-3 the second death left the network in dhcp_failed for good.
    ticks = [(0.0, False), (5.0, True), (600.0, False), (605.0, True), (1200.0, False)]
    assert _dhcp_setup(monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp"]


def test_fourth_dhcp_failure_in_an_hour_restarts_the_network(monkeypatch):
    ticks = [
        (0.0, False), (5.0, True), (10.0, False), (15.0, True), (20.0, False), (25.0, True),
        (30.0, False), (35.0, False),
    ]
    assert _dhcp_setup(monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp", "ap"]


def test_failed_dhcp_restart_restarts_the_network_on_the_next_tick(monkeypatch):
    ticks = [(0.0, False), (5.0, False)]
    assert _dhcp_setup(monkeypatch, ticks, dhcp_restart_works=False) == ["dhcp", "ap"]


def test_dhcp_budget_renews_after_the_window(monkeypatch):
    ticks = [
        (0.0, False), (5.0, True), (10.0, False), (15.0, True), (20.0, False), (25.0, True),
        (3700.0, False),
    ]
    assert _dhcp_setup(monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp", "dhcp"]


def test_a_half_stopped_network_is_not_repaired(monkeypatch):
    """After a stop that did not complete (hostapd stuck), the watchdog must not undo the stop."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    device = reservations.create(0).device_id
    monkeypatch.setitem(manager.active, device, NetworkStatus(interface=device, active=True))
    monkeypatch.setattr(manager, "_stop_failed", {device})
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=False))
    restore = Mock()
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(manager.watchdog, "_restore_dhcp", restore)
    _run_ticks(monkeypatch, manager, reservations, device, [0.0, 5.0, 10.0, 15.0])
    restore.assert_not_called()
