"""PERF-2: checking that a network runs costs no radio query; client lists are reused briefly."""

from unittest.mock import Mock

import pytest
from conftest import active_network

from wilab.wifi import clients as clients_module
from wilab.wifi import manager as manager_module
from wilab.wifi import txpower as txpower_module


@pytest.fixture
def running(monkeypatch, config):
    mgr = manager_module.NetworkManager(config)
    device = config.antennas[0].device_id
    mgr.active[device] = active_network(interface=device, channel=6, tx_power_level=4, subnet="192.168.120.0/24")
    iw = Mock(return_value="")
    for module in (manager_module, clients_module, txpower_module):
        monkeypatch.setattr(module, "execute_iw", iw)
    monkeypatch.setattr(mgr.dhcp_server, "get_subnet_info", Mock(return_value={}))
    yield mgr, device, iw
    mgr.active.clear()


def test_active_status_runs_no_command(running):
    mgr, device, iw = running
    assert mgr.active_status(device) is mgr.active[device]
    iw.assert_not_called()


def test_active_status_of_an_idle_antenna_is_none(running):
    mgr, device, _iw = running
    mgr.active.clear()
    assert mgr.active_status(device) is None


def test_client_list_is_reused_for_a_moment(running, monkeypatch):
    mgr, device, iw = running
    now = [100.0]
    monkeypatch.setattr(clients_module.time, "monotonic", lambda: now[0])
    mgr.list_clients(device)
    mgr.list_clients(device)
    dumps = [c for c in iw.call_args_list if "station" in c.args[0]]
    assert len(dumps) == 1
    now[0] += clients_module.CLIENTS_CACHE_SECONDS + 0.1
    mgr.list_clients(device)
    assert len([c for c in iw.call_args_list if "station" in c.args[0]]) == 2


def test_a_status_read_leaves_the_stored_network_alone(running, monkeypatch):
    # ARCH-3: each read builds a new answer; the live reads are never stored.
    mgr, device, _iw = running
    monkeypatch.setattr(mgr, "list_clients", Mock(return_value=[]))
    stored = mgr.active[device]
    before = repr(stored)
    first = mgr.get_status(device)
    assert first is not None and first.clients_connected == 0 and first.dhcp == {}
    first.expires_at = "changed by a caller"
    assert mgr.get_status(device) is not first
    assert mgr.active[device] is stored and repr(stored) == before
