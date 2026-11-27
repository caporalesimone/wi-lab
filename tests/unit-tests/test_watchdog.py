"""AP watchdog: restore budget (WD-1), retries after a failed restore (WD-2) and DHCP repair (WD-3)."""

import threading
import time
from unittest.mock import Mock

import pytest
from conftest import active_network, create_network, network_body
from fastapi.testclient import TestClient

from wilab.wifi.hostapd import Probe
from wilab import heartbeat
from wilab.models import NetworkStatus
from wilab.wifi import watchdog as watchdog_module
from wilab.wifi.failures import FailureKind
from wilab.wifi.manager import StartupFailure


@pytest.fixture(autouse=True)
def _no_heartbeat(monkeypatch):
    # The tests replace time.monotonic with a scripted clock; heartbeats would consume it.
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)


def _setup(context, monkeypatch, times, recreate_at=None):
    """Run the watch loop once per value in `times` with hostapd always dead."""
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=False))
    clock = iter(times)
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: next(clock))
    flags: list[bool] = []

    def restore(_reservations, _reservation, _status, exhausted):
        flags.append(exhausted)
        if recreate_at is not None and len(flags) == recreate_at:
            # The client deleted and recreated the network: a new status object.
            manager.active[device] = active_network(interface=device)

    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(
        manager.watchdog, "_pause", Mock(side_effect=[False] * len(times) + [True]),
    )
    manager.watchdog._watch(reservations, device)
    return flags


def test_second_ap_failure_is_restored_not_quarantined(monkeypatch, context):
    # Before WD-1 the second failure in the life of a network quarantined the adapter.
    assert _setup(context, monkeypatch, [0.0, 86400.0]) == [False, False]


def test_budget_is_three_restores_per_hour(monkeypatch, context):
    assert _setup(context, monkeypatch, [0.0, 600.0, 1200.0, 1800.0]) == [False, False, False, True]


def test_old_restores_leave_the_window(monkeypatch, context):
    times = [0.0, 1000.0, 2000.0, 3601.0, 3700.0]
    # At 3601 the restore at 0 is older than an hour; at 3700 three restores
    # (1000, 2000, 3601) are inside the window again.
    assert _setup(context, monkeypatch, times) == [False, False, False, False, True]


def test_recreating_the_network_does_not_reset_the_budget(monkeypatch, context):
    flags = _setup(context, monkeypatch, [0.0, 10.0, 20.0, 30.0], recreate_at=2)
    assert flags == [False, False, False, True]


@pytest.mark.parametrize("exhausted", [False, True])
def test_exhausted_budget_quarantines_instead_of_restarting(monkeypatch, exhausted, context):
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(60)
    device = reservation.device_id
    status = active_network(
        interface=device, ssid="net", channel=1, band="2.4ghz",
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
    return active_network(
        interface=device, ssid="net", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4,
    )


def _failed_restore(context, monkeypatch, now=1000.0):
    """A restore that fails for a non-radio reason; returns the pieces of the setup."""
    config = context.config
    manager = context.manager
    reservations = context.reservations
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


def test_failed_restore_is_reported_and_scheduled(monkeypatch, context):
    _, manager, _, reservation, start, quarantine = _failed_restore(context, monkeypatch)
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
    monkeypatch.setattr(manager.watchdog, "_pause", wait)
    manager.watchdog._watch(reservations, device)


def test_watchdog_retries_with_backoff_until_the_ap_is_back(monkeypatch, context):
    _, manager, reservations, reservation, start, _ = _failed_restore(context, monkeypatch)
    device = reservation.device_id
    calls = []

    def start_again(target, request, expires_at, *, allow_internal_retry, cancelled):
        calls.append(allow_internal_retry)
        if len(calls) == 1:
            raise StartupFailure("gateway setup failed again")
        manager.active[device] = _restorable(device)

    start.side_effect = start_again
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager.hostapd_manager, "probe", Mock(return_value=Probe(True)))
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
    # 1010: not due; 1015: retry 1 fails (next at 1015 + 30); 1040: not due;
    # 1045: retry 2 succeeds; 1050: normal supervision of the restored AP.
    _run_ticks(monkeypatch, manager, reservations, device, [1010.0, 1015.0, 1040.0, 1045.0, 1050.0])
    assert calls == [True, True]
    assert device not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None
    assert reservations.get(reservation.reservation_id) is reservation


def test_radio_failure_on_retry_quarantines(monkeypatch, context):
    _, manager, reservations, reservation, start, quarantine = _failed_restore(context, monkeypatch)
    start.side_effect = StartupFailure("beacon setup failed", kind=FailureKind.TRANSIENT_RADIO)
    _run_ticks(monkeypatch, manager, reservations, reservation.device_id, [1015.0])
    quarantine.assert_called_once()
    assert quarantine.call_args.kwargs["radio_fault"] is True
    assert reservation.device_id not in manager.watchdog._pending


def test_release_stops_the_retries(monkeypatch, context):
    _, manager, reservations, reservation, start, _ = _failed_restore(context, monkeypatch)
    reservation.release_requests += 1
    _run_ticks(monkeypatch, manager, reservations, reservation.device_id, [1015.0])
    assert start.call_count == 1  # only the original restore
    assert reservation.device_id not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None


def test_api_reports_restore_failed_and_delete_stops_retries(monkeypatch, context, app):
    config, manager, _, reservation, _, _ = _failed_restore(context, monkeypatch)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v2/reservations/{reservation.reservation_id}/network"
    with TestClient(app) as client:
        network = client.get(path, headers=headers).json()
        assert (network["active"], network["runtime_state"]) == (False, "restore_failed")
        system = client.get("/api/v2/status", headers=headers).json()
        assert system["service"]["health"] == "degraded"
        assert system["antennas"][0]["runtime_state"] == "restore_failed"
        assert client.delete(path, headers=headers).status_code == 200
        assert manager.watchdog.state(reservation) is None
        assert client.delete(path, headers=headers).status_code == 409
        assert client.get(f"/api/v2/reservations/{reservation.reservation_id}", headers=headers).status_code == 200


def test_new_create_replaces_the_pending_restore(monkeypatch, context, app):
    config, manager, _, reservation, start, _ = _failed_restore(context, monkeypatch)
    start.side_effect = None
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v2/reservations/{reservation.reservation_id}/network"
    body = network_body(ssid="new", channel=1, band="2.4ghz", encryption="open", tx_power_level=4)
    with TestClient(app) as client:
        assert create_network(client, headers, path, body)[1].status_code == 200
    assert reservation.device_id not in manager.watchdog._pending
    assert manager.watchdog.state(reservation) is None


# --------------------------------------------------------------------------- WD-3

def _dhcp_setup(context, monkeypatch, ticks, dhcp_restart_works=True):
    """Run the watch loop once per (time, dnsmasq running) tick with hostapd healthy.

    Returns the events: "dhcp" for a DHCP-only restart, "ap" for a network restore.
    """
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(
        manager.active, device, active_network(interface=device, subnet="192.0.2.0/24"),
    )
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager.hostapd_manager, "probe", Mock(return_value=Probe(True)))
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
    monkeypatch.setattr(manager.watchdog, "_pause", wait)
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


def test_dnsmasq_death_is_repaired_more_than_once(monkeypatch, context):
    # Before WD-3 the second death left the network in dhcp_failed for good.
    ticks = [(0.0, False), (5.0, True), (600.0, False), (605.0, True), (1200.0, False)]
    assert _dhcp_setup(context, monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp"]


def test_fourth_dhcp_failure_in_an_hour_restarts_the_network(monkeypatch, context):
    ticks = [
        (0.0, False), (5.0, True), (10.0, False), (15.0, True), (20.0, False), (25.0, True),
        (30.0, False), (35.0, False),
    ]
    assert _dhcp_setup(context, monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp", "ap"]


def test_failed_dhcp_restart_restarts_the_network_on_the_next_tick(monkeypatch, context):
    ticks = [(0.0, False), (5.0, False)]
    assert _dhcp_setup(context, monkeypatch, ticks, dhcp_restart_works=False) == ["dhcp", "ap"]


def test_dhcp_budget_renews_after_the_window(monkeypatch, context):
    ticks = [
        (0.0, False), (5.0, True), (10.0, False), (15.0, True), (20.0, False), (25.0, True),
        (3700.0, False),
    ]
    assert _dhcp_setup(context, monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp", "dhcp"]


def test_a_half_stopped_network_is_not_repaired(monkeypatch, context):
    """After a stop that did not complete (hostapd stuck), the watchdog must not undo the stop."""
    manager = context.manager
    reservations = context.reservations
    device = reservations.create(0).device_id
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    monkeypatch.setattr(manager, "_stop_failed", {device})
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=False))
    restore = Mock()
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(manager.watchdog, "_restore_dhcp", restore)
    _run_ticks(monkeypatch, manager, reservations, device, [0.0, 5.0, 10.0, 15.0])
    restore.assert_not_called()


def _only_reservation(context):
    reservations = context.reservations
    return next(iter(reservations.snapshot().values()))


def test_ap_restarts_are_counted_for_the_whole_reservation(monkeypatch, context):
    """restarts.ap grows with every AP restore, also across a recreated network."""
    _setup(context, monkeypatch, [0.0, 10.0, 20.0], recreate_at=1)
    reservation = _only_reservation(context)
    assert (reservation.ap_restarts, reservation.dhcp_restarts) == (3, 0)
    assert reservation.last_restart_reason == "hostapd_not_running"
    assert reservation.last_restart_at is not None


def test_dhcp_restarts_and_the_network_restart_after_them_are_counted(monkeypatch, context):
    ticks = [
        (0.0, False), (5.0, True), (10.0, False), (15.0, True), (20.0, False), (25.0, True),
        (30.0, False), (35.0, False),
    ]
    assert _dhcp_setup(context, monkeypatch, ticks) == ["dhcp", "dhcp", "dhcp", "ap"]
    reservation = _only_reservation(context)
    assert (reservation.ap_restarts, reservation.dhcp_restarts) == (1, 3)
    assert reservation.last_restart_reason == "dhcp_failed"


def test_get_network_has_the_restarts_section(monkeypatch, context, app):
    config = context.config
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        rid = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300}).json()[
            "reservation_id"]
        reservation = context.reservations.get(rid)
        reservation.record_restart("ap", "hostapd_not_running")
        body = client.get(f"/api/v2/reservations/{rid}/network", headers=headers).json()
    assert body["restarts"]["ap"] == 1 and body["restarts"]["dhcp"] == 0
    assert body["restarts"]["last_reason"] == "hostapd_not_running"
    assert body["restarts"]["last_at"].endswith("Z")


def test_unexpected_error_in_a_restore_is_a_failed_restore(monkeypatch, context):
    """REV-1: an error other than StartupFailure or ValueError is reported and retried, not lost."""
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    monkeypatch.setattr(manager, "release_device", Mock())
    monkeypatch.setattr(manager, "start_network", Mock(side_effect=KeyError("boom")))
    quarantine = Mock()
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)
    manager.watchdog._restore_ap(reservations, reservation, _restorable(reservation.device_id), False)
    quarantine.assert_not_called()
    assert manager.watchdog.state(reservation) == "restore_failed"
    pending = manager.watchdog._pending[reservation.device_id]
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: pending.next_try)
    manager.watchdog._retry_pending(reservations, pending)
    assert pending.failures == 2   # the retry failed the same way and was scheduled again


# --------------------------------------------------------------------------- unit-test-14 (b)


def _watch_until_a_restart(context, monkeypatch, ticks, *, dhcp_restart_works=True, verify=None):
    """One watch-loop tick per (time, hostapd alive, hostapd enabled, dnsmasq running).

    The restores themselves are fakes; returns the reservation that counted the restarts.
    """
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(
        manager.active, device, active_network(interface=device, subnet="192.0.2.0/24"),
    )
    tick = {"now": 0.0, "alive": True, "enabled": True, "dhcp": True}
    pending = iter(ticks)

    def wait(_timeout):
        try:
            tick["now"], tick["alive"], tick["enabled"], tick["dhcp"] = next(pending)
        except StopIteration:
            return True
        return False

    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: tick["now"])
    monkeypatch.setattr(manager.watchdog, "_pause", wait)
    monkeypatch.setattr(manager.hostapd_manager, "is_running", lambda _device: tick["alive"])
    monkeypatch.setattr(manager.hostapd_manager, "probe", lambda _device: Probe(tick["enabled"]))
    monkeypatch.setattr(manager.dhcp_server, "is_running", lambda _device: tick["dhcp"])
    monkeypatch.setattr(manager, "verify_network", verify or Mock(return_value=([], False)))

    def restore_dhcp(_reservations, res, _status):
        if dhcp_restart_works:
            manager.watchdog.states.pop(device, None)
        else:
            manager.watchdog.states[device] = (res, "dhcp_failed")

    monkeypatch.setattr(manager.watchdog, "_restore_dhcp", restore_dhcp)
    monkeypatch.setattr(manager.watchdog, "_restore_ap", Mock())
    manager.watchdog._watch(reservations, device)
    monkeypatch.delitem(manager.active, device)   # GET .../network then reads only the reservation
    return reservation


_HEALTHY = (True, True, True)


@pytest.mark.parametrize(("ticks", "options", "expected"), [
    ([(0.0, False, False, True)], {}, (1, 0, "hostapd_not_running")),
    ([(0.0, True, False, True), (5.0, True, False, True), (10.0, True, False, True)], {},
     (1, 0, "hostapd_not_enabled")),
    ([(0.0, True, True, False)], {}, (0, 1, "dnsmasq_not_running")),
    ([(0.0, True, True, False), (5.0, *_HEALTHY)], {"dhcp_restart_works": False}, (1, 1, "dhcp_failed")),
    ([(5.0 * i, *_HEALTHY) for i in range(watchdog_module.VERIFY_EVERY + 1)],
     {"verify": Mock(return_value=(["gateway address"], True))}, (1, 0, "network_check_failed")),
], ids=["hostapd_not_running", "hostapd_not_enabled", "dnsmasq_not_running", "dhcp_failed",
        "network_check_failed"])
def test_every_restart_reason_reaches_get_network(monkeypatch, ticks, options, expected, context, app):
    """unit-test-14 (b): each value of restarts.last_reason, from the watch loop to GET .../network."""
    reservation = _watch_until_a_restart(context, monkeypatch, ticks, **options)
    config = context.config
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        restarts = client.get(
            f"/api/v2/reservations/{reservation.reservation_id}/network", headers=headers,
        ).json()["restarts"]
    assert (restarts["ap"], restarts["dhcp"], restarts["last_reason"]) == expected
    assert restarts["last_at"].endswith("Z")


@pytest.fixture
def scripted_creates(monkeypatch, context, app):
    """The API with a scripted start_network: `go` lets a start finish, `fail` makes it start_failed."""
    from wilab.api.routes import network as network_routes

    monkeypatch.setattr(network_routes, "CREATE_RETRY_DELAYS", (0, 0))
    config = context.config
    manager = context.manager
    monkeypatch.setattr(context.channels, "validate_network", Mock())
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    script = {"go": threading.Event(), "fail": False}
    script["go"].set()

    def start_network(device, req, *args, cancelled=None, **kwargs):
        while not script["go"].wait(0.01):
            if cancelled is not None and cancelled():
                raise StartupFailure("AP start cancelled", stage="hostapd")
        if script["fail"]:
            raise StartupFailure("dnsmasq refused the configuration", stage="dhcp")
        manager.active[device] = active_network(interface=device)
        return manager.active[device]

    monkeypatch.setattr(manager, "start_network", start_network)
    monkeypatch.setattr(
        manager, "get_status",
        lambda device: manager.active[device].status() if device in manager.active
        else NetworkStatus(interface=device, active=False),
    )
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        yield client, headers, manager, script
        script["go"].set()
        with manager.start_jobs_lock:
            threads = [job.thread for job in manager.start_jobs.values() if job.thread is not None]
        for thread in threads:
            thread.join(timeout=5)
        manager.active.clear()


def _until(predicate, timeout: float = 5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if value := predicate():
            return value
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_restart_counters_live_as_long_as_the_reservation(scripted_creates, context):
    """unit-test-14 (b): restarts in the 202 body and every runtime_state; kept across creates, zero when new."""
    client, headers, manager, script = scripted_creates
    reservations = context.reservations
    rid = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300}).json()[
        "reservation_id"]
    url = f"/api/v2/reservations/{rid}/network"
    reservation = reservations.get(rid)
    reservation.record_restart("ap", "hostapd_not_running")
    reservation.record_restart("dhcp", "dnsmasq_not_running")
    counted = client.get(url, headers=headers).json()["restarts"]
    assert (counted["ap"], counted["dhcp"], counted["last_reason"]) == (1, 1, "dnsmasq_not_running")
    body = network_body(ssid="counters", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)

    def state():
        return client.get(url, headers=headers).json()

    script["go"].clear()
    created = client.post(url, headers=headers, json=body)
    assert created.status_code == 202 and created.json()["restarts"] == counted
    assert state()["runtime_state"] == "starting" and state()["restarts"] == counted
    script["go"].set()
    assert _until(lambda: state()["active"])
    assert state()["restarts"] == counted
    assert client.delete(url, headers=headers).status_code == 200
    assert state()["restarts"] == counted
    assert create_network(client, headers, url, body)[1].json()["restarts"] == counted   # a new create
    assert client.delete(url, headers=headers).status_code == 200
    script["fail"] = True
    failed = create_network(client, headers, url, body)[1].json()
    assert failed["runtime_state"] == "start_failed" and failed["restarts"] == counted
    assert client.delete(url, headers=headers).status_code == 200
    for repair in ("restoring_ap", "restoring_dhcp"):
        manager.watchdog.states[reservation.device_id] = (reservation, repair)
        repaired = state()
        assert repaired["runtime_state"] == repair and repaired["restarts"] == counted
    manager.watchdog.states.pop(reservation.device_id)
    assert client.delete(f"/api/v2/reservations/{rid}", headers=headers).status_code == 200
    fresh = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300}).json()
    zero = client.get(f"/api/v2/reservations/{fresh['reservation_id']}/network", headers=headers).json()
    assert zero["restarts"] == {"ap": 0, "dhcp": 0, "last_at": None, "last_reason": None}


# --------------------------------------------------------------------------- WD-10


@pytest.mark.parametrize(("answers", "restarted"), [
    ([None] * 5, False),            # five slow probes: a loaded host, not a dead AP
    ([None] * 6, True),             # six in a row: restart
    ([None, None, False, None, None], True),   # 1 + 1 + 2 + 1 + 1 half misses
    ([None] * 4 + [True] + [None] * 4, False),  # a real ENABLED answer resets the count
    ([False] * 3, True),            # hostapd's own "not ENABLED" keeps the old limit
])
def test_slow_probes_count_half(monkeypatch, answers, restarted, context):
    ticks = [(5.0 * i, True, answer, True) for i, answer in enumerate(answers)]
    _watch_until_a_restart(context, monkeypatch, ticks)
    manager = context.manager
    assert manager.watchdog._restore_ap.called is restarted


# --------------------------------------------------------------------------- PERF-4 wake-up


def test_wake_runs_the_next_tick_early_and_stop_ends_the_wait(context):
    """The hostapd control monitor wakes the antenna's watchdog: no waiting for the 5 s tick."""
    watchdog = context.manager.watchdog
    timer = threading.Timer(0.1, watchdog.wake, args=("wlan0",))
    timer.start()
    began = time.monotonic()
    assert watchdog._pause("wlan0") is False
    assert time.monotonic() - began < watchdog_module.TICK - 1   # woken, after WAKE_GAP at least
    assert time.monotonic() - began >= watchdog_module.WAKE_GAP - 0.05
    timer = threading.Timer(0.1, watchdog.stopping.set)
    timer.start()
    began = time.monotonic()
    assert watchdog._pause("wlan0") is True
    assert time.monotonic() - began < 1


# --------------------------------------------------------------------------- unit-test-14 / REV-10


def _gone_reason(reservations, reservation) -> str:
    return reservations.ended_reason(reservation.reservation_id)


@pytest.fixture
def faulty(monkeypatch, context):
    """A reservation with a running network; quarantine is real, the USB recovery is recorded."""
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    schedule = Mock()
    monkeypatch.setattr(manager.recovery, "schedule", schedule)
    monkeypatch.setitem(manager.active, device, active_network(interface=device, subnet="192.0.2.0/24"))
    return manager, reservations, reservation, device, schedule


def test_dhcp_stop_failing_in_the_repair_quarantines_without_usb_reset(monkeypatch, faulty):
    """unit-test-14 (1): dnsmasq cannot even be stopped -> tear down, unavailable, no USB reset."""
    from wilab.network.dhcp import DhcpServerError

    manager, reservations, reservation, device, schedule = faulty
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock(side_effect=DhcpServerError("stuck")))
    release = Mock()
    monkeypatch.setattr(manager, "release_device", release)
    manager.watchdog._restore_dhcp(reservations, reservation, manager.active[device])
    release.assert_called_once_with(device)
    schedule.assert_not_called()   # radio_fault=False: no USB reset
    assert reservations.get(reservation.reservation_id) is None
    assert _gone_reason(reservations, reservation) == "reservation_invalidated"
    assert reservations.recovery_snapshot() == {device: False}   # unavailable, not recovering


def test_cleanup_failing_on_the_owed_retry_quarantines_without_usb_reset(monkeypatch, faulty):
    """unit-test-14 (2): the second failed cleanup in a row quarantines, radio_fault=False."""
    manager, reservations, reservation, device, schedule = faulty
    pending = watchdog_module._Pending(reservation, _restorable(device).restart_request(), "2.4ghz", 1)
    manager.watchdog._pending[device] = pending
    monkeypatch.setattr(manager, "release_device", Mock(side_effect=RuntimeError("iptables busy")))
    start = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    manager.watchdog._retry_pending(reservations, pending)
    start.assert_not_called()
    schedule.assert_not_called()
    assert device not in manager.watchdog._pending
    assert _gone_reason(reservations, reservation) == "reservation_invalidated"
    assert reservations.recovery_snapshot() == {device: False}


def test_release_right_after_a_successful_retry_cleans_up(monkeypatch, faulty):
    """unit-test-14 (3): the owed restore succeeds, the client released meanwhile -> released again."""
    manager, reservations, reservation, device, schedule = faulty
    pending = watchdog_module._Pending(reservation, _restorable(device).restart_request(), "2.4ghz", 1)
    manager.watchdog._pending[device] = pending
    release = Mock()
    monkeypatch.setattr(manager, "release_device", release)

    def start(*_args, **_kwargs):
        reservation.release_requests += 1   # the client's DELETE arrived during the start

    monkeypatch.setattr(manager, "start_network", start)
    manager.watchdog._retry_pending(reservations, pending)
    assert release.call_count == 2   # leftovers before the start, the restored AP after it
    schedule.assert_not_called()
    assert reservations.recovery_snapshot() == {}


def test_unsafe_cleanup_of_a_restore_is_retried_not_a_usb_reset(monkeypatch, faulty):
    """REV-10: a cleanup that fails once (iptables lock) no longer quarantines with a USB reset.

    The restore is owed (restore_failed), its retry cleans up again and brings the
    network back; the reservation is kept throughout.
    """
    manager, reservations, reservation, device, schedule = faulty
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: 1000.0)
    release = Mock(side_effect=[RuntimeError("xtables lock held"), None])
    monkeypatch.setattr(manager, "release_device", release)
    start = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    manager.watchdog._restore_ap(reservations, reservation, _restorable(device), False)
    schedule.assert_not_called()
    assert reservations.get(reservation.reservation_id) is reservation
    assert manager.watchdog.state(reservation) == "restore_failed"
    start.assert_not_called()
    manager.watchdog._retry_pending(reservations, manager.watchdog._pending[device])
    start.assert_called_once()
    assert device not in manager.watchdog._pending
    assert reservations.recovery_snapshot() == {}


def test_unsafe_cleanup_with_the_adapter_gone_is_a_radio_fault(monkeypatch, faulty):
    manager, reservations, reservation, device, schedule = faulty
    monkeypatch.setattr(watchdog_module, "interface_present", lambda _interface: False)
    monkeypatch.setattr(manager, "release_device", Mock(side_effect=RuntimeError("no such device")))
    manager.devices.get(device).usb_port = "2-1"
    manager.watchdog._restore_ap(reservations, reservation, _restorable(device), False)
    schedule.assert_called_once()   # USB recovery
    assert _gone_reason(reservations, reservation) == "reservation_invalidated"


def test_failed_rollback_of_a_restore_is_retried(monkeypatch, faulty):
    """REV-10: a restore whose rollback failed (CLEANUP_FAILED) is owed, not quarantined at once."""
    manager, reservations, reservation, device, schedule = faulty
    monkeypatch.setattr(manager, "release_device", Mock())
    monkeypatch.setattr(
        manager, "start_network",
        Mock(side_effect=StartupFailure("rollback failed", kind=FailureKind.CLEANUP_FAILED)),
    )
    manager.watchdog._restore_ap(reservations, reservation, _restorable(device), False)
    schedule.assert_not_called()
    assert reservations.get(reservation.reservation_id) is reservation
    assert manager.watchdog.state(reservation) == "restore_failed"


# --------------------------------------------------------------------------- budgets per driver (config.yaml)


def test_a_driver_has_its_own_ap_restore_budget(monkeypatch, context):
    """watchdog.drivers.<driver>.ap_restores in config.yaml: mt7921u gets 5 restores an hour."""
    from wilab.config import DriverWatchdog, RepairBudget, RepairBudgetOverride, WatchdogConfig

    monkeypatch.setattr(context.manager.config, "watchdog", WatchdogConfig(
        ap_restores=RepairBudget(limit=3, window_minutes=60), dhcp_restarts=RepairBudget(limit=3, window_minutes=60),
        drivers={"mt7921u": DriverWatchdog(ap_restores=RepairBudgetOverride(limit=5))},
    ))
    for device in context.manager.devices.all():
        monkeypatch.setattr(device, "driver", "mt7921u")
    times = [0.0, 600.0, 1200.0, 1800.0, 2400.0, 3000.0]
    assert _setup(context, monkeypatch, times) == [False] * 5 + [True]


def test_another_driver_keeps_the_default_budget(monkeypatch, context):
    from wilab.config import DriverWatchdog, RepairBudget, RepairBudgetOverride, WatchdogConfig

    monkeypatch.setattr(context.manager.config, "watchdog", WatchdogConfig(
        ap_restores=RepairBudget(limit=3, window_minutes=60), dhcp_restarts=RepairBudget(limit=3, window_minutes=60),
        drivers={"mt7921u": DriverWatchdog(ap_restores=RepairBudgetOverride(limit=5))},
    ))
    for device in context.manager.devices.all():
        monkeypatch.setattr(device, "driver", "rtw88_8822bu")
    assert _setup(context, monkeypatch, [0.0, 600.0, 1200.0, 1800.0]) == [False, False, False, True]


def test_a_shorter_window_forgets_restores_sooner(monkeypatch, context):
    from wilab.config import RepairBudget, WatchdogConfig

    monkeypatch.setattr(context.manager.config, "watchdog", WatchdogConfig(
        ap_restores=RepairBudget(limit=3, window_minutes=10),
        dhcp_restarts=RepairBudget(limit=3, window_minutes=60),
    ))
    # Every restore is 6 minutes apart: never more than 2 inside a 10-minute window.
    assert _setup(context, monkeypatch, [0.0, 360.0, 720.0, 1080.0, 1440.0]) == [False] * 5
