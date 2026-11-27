"""RACE-2: /status is computed from one snapshot and ignores networks mid-operation."""

import threading

import pytest
from conftest import active_network
from fastapi.testclient import TestClient

from wilab.config import load_config


@pytest.fixture
def stopping_network(monkeypatch, context, app):
    """An active network whose DHCP is already gone, as in the middle of a stop."""
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {load_config().auth_token}"}
        manager = context.manager
        device = manager.config.antennas[0].device_id
        monkeypatch.setitem(
            manager.active, device,
            active_network(interface=device, subnet="192.168.120.0/24"),
        )
        # The checks ask each process (BUG-2): hostapd is alive, dnsmasq is not.
        monkeypatch.setattr(manager.hostapd_manager, "is_running", lambda _device: True)
        monkeypatch.setattr(manager.dhcp_server, "is_running", lambda _device: False)
        yield client, headers, manager, device


def _hold(manager, device):
    held, release = threading.Event(), threading.Event()

    def holder():
        with manager.devices.lock(device):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)
    return release, thread


def test_network_mid_operation_does_not_make_status_degraded(stopping_network):
    client, headers, manager, device = stopping_network
    release, thread = _hold(manager, device)  # the stop holds the device lock
    try:
        data = client.get("/api/v2/status", headers=headers).json()
    finally:
        release.set()
        thread.join()
    assert data["active_networks"] == 1
    assert data["status"] == "ok"


def test_settled_network_with_dhcp_down_is_still_degraded(stopping_network):
    client, headers, _manager, _device = stopping_network
    data = client.get("/api/v2/status", headers=headers).json()
    assert data["status"] == "degraded"
    assert [reason["code"] for reason in data["degraded_reasons"]] == ["dnsmasq_not_running"]
