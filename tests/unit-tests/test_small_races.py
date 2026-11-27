"""REV-12: small races and edge cases in wifi and network."""

import threading
from unittest.mock import Mock

import pytest
from conftest import active_network

from wilab import heartbeat, runtime_cleanup
from wilab.wifi import watchdog as watchdog_module
from wilab.wifi.channels import ChannelManager
from wilab.wifi.hostapd import DFS_READY_TIMEOUT, Probe


@pytest.fixture(autouse=True)
def _no_heartbeat(monkeypatch):
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)


# -- channel cache ---------------------------------------------------------------


def test_a_reading_older_than_invalidate_is_not_cached(monkeypatch):
    channels = ChannelManager()
    started, release = threading.Event(), threading.Event()
    readings = iter(["old", "new"])

    def resolve(_interface):
        value = next(readings)
        if value == "old":
            started.set()
            release.wait(5)
        return value

    monkeypatch.setattr(channels, "_resolve_channels", resolve)
    result: list[object] = []
    reader = threading.Thread(target=lambda: result.append(channels.get_channels("wlan0")))
    reader.start()
    assert started.wait(5)
    channels.invalidate("wlan0")      # e.g. BUG-4: the regulatory domain changed meanwhile
    release.set()
    reader.join(5)
    assert result == ["old"]          # the caller still gets an answer
    assert channels.get_channels("wlan0") == "new"   # but the stale one was not kept


def test_a_reading_without_invalidate_is_cached(monkeypatch):
    channels = ChannelManager()
    resolve = Mock(return_value="value")
    monkeypatch.setattr(channels, "_resolve_channels", resolve)
    assert channels.get_channels("wlan0") == channels.get_channels("wlan0") == "value"
    assert resolve.call_count == 1


# -- radar events in the watchdog ------------------------------------------------


def _watch(context, monkeypatch, probes, times, channel=52):
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    status = active_network(interface=device, band="5ghz", channel=channel)
    monkeypatch.setitem(manager.active, device, status)
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
    clock = {"now": 0.0}
    answers = iter(zip(times, probes))

    def probe(_device):
        clock["now"], answer = next(answers)
        return answer

    monkeypatch.setattr(manager.hostapd_manager, "probe", probe)
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager, "verify_network", Mock(return_value=([], False)))
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: clock["now"])
    restore = Mock()
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(manager.watchdog, "_pause", Mock(side_effect=[False] * len(probes) + [True]))
    manager.watchdog._watch(reservations, device)
    return status, restore


def test_a_radar_check_is_not_a_fault(monkeypatch, context):
    # Before REV-12 three "DFS" answers restored the AP, and three radars in an hour quarantined it.
    dfs = Probe(False, "DFS", 52)
    probes = [dfs] * 8 + [Probe(True, "ENABLED", 52)]
    times = [float(5 * n) for n in range(len(probes))]
    _status, restore = _watch(context, monkeypatch, probes, times)
    restore.assert_not_called()


def test_a_radar_check_that_never_ends_restores_the_ap(monkeypatch, context):
    dfs = Probe(False, "DFS", 52)
    times = [0.0, DFS_READY_TIMEOUT + 1, DFS_READY_TIMEOUT + 6, DFS_READY_TIMEOUT + 11]
    _status, restore = _watch(context, monkeypatch, [dfs] * 4, times)
    restore.assert_called_once()


def test_the_channel_a_radar_moved_to_is_shown(monkeypatch, context):
    probes = [Probe(True, "ENABLED", 52), Probe(True, "ENABLED", 100)]
    status, restore = _watch(context, monkeypatch, probes, [0.0, 5.0])
    restore.assert_not_called()
    assert status.channel == 52               # the request, used by a restore
    assert status.status().channel == 100     # what GET /access-point/{reservation_id} shows


def test_the_moved_channel_is_cleared_when_back_on_the_requested_one(monkeypatch, context):
    probes = [Probe(True, "ENABLED", 100), Probe(True, "ENABLED", 52)]
    status, _restore = _watch(context, monkeypatch, probes, [0.0, 5.0])
    assert status.radio_channel is None
    assert status.status().channel == 52


# -- startup cleanup -------------------------------------------------------------


def test_runtime_cleanup_never_raises(monkeypatch):
    def unreadable(*_args, **_kwargs):
        raise PermissionError("/proc unreadable")

    removed = Mock()
    monkeypatch.setattr(runtime_cleanup, "_orphans", unreadable)
    monkeypatch.setattr(runtime_cleanup, "_remove_files", removed)
    monkeypatch.setattr(runtime_cleanup, "_stale_ifbs", Mock(return_value=[]))
    runtime_cleanup.cleanup_runtime()
    removed.assert_called_once()              # the other steps still run


# -- expiry seen by a read -------------------------------------------------------


@pytest.mark.parametrize("read", ["get_status", "active_status"])
def test_a_read_of_an_expired_network_never_raises(monkeypatch, context, read):
    manager = context.manager
    device = manager.config.antennas[0].device_id
    monkeypatch.setitem(manager.active, device, active_network(interface=device, deadline=0.0))
    monkeypatch.setattr(manager, "stop_network", Mock(side_effect=RuntimeError("iptables locked")))
    answer = getattr(manager, read)(device)
    assert answer is None or answer.active is False
    assert manager._cleanup_failures[device] == 1      # the background loop takes over (WD-6)
