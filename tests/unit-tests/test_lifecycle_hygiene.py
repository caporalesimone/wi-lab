"""Fable chapter 4: a create/stop cycle logs no ERROR (T-13, ARCH-10) and leaves nothing behind (T-21, PERF-7).

The real start and stop run; hostapd and dnsmasq are fakes that only track their state,
and every system command is answered by the conftest fakes.
"""

import logging
import threading
from unittest.mock import Mock

import pytest
from conftest import ap, create_network, network_body
from fastapi.testclient import TestClient

RESERVE = "/api/v2/reservations"
BODY = network_body(
    ssid="hygiene", channel=6, encryption="wpa2", password="12345678", band="2.4ghz",
    tx_power_level=4, internet_enabled=True,
)


@pytest.fixture
def lab(monkeypatch, context, app):
    manager = context.manager
    monkeypatch.setattr(context.channels, "validate_network", Mock())
    monkeypatch.setattr(manager._channel_manager, "validate_network", Mock())
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    instances = manager.hostapd_manager._instances

    def hostapd_start(*, net_id, **kwargs):
        instances[net_id] = Mock()

    monkeypatch.setattr(manager.hostapd_manager, "start", hostapd_start)
    monkeypatch.setattr(manager.hostapd_manager, "stop", lambda net_id: instances.pop(net_id, None))
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock())
    monkeypatch.setattr(manager.dhcp_server, "list_active", Mock(return_value=[]))
    headers = {"Authorization": f"Bearer {context.config.auth_token}"}
    with TestClient(app) as client:
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 3600}).json()["reservation_id"]
        yield client, headers, f"{RESERVE}/{rid}", manager, context
        manager.active.clear()


def _cycle(client, headers, url):
    _created, network = create_network(client, headers, ap(url), BODY)
    assert network.status_code == 200 and network.json()["active"], network.text
    assert client.get(ap(url), headers=headers).status_code == 200
    assert client.post(ap(url, "/internet/disable"), headers=headers).status_code == 200
    assert client.post(ap(url, "/internet/enable"), headers=headers).status_code == 200
    assert client.delete(ap(url), headers=headers).status_code == 200


def test_a_full_cycle_logs_no_error(lab, caplog):
    """T-13: ERROR means someone must act. A healthy create, read, Internet toggle and stop logs none."""
    client, headers, url, _manager, _context = lab
    with caplog.at_level(logging.ERROR):
        _cycle(client, headers, url)
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], [f"{r.name}: {r.getMessage()}" for r in errors]


def _sizes(manager, context) -> dict[str, int]:
    return {
        "active": len(manager.active),
        "hostapd": len(manager.hostapd_manager._instances),
        "dhcp": len(manager.dhcp_server._instances),
        "captive_portals": len(manager.captive_portals),
        "nat_blocked": len(manager.nat_manager._blocked_rules),
        "nat_networks": len(manager.nat_manager._nat_networks),
        "watchdog_states": len(manager.watchdog.states),
        "start_jobs": len(manager.start_jobs),
        "stop_failed": len(manager._stop_failed),
        "threads": threading.active_count(),
    }


def test_many_cycles_leave_nothing_behind(lab):
    """T-21: after many create/stop cycles every per-network structure and the thread count are back to the start."""
    client, headers, url, manager, context = lab
    _cycle(client, headers, url)   # warm-up: lazily started helpers exist from here on
    before = _sizes(manager, context)
    for _ in range(200):
        _cycle(client, headers, url)
    after = _sizes(manager, context)
    assert after == before
