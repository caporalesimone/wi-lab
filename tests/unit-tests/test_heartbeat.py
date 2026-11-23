"""STAB-1: systemd watchdog pings stop only when a loop stalled and Wi-Lab is idle."""

import socket
import threading
from pathlib import Path

import pytest

from wilab import heartbeat
from wilab.reservation import ReservationManager


@pytest.fixture(autouse=True)
def _clean_beats(monkeypatch):
    monkeypatch.setattr(heartbeat, "_beats", {})


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(heartbeat.time, "monotonic", lambda: now["t"])
    return now


def test_fresh_loops_are_not_stale(clock):
    heartbeat.beat("expiry")
    clock["t"] += heartbeat.STALE_AFTER - 1
    assert heartbeat.stale_loops() == []


def test_loop_without_beats_becomes_stale(clock):
    heartbeat.beat("expiry")
    heartbeat.beat("watchdog:wlan0")
    clock["t"] += heartbeat.STALE_AFTER + 1
    heartbeat.beat("expiry")
    assert heartbeat.stale_loops() == ["watchdog:wlan0"]


@pytest.mark.parametrize(("stale", "idle", "ping"), [
    (False, False, True),
    (False, True, True),
    (True, False, True),   # stalled but a reservation exists: keep running
    (True, True, False),   # stalled and idle: let systemd restart
])
def test_ping_decision(clock, stale, idle, ping):
    heartbeat.beat("expiry")
    if stale:
        clock["t"] += heartbeat.STALE_AFTER + 1
    assert heartbeat.should_ping(lambda: idle)[0] is ping


def test_broken_idle_check_keeps_the_service_running(clock):
    heartbeat.beat("expiry")
    clock["t"] += heartbeat.STALE_AFTER + 1

    def broken() -> bool:
        raise RuntimeError("boom")

    assert heartbeat.should_ping(broken)[0] is True


def test_sd_notify_sends_to_the_systemd_socket(monkeypatch, tmp_path: Path):
    path = tmp_path / "notify"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(path))
    try:
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        assert heartbeat.sd_notify("WATCHDOG=1")
        assert server.recv(64) == b"WATCHDOG=1"
    finally:
        server.close()


def test_sd_notify_without_systemd_does_nothing(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert heartbeat.sd_notify("READY=1") is False


def test_watchdog_enabled_only_for_this_process(monkeypatch):
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert not heartbeat.watchdog_enabled()
    monkeypatch.setenv("WATCHDOG_USEC", "90000000")
    monkeypatch.setenv("WATCHDOG_PID", "1")
    assert not heartbeat.watchdog_enabled()
    monkeypatch.delenv("WATCHDOG_PID")
    assert heartbeat.watchdog_enabled()


def test_notify_loop_stops_pinging_only_while_idle(monkeypatch, clock):
    sent: list[str] = []
    monkeypatch.setattr(heartbeat, "sd_notify", lambda state: sent.append(state) or True)
    heartbeat.beat("expiry")
    clock["t"] += heartbeat.STALE_AFTER + 1
    idle = iter([False, True, False])
    stop = threading.Event()
    waits = iter([False, False, True])
    monkeypatch.setattr(stop, "wait", lambda _t: next(waits))
    heartbeat.notify_loop(stop, lambda: next(idle))
    # busy -> ping, idle -> no ping (systemd restarts), busy again -> ping
    assert sent == ["WATCHDOG=1", "WATCHDOG=1"]


def test_reservation_manager_idle_state():
    mgr = ReservationManager(["wlan0", "wlan1"])
    assert mgr.is_idle()
    reservation = mgr.create(60)
    assert not mgr.is_idle()
    mgr.delete(reservation.reservation_id)
    assert mgr.is_idle()


def test_quarantine_with_usb_recovery_is_not_idle():
    mgr = ReservationManager(["wlan0"])
    reservation = mgr.create(60)
    mgr.quarantine(reservation, recovering=True)
    assert not mgr.is_idle()
    mgr.finish_recovery("wlan0", recovered=False)
    assert mgr.is_idle()  # unavailable, but nothing is running
