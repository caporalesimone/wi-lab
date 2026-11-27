"""WD-5 point 3: a device whose interface is gone is retired when nothing holds it."""

import threading
from unittest.mock import Mock

import pytest
from conftest import active_network

from wilab import heartbeat
from wilab.api import discovery as discovery_module
from wilab.devices import Device


@pytest.fixture
def gone(monkeypatch):
    """Interfaces in this set are missing from /sys/class/net."""
    missing: set[str] = set()
    monkeypatch.setattr(discovery_module, "interface_present", lambda name: name not in missing)
    monkeypatch.setattr(discovery_module, "scan_new_networks", Mock(return_value=[]))
    return missing


def _scans(context, n):
    for _ in range(n):
        context.discovery.scan(quiet=True)


def _device(context):
    device = Device(interface="wlx-old", display_name="Old adapter")
    context.devices.add(device)
    return device


def test_a_gone_unused_device_is_retired_after_four_scans(context, gone):
    device = _device(context)
    gone.add(device.interface)
    _scans(context, discovery_module.RETIRE_AFTER_SCANS - 1)
    assert device.interface in context.devices
    _scans(context, 1)
    assert device.interface not in context.devices


def test_a_device_that_comes_back_in_time_is_kept(context, gone):
    device = _device(context)
    gone.add(device.interface)
    _scans(context, discovery_module.RETIRE_AFTER_SCANS - 1)
    gone.clear()
    _scans(context, 1)
    gone.add(device.interface)
    _scans(context, discovery_module.RETIRE_AFTER_SCANS - 1)
    assert device.interface in context.devices      # the count starts again


def test_an_unavailable_device_is_retired_and_degraded_ends(context, gone):
    # Before WD-5 p. 3 the old entry stayed "unavailable" and /status "degraded" until a restart.
    device = _device(context)
    context.reservations._blocked[device.interface] = False      # quarantined, no recovery running
    context.manager.quarantines[device.interface] = (1, 0.0, True)
    context.manager.subnets._assigned[device.interface] = object()
    gone.add(device.interface)
    _scans(context, discovery_module.RETIRE_AFTER_SCANS)
    assert device.interface not in context.devices
    assert device.interface not in context.reservations.recovery_snapshot()
    assert device.interface not in context.manager.quarantines
    assert context.manager.subnets.assigned(device.interface) is None


@pytest.mark.parametrize("holder", ["reserved", "recovering", "network", "cleanup_failed", "owed"])
def test_a_device_still_held_is_kept(context, gone, monkeypatch, holder):
    device = _device(context)
    name = device.interface
    if holder == "reserved":
        context.reservations.create(60, name)
    elif holder == "recovering":
        context.reservations._blocked[name] = True
    elif holder == "network":
        monkeypatch.setitem(context.manager.active, name, active_network(interface=name))
    elif holder == "cleanup_failed":
        monkeypatch.setitem(context.manager._cleanup_failures, name, 1)
    else:
        monkeypatch.setitem(context.manager.watchdog._pending, name, Mock())
    gone.add(name)
    _scans(context, discovery_module.RETIRE_AFTER_SCANS + 2)
    assert name in context.devices


def test_the_watcher_of_a_retired_device_ends(context, gone, monkeypatch):
    device = _device(context)
    watchdog = context.manager.watchdog
    forgotten = []
    monkeypatch.setattr(heartbeat, "forget", forgotten.append)
    ticks = []
    monkeypatch.setattr(watchdog, "tick", lambda *_: ticks.append(1))

    def pause_then_retire(_device):
        if len(ticks) == 1:
            context.devices.retire(device.interface)
        return False

    monkeypatch.setattr(watchdog, "_pause", pause_then_retire)
    # In a thread of its own, like in the service: _watch binds the log context of its thread.
    watcher = threading.Thread(target=watchdog._watch, args=(context.reservations, device.interface))
    watcher.start()
    watcher.join(5)
    assert not watcher.is_alive()       # it returned instead of looping forever
    assert ticks == [1]
    assert forgotten == [f"watchdog:{device.interface}"]
