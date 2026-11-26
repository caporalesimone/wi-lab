"""PERF-2: checking that a network runs costs no radio query; client lists are reused briefly."""

from unittest.mock import Mock

import pytest

from wilab.models import NetworkStatus
from wilab.wifi import manager as manager_module


@pytest.fixture
def running(monkeypatch, config):
    mgr = manager_module.NetworkManager(config)
    device = config.antennas[0].device_id
    mgr.active[device] = NetworkStatus(interface=device, active=True, channel=6, tx_power_level=4, subnet="192.168.120.0/24")
    iw = Mock(return_value="")
    monkeypatch.setattr(manager_module, "execute_iw", iw)
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
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now[0])
    mgr.list_clients(device)
    mgr.list_clients(device)
    dumps = [c for c in iw.call_args_list if "station" in c.args[0]]
    assert len(dumps) == 1
    now[0] += manager_module.CLIENTS_CACHE_SECONDS + 0.1
    mgr.list_clients(device)
    assert len([c for c in iw.call_args_list if "station" in c.args[0]]) == 2
