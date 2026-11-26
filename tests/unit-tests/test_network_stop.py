"""Partial failures of a network stop, one phase at a time (unit-test-6, REV-7).

A stop that fails in one phase names it, keeps the network in `active` with
`stop_failed`, and a repeated stop finishes the work. While hostapd has not
stopped, the host guard and the isolation rules stay: its clients would
otherwise reach the host and the other networks.
"""

from unittest.mock import Mock

import pytest

from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.network.captive import CaptivePortalError
from wilab.network.commands import CommandError
from wilab.wifi.manager import NetworkManager, NetworkStopError


@pytest.fixture
def running(monkeypatch):
    """A network started with hostapd and DHCP as fakes; the firewall uses the mocked commands."""
    mgr = NetworkManager(load_config())
    mgr.qos_manager = Mock()
    mgr.qos_profile_manager = Mock()
    instances = mgr.hostapd_manager._instances
    monkeypatch.setattr(mgr.hostapd_manager, "start", lambda *, net_id, **kw: instances.__setitem__(net_id, Mock()))
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock(side_effect=lambda net_id: instances.pop(net_id, None)))
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    device = mgr.config.antennas[0].device_id
    mgr.start_network(device, NetworkCreateRequest(
        ssid="stop", channel=6, encryption="open", band="2.4ghz", tx_power_level=4,
        internet_enabled=False, captive_portal=True,
    ))
    assert mgr.host_guard.has(device) and mgr.isolation_manager.get_active_subnets()
    return mgr, device


def _break(monkeypatch, mgr, phase):
    """Make one phase of the stop fail once; returns the label NetworkStopError uses."""
    error = CommandError(f"{phase} failed", returncode=1)
    targets = {
        "QoS": (mgr.qos_manager, "clear_qos", error, "QoS"),
        "NAT": (mgr.nat_manager, "release_network", RuntimeError("NAT failed"), "NAT"),
        "captive portal": (None, None, CaptivePortalError("portal failed"), "captive portal"),
        "host guard": (mgr.host_guard, "remove", error, "host guard"),
        "isolation": (mgr.isolation_manager, "remove_network", error, "isolation"),
        "DHCP": (mgr.dhcp_server, "stop", error, "DHCP"),
    }
    owner, name, exc, label = targets[phase]
    if owner is None:
        device = next(iter(mgr.captive_portals))
        owner, name = mgr.captive_portals[device], "stop"
    real = getattr(owner, name)
    calls = {"n": 0}

    def once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, once)
    return label


@pytest.mark.parametrize("phase", ["QoS", "NAT", "captive portal", "host guard", "isolation", "DHCP"])
def test_a_failed_phase_is_named_and_a_repeated_stop_finishes(running, monkeypatch, phase):
    mgr, device = running
    label = _break(monkeypatch, mgr, phase)
    with pytest.raises(NetworkStopError, match=f"{label}: "):
        mgr.stop_network(device)
    assert device in mgr.active and mgr.stop_failed(device)
    mgr.stop_network(device)
    assert device not in mgr.active and not mgr.stop_failed(device)
    assert not mgr.has_leftovers(device)
    assert not mgr.isolation_manager.get_active_subnets()


def test_hostapd_that_does_not_stop_keeps_the_host_guard_and_isolation(running, monkeypatch):
    """REV-7: clients of an AP that may still transmit must not reach the host or other networks."""
    mgr, device = running
    real_stop = mgr.hostapd_manager.stop
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock(side_effect=CommandError("hostapd stuck")))
    with pytest.raises(NetworkStopError, match="hostapd: "):
        mgr.stop_network(device)
    assert mgr.host_guard.has(device)
    assert mgr.isolation_manager.get_active_subnets()
    assert mgr.nat_manager.has_pending_network(device)   # the Internet block stays too
    monkeypatch.setattr(mgr.hostapd_manager, "stop", real_stop)
    mgr.stop_network(device)
    assert not mgr.host_guard.has(device)
    assert not mgr.isolation_manager.get_active_subnets()
    assert not mgr.has_leftovers(device)
