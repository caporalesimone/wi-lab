"""BUG-2: /status health checks look at Wi-Lab's own processes and rules."""

import json
from unittest.mock import Mock

import pytest
from conftest import active_network
from fastapi.testclient import TestClient

from wilab import health as status_module
from wilab.config import load_config


def _link(operstate: str, flags: list[str], inet: bool = True) -> str:
    addr = [{"family": "inet", "local": "192.0.2.10", "prefixlen": 24}] if inet else []
    return json.dumps([{"ifname": "eth0", "operstate": operstate, "flags": flags, "addr_info": addr}])


@pytest.fixture
def running(monkeypatch, context, app):
    """One settled network; hostapd and dnsmasq alive; upstream up."""
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {load_config().auth_token}"}
        manager = context.manager
        device = manager.config.antennas[0].device_id
        state = {"internet": False, "nat": "-P POSTROUTING ACCEPT", "link": _link("UP", ["UP", "LOWER_UP"])}

        def network():
            return active_network(interface=device, subnet="192.168.120.0/24",
                                 internet_enabled=state["internet"])

        context.reservations.create(3600, device)   # a network always belongs to a reservation
        monkeypatch.setitem(manager.active, device, network())
        monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=True))
        monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
        monkeypatch.setattr(manager, "firewall_status", lambda: {"nat": state["nat"], "errors": []})
        monkeypatch.setattr(manager.nat_manager, "get_upstream_interface", lambda: "eth0")
        monkeypatch.setattr(status_module, "execute_command", lambda cmd, **kw: state["link"])

        def get():
            manager.active[device] = network()
            data = client.get("/api/v2/status", headers=headers).json()
            return {**data, "antennas": client.get("/api/v2/antennas", headers=headers).json()["antennas"]}

        yield get, state, manager, device


def test_network_without_internet_is_ok_on_a_host_without_nat_rules(running):
    get, _state, _manager, _device = running
    data = get()
    assert data["service"]["health"] == "good"  # before BUG-2: degraded (no MASQUERADE anywhere)
    assert data["checks"]["iptables_nat"] == {"configured": True, "missing": [], "errors": []}


def test_foreign_masquerade_does_not_count_for_a_network_with_internet(running):
    get, state, _manager, device = running
    state["internet"] = True
    state["nat"] = "-A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE"  # Docker's rule
    data = get()
    assert data["service"]["health"] == "degraded"
    assert data["checks"]["iptables_nat"]["missing"] == [device]
    state["nat"] += f'\n-A POSTROUTING -s 192.168.120.0/24 -o eth0 -m comment --comment wilab-nat-{device} -j MASQUERADE'
    assert get()["service"]["health"] == "good"


@pytest.mark.parametrize("internet", [False, True])
def test_the_upstream_link_never_degrades(running, internet):
    """The upstream is shown in checks only (2026-11-27): a down link is not a reason."""
    get, state, _manager, device = running
    state["internet"] = internet
    state["nat"] = f"-A POSTROUTING -s 192.168.120.0/24 -o eth0 -m comment --comment wilab-nat-{device} -j MASQUERADE"
    state["link"] = _link("DOWN", ["UP"], inet=False)
    data = get()
    assert data["service"]["health"] == "good"
    assert data["checks"]["upstream_interface"]["operstate"] == "DOWN"
    assert data["checks"]["upstream_interface"]["ipv4"] == []


def test_dead_hostapd_is_reported_and_degrades(running):
    get, _state, manager, device = running
    manager.hostapd_manager.is_running.return_value = False
    data = get()
    assert data["checks"]["hostapd"] == {"running": False, "instances": 0, "missing": [device]}
    assert data["service"]["health"] == "degraded"


def test_status_reads_the_background_checks_without_running_commands(monkeypatch, context, app):
    """The host commands run in the health loop; /status only reads the latest result."""
    from wilab import health

    config = context.config
    manager = context.manager
    monkeypatch.setattr(health, "MAX_AGE", 60.0)
    manager.health.refresh()
    calls = []
    monkeypatch.setattr(health, "execute_command", lambda cmd, **kw: calls.append(cmd) or "[]")
    monkeypatch.setattr(manager, "firewall_status", lambda: calls.append("fw") or {"nat": ""})
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    for _ in range(5):
        assert client.get("/api/v2/status", headers=headers).status_code == 200
    assert calls == []


def test_a_late_loop_does_not_leave_status_stale(monkeypatch, context):
    from wilab import health

    manager = context.manager
    monkeypatch.setattr(health, "MAX_AGE", 60.0)
    first = manager.health.refresh()
    assert manager.health.current() is first
    monkeypatch.setattr(health.time, "monotonic", lambda: first.taken + 61.0)
    assert manager.health.current() is not first


def test_degraded_reasons_name_the_problem_and_the_antenna(monkeypatch, context, app):
    """/status gives coded reasons and the detail of the same checks."""
    from wilab.api.routes import status as status_route

    config = context.config
    manager = context.manager
    device = manager.config.antennas[0].device_id
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    monkeypatch.setattr(manager.hostapd_manager, "is_running", lambda _d: False)
    monkeypatch.setattr(status_route, "stuck_commands", lambda: 1)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    status = client.get("/api/v2/status", headers=headers).json()
    assert status["service"]["health"] == "degraded"
    codes = [(r["code"], r["interface"]) for r in status["service"]["degraded_reasons"]]
    assert ("hostapd_not_running", device) in codes and ("command_stuck", None) in codes
    assert status["checks"]["hostapd"]["missing"] == [device]
    assert status["check_interval_seconds"] == 10 and status["checked_at"].endswith("Z")
    assert client.get("/api/v2/status").status_code == 401


def test_half_stopped_network_is_reported_as_stop_incomplete_only(running, monkeypatch):
    """API-1 #1: /status shows stop_failed like GET .../network, not as a dead dnsmasq."""
    get, _state, manager, device = running
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=False))  # stopped by the stop
    manager._stop_failed.add(device)
    try:
        data = get()
    finally:
        manager._stop_failed.discard(device)
    entry = next(a for a in data["antennas"] if a["interface"] == device)
    assert entry["runtime_state"] == "stop_failed"
    assert [r["code"] for r in data["service"]["degraded_reasons"]] == ["network_stop_incomplete"]


def test_upstream_shows_the_interface_details(monkeypatch, context):
    """In checks.upstream_interface: addresses, MAC, MTU and gateway instead of a bare has_ip (2026-11-27)."""
    link = json.dumps([{
        "ifname": "eth0", "operstate": "UP", "flags": ["UP", "LOWER_UP"], "mtu": 1500,
        "address": "bc:24:11:07:a6:9b",
        "addr_info": [
            {"family": "inet", "local": "192.0.2.10", "prefixlen": 24, "scope": "global"},
            {"family": "inet6", "local": "2001:db8::10", "prefixlen": 64, "scope": "global"},
            {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"},
        ],
    }])
    route = json.dumps([{"dst": "default", "gateway": "192.0.2.1", "dev": "eth0"}])
    monkeypatch.setattr(status_module, "execute_command", lambda cmd, **kw: route if "route" in cmd else link)
    monkeypatch.setattr(context.manager.nat_manager, "get_upstream_interface", lambda: "eth0")
    assert status_module._upstream_check(context.manager) == {
        "name": "eth0", "operstate": "UP", "mac": "bc:24:11:07:a6:9b",
        "mtu": 1500, "ipv4": ["192.0.2.10/24"], "ipv6": ["2001:db8::10/64"], "gateway": "192.0.2.1",
    }
