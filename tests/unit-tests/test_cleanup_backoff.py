"""WD-6: a cleanup that keeps failing is retried with backoff in the background."""

import itertools
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import active_network
from fastapi.testclient import TestClient

from wilab.config import load_config
from wilab.network.commands import CommandError
from wilab.reservation import NoDeviceAvailableError, ReservationManager
from wilab.wifi import manager as manager_module
from wilab.wifi.manager import NetworkManager


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now["t"])
    return now


@pytest.fixture
def stuck_network(monkeypatch, clock):
    mgr = NetworkManager(load_config())
    device = mgr.config.antennas[0].device_id
    status = active_network(interface=device, deadline=time.monotonic() - 3600)  # long expired
    mgr.active[device] = status
    stop = Mock(side_effect=RuntimeError("Cannot find device"))
    monkeypatch.setattr(mgr, "stop_network", stop)
    return mgr, device, status, stop


def test_expiry_loop_backs_off_a_failing_cleanup(stuck_network, clock):
    mgr, device, status, stop = stuck_network
    for second in range(0, 31, 5):  # the expiry loop ticks every 5 s
        clock["t"] = 1000.0 + second
        mgr._expire_network(device, status, now=2.0)
    # Before WD-6: 7 attempts in 30 s. Now t=0 (wait 5), t=5 (wait 15), t=20 (wait 60).
    assert stop.call_count == 3


def test_explicit_release_is_never_delayed(stuck_network, clock):
    mgr, device, status, stop = stuck_network
    mgr._expire_network(device, status, now=2.0)
    assert not mgr.cleanup_due(device)
    with pytest.raises(RuntimeError):
        mgr.release_device(device)  # a client DELETE tries for real
    assert stop.call_count == 2


def test_success_resets_the_backoff(stuck_network, clock):
    mgr, device, status, stop = stuck_network
    mgr._expire_network(device, status, now=2.0)
    stop.side_effect = lambda d: mgr.active.pop(d)
    mgr.release_device(device)
    assert mgr.cleanup_due(device)
    assert device not in mgr._cleanup_failures


def test_backoff_steps_and_cap(stuck_network, clock):
    mgr, device, _status, _stop = stuck_network
    delays = []
    for _ in range(6):
        with pytest.raises(RuntimeError):
            mgr.release_device(device)
        delays.append(mgr._cleanup_retry_at[device] - clock["t"])
    assert delays == [5.0, 15.0, 60.0, 300.0, 300.0, 300.0]


def test_reservation_sweep_skips_a_device_backing_off_but_delete_does_not(caplog):
    due = {"dev0": False}
    cleanup = Mock(side_effect=RuntimeError("stop failed"))
    store = ReservationManager(["dev0"], cleanup=cleanup, cleanup_due=lambda d: due[d])
    reservation = store.create(60)
    reservation.expires_at = 1.0
    store.expire()  # backing off: not attempted
    assert cleanup.call_count == 0
    due["dev0"] = True
    store.expire()
    assert cleanup.call_count == 1
    caplog.set_level(logging.WARNING)
    caplog.clear()
    store.expire()
    assert cleanup.call_count == 2
    # One traceback per failure series, then short warnings.
    assert [r.levelno for r in caplog.records if "clean up device" in r.getMessage()] == [logging.WARNING]
    due["dev0"] = False
    # An explicit release ignores the backoff; the expired ID is gone (nothing to release).
    assert store.delete(reservation.reservation_id) is False
    assert cleanup.call_count == 3


def test_requests_never_repeat_a_cleanup_that_is_backing_off():
    """Only the background sweep and an explicit release retry a failed cleanup."""
    cleanup = Mock(side_effect=RuntimeError("stop failed"))
    store = ReservationManager(
        ["dev0"], cleanup=cleanup, cleanup_due=lambda _d: False, cleanup_wait=lambda _d: 42.0,
    )
    reservation = store.create(60)
    reservation.expires_at = 1.0
    assert store.get(reservation.reservation_id) is None  # a call with the expired ID
    for kwargs in ({}, {"device_id": "dev0"}):  # a reserve, with and without the antenna
        with pytest.raises(NoDeviceAvailableError) as busy:
            store.create(60, **kwargs)
        # Free at the next background attempt, never a time in the past.
        assert 40 < busy.value.next_available_at - time.time() <= 42
    assert cleanup.call_count == 0


# --------------------------------------------------------------------------- unit-test-17


@pytest.fixture
def stuck_release(monkeypatch, context, app):
    """The API with a network whose hostapd does not stop, and a fake clock in the manager.

    Returns `(client, headers, manager, device, clock, attempts, run_expiry_loop)`.
    `run_expiry_loop(until)` runs `_expiry_loop` in this thread, one tick every 5 s of the fake clock.
    """
    clock = {"now": 1000.0, "stuck": True}
    monkeypatch.setattr(manager_module, "time", SimpleNamespace(
        monotonic=lambda: clock["now"], time=time.time, sleep=time.sleep,
    ))
    config = context.config
    manager = context.manager
    device = config.antennas[0].device_id
    attempts: list[float] = []

    def hostapd_stop(_net_id):
        attempts.append(clock["now"])
        if clock["stuck"]:
            raise CommandError("hostapd stuck in the kernel")

    monkeypatch.setattr(manager.hostapd_manager, "stop", hostapd_stop)
    test_thread = threading.current_thread()
    real_wait = manager.watchdog.stopping.wait
    ticks: list[float] = []

    def wait(timeout=None):
        if threading.current_thread() is not test_thread:
            return real_wait(timeout)   # the service's own loops keep their real pace
        if not ticks:
            return True
        clock["now"] = ticks.pop(0)
        return False

    monkeypatch.setattr(manager.watchdog.stopping, "wait", wait)

    def run_expiry_loop(until: float) -> None:
        ticks.extend(t for t in range(int(clock["now"]) + 5, int(until) + 1, 5))
        manager._expiry_loop()
        assert clock["now"] == until

    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        yield client, headers, manager, device, clock, attempts, run_expiry_loop
        manager.active.clear()


def _cleanup_reason(client, headers):
    reasons = client.get("/api/v2/status", headers=headers).json()["degraded_reasons"]
    return next((r for r in reasons if r["code"] == "cleanup_failed"), None)


def _reserve(client, headers):
    return client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300})


def test_cleanup_backoff_through_the_release_and_the_expiry_loop(stuck_release, monkeypatch):
    """unit-test-17: release with a stuck stop, then the expiry loop retries at +5, +15, +60, +300 s."""
    client, headers, manager, device, clock, attempts, run_expiry_loop = stuck_release
    rid = _reserve(client, headers).json()["reservation_id"]
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    assert client.delete(f"/api/v2/reservations/{rid}", headers=headers).status_code == 200
    assert attempts == [1000.0]
    for count, (wait, retry_at) in enumerate([(5, 1005), (15, 1020), (60, 1080), (300, 1380)], start=1):
        reason = _cleanup_reason(client, headers)
        assert reason is not None, count
        assert reason["message"] == (
            f"Cleanup failed {count} time(s) in a row; the antenna stays held, next attempt in {wait} s"
        )
        busy = _reserve(client, headers)
        assert (busy.status_code, busy.json()["detail"]["code"]) == (409, 1005)
        # Computed from a wall clock that moved on a little: truncated, never more than the wait.
        assert wait - 1 <= busy.json()["detail"]["next_available_in"] <= wait
        if retry_at == 1380:
            clock["stuck"] = False   # the last retry succeeds
        run_expiry_loop(retry_at - 5)
        assert attempts[-1] < retry_at - wait + 1   # nothing before the backoff ends
        run_expiry_loop(retry_at)
        assert attempts[-1] == retry_at
    assert [b - a for a, b in itertools.pairwise(attempts)] == [5.0, 15.0, 60.0, 300.0]
    assert _cleanup_reason(client, headers) is None
    assert manager.cleanup_failures() == {} and device not in manager.active
    free = _reserve(client, headers)
    assert free.status_code == 200 and free.json()["interface"] == device


def test_reserve_next_available_in_equals_the_cleanup_wait(stuck_release, monkeypatch):
    """unit-test-17: the 409 of the reserve gives the same wait as /status, not one second less."""
    client, headers, manager, device, _clock, _attempts, _run_expiry_loop = stuck_release
    rid = _reserve(client, headers).json()["reservation_id"]
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    assert client.delete(f"/api/v2/reservations/{rid}", headers=headers).status_code == 200
    assert _cleanup_reason(client, headers)["message"].endswith("next attempt in 5 s")
    assert _reserve(client, headers).json()["detail"]["next_available_in"] == 5
