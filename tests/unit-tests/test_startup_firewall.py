"""NET-2: a network never reports success without the NAT and isolation it claims.

NET-4: the misleading "Isolation disabled for testing" log line is gone.
"""

import logging
from unittest.mock import Mock

import pytest
from conftest import network_body
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.network.commands import CommandError
from wilab.wifi.manager import NetworkManager, StartupFailure


def _request(**kwargs) -> NetworkCreateRequest:
    return NetworkCreateRequest(
        ssid="fw", channel=6, encryption="open", band="2.4ghz", tx_power_level=4, **kwargs,
    )


@pytest.fixture
def manager(monkeypatch) -> NetworkManager:
    mgr = NetworkManager(load_config())
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "start", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    return mgr


def test_nat_failure_fails_the_startup_and_rolls_back(monkeypatch, manager):
    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(
        manager.nat_manager, "enable_nat", Mock(side_effect=RuntimeError("Cannot enable NAT: no default route")),
    )
    release = Mock(wraps=manager.release_device)
    monkeypatch.setattr(manager, "release_device", release)
    with pytest.raises(StartupFailure, match="enable Internet") as failure:
        manager.start_network(device, _request(internet_enabled=True))
    assert not failure.value.radio and not failure.value.cleanup_failed
    assert device not in manager.active
    # Once before the start, once for the rollback that tears the AP down.
    assert release.call_count == 2
    assert not manager.nat_manager.has_pending_network(device)
    assert not manager.isolation_manager.get_active_subnets()


def test_isolation_failure_fails_the_startup_and_removes_nat(monkeypatch, manager):
    device = manager.config.antennas[0].device_id
    # Another network is already isolated, so this one needs blocking rules.
    manager.isolation_manager._active_subnets.add("192.168.199.0/24")
    monkeypatch.setattr(
        manager.isolation_manager, "_block_traffic", Mock(side_effect=CommandError("iptables failed")),
    )
    with pytest.raises(StartupFailure, match="isolate network"):
        manager.start_network(device, _request(internet_enabled=True))
    assert device not in manager.active
    assert not manager.nat_manager.has_pending_network(device)
    assert manager.isolation_manager.get_active_subnets() == ["192.168.199.0/24"]


def test_rollback_removes_isolation_of_a_network_that_never_became_active(monkeypatch, manager):
    device = manager.config.antennas[0].device_id
    removed = []
    original = manager.isolation_manager.remove_network
    monkeypatch.setattr(
        manager.isolation_manager, "remove_network", lambda subnet: removed.append(subnet) or original(subnet),
    )
    status = manager.start_network(device, _request(internet_enabled=False))
    # A rollback runs before the network is registered in `active`: the teardown
    # must still find the subnet, from the assignment.
    manager.active.pop(device)
    manager.release_device(device)
    assert removed == [status.subnet]
    assert not manager.isolation_manager.get_active_subnets()


def test_successful_start_logs_no_false_isolation_line(manager, caplog):
    device = manager.config.antennas[0].device_id
    with caplog.at_level(logging.INFO):
        manager.start_network(device, _request(internet_enabled=True))
    assert "Isolation rules applied" in caplog.text
    assert "Isolation disabled for testing" not in caplog.text


def test_api_returns_500_and_keeps_the_reservation(monkeypatch):
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    monkeypatch.setattr(mgr.hostapd_manager, "start", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(
        mgr.nat_manager, "enable_nat", Mock(side_effect=RuntimeError("Cannot enable NAT: no default route")),
    )
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    body = {"ssid": "fw", "channel": 6, "band": "2.4ghz", "encryption": "open",
            "tx_power_level": 4, "internet_enabled": True}
    with TestClient(create_app()) as client:
        rid = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 60}).json()[
            "reservation_id"
        ]
        response = client.post(f"/api/v2/reservations/{rid}/network", headers=headers, json=network_body(**body))
        assert response.status_code == 500
        assert "enable Internet" in response.json()["detail"]["message"]
        assert "Retry-After" not in response.headers
        network = client.get(f"/api/v2/reservations/{rid}/network", headers=headers).json()
        assert network["active"] is False
        assert client.get(f"/api/v2/reservations/{rid}", headers=headers).status_code == 200
