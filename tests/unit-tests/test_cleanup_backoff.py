"""WD-6: a cleanup that keeps failing is retried with backoff in the background."""

import logging
from unittest.mock import Mock

import pytest

from wilab.config import load_config
from wilab.models import NetworkStatus
from wilab.reservation import ReservationManager
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
    status = NetworkStatus(interface=device, active=True)
    status._expires_at_timestamp = 1.0  # long expired
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
