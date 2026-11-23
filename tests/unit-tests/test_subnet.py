import json
from ipaddress import IPv4Network

import pytest

from wilab.network.commands import CommandError
from wilab.network.subnet import host_ipv4_networks


def test_host_networks_include_connected_routes_and_local_addresses(monkeypatch):
    routes = [
        {"dst": "default", "dev": "eth0"},
        {"dst": "192.168.0.0/16", "dev": "eth0"},
        {"dst": "192.168.120.1", "dev": "lo", "type": "local"},
        {"dst": "192.168.120.255", "type": "broadcast"},
    ]
    monkeypatch.setattr("wilab.network.subnet.execute_command", lambda cmd, **kwargs: json.dumps(routes))
    assert host_ipv4_networks() == {IPv4Network("192.168.0.0/16"), IPv4Network("192.168.120.1/32")}


def test_route_check_failure_is_reported(monkeypatch):
    def fail(_cmd, **kwargs):
        raise CommandError("unavailable")

    monkeypatch.setattr("wilab.network.subnet.execute_command", fail)
    with pytest.raises(ValueError, match="Cannot check AP subnet"):
        host_ipv4_networks()
