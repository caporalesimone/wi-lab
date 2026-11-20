import json
import logging

from wilab.network.commands import CommandError
from wilab.network.subnet import warn_subnet_collisions


def test_warns_about_host_overlap_without_matching_default_or_owned_routes(monkeypatch, caplog):
    routes = [
        {"dst": "default", "dev": "eth0"},
        {"dst": "192.168.120.0/24", "dev": "wlan0", "protocol": "kernel", "prefsrc": "192.168.120.1"},
        {"dst": "192.168.0.0/16", "dev": "eth0"},
        {"dst": "192.168.120.1", "dev": "lo", "type": "local"},
    ]
    monkeypatch.setattr("wilab.network.subnet.execute_command", lambda cmd: json.dumps(routes))
    with caplog.at_level(logging.WARNING):
        warn_subnet_collisions("192.168.120.0/24", {("192.168.120.0/24", "wlan0", "192.168.120.1")})
    assert caplog.text.count("overlaps existing route") == 1
    assert "192.168.0.0/16" in caplog.text


def test_route_on_same_interface_is_not_assumed_to_be_owned(monkeypatch, caplog):
    routes = [{"dst": "192.168.120.0/24", "dev": "wlan0", "protocol": "static"}]
    monkeypatch.setattr("wilab.network.subnet.execute_command", lambda cmd: json.dumps(routes))
    warn_subnet_collisions("192.168.120.0/24", {("192.168.120.0/24", "wlan0", "192.168.120.1")})
    assert "overlaps existing route" in caplog.text


def test_route_check_failure_is_reported(monkeypatch, caplog):
    def fail(_cmd):
        raise CommandError("unavailable")

    monkeypatch.setattr("wilab.network.subnet.execute_command", fail)
    warn_subnet_collisions("192.168.120.0/24", set())
    assert "Cannot check subnet" in caplog.text
