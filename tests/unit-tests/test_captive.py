"""Tests for the simulated captive portal."""

import http.client
import threading
from unittest.mock import Mock

import pytest

from wilab.api import dependencies
from wilab.config import load_config
from wilab.models import NetworkCreateRequest, NetworkStatus
from wilab.network import captive
from wilab.network.commands import CommandError
from wilab.network.dhcp import DhcpServer
from wilab.wifi.manager import NetworkManager, StartupFailure

CLIENT_MAC = "aa:bb:cc:dd:ee:01"


@pytest.fixture
def iptables(monkeypatch):
    """Record iptables changes; listings show one installed portal for wls16."""
    calls: list[list[str]] = []

    def listing(cmd):
        table = cmd[cmd.index("-t") + 1] if "-t" in cmd else "filter"
        chain = cmd[-1] if cmd[-1] != "-S" else None
        if chain == "PREROUTING":
            return "-A PREROUTING -i wls16 -m comment --comment wilab-captive-wls16 -j wilab-cp-wls16\n"
        if chain == "FORWARD":
            return (
                "-A FORWARD -i wls16 -m comment --comment wilab-captive-wls16 -j wilab-cp-wls16\n"
                "-A FORWARD -i other -m comment --comment wilab-captive-other -j wilab-cp-other\n"
            )
        return f"-P INPUT ACCEPT\n-N wilab-cp-wls16\n-N wilab-cp-other\n-N unrelated-{table}\n"

    def iptables_call(args):
        if "-S" in args:
            return listing(args)
        calls.append(args)
        return ""

    monkeypatch.setattr(captive, "execute_iptables", iptables_call)
    return calls


def _portal(mac: str | None = CLIENT_MAC, **kwargs) -> captive.CaptivePortal:
    context = {
        "ssid": "<b>lab</b>", "radio": "2.4ghz / 6", "subnet": "192.168.120.0/24",
        "dhcp_range": "192.168.120.10 - 192.168.120.250",
        "internet": "enabled after sign-in", "expires": "no expiry",
    }
    return captive.CaptivePortal(
        interface="wls16", net_id="wls16", gateway="127.0.0.1",
        context=lambda: context, lookup_mac=lambda ip: mac, firewall_lock=threading.Lock(), **kwargs,
    )


@pytest.fixture
def served(iptables):
    """Serve a portal over loopback, so 127.0.0.1 is both gateway and client."""
    servers = []

    def serve(portal: captive.CaptivePortal) -> captive.CaptivePortal:
        server = captive._PortalHTTPServer(("127.0.0.1", 0), portal)
        portal.port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return portal

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _request(portal, method: str, path: str, host: str | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", portal.port, timeout=5)
    conn.request(method, path, headers={"Host": host or f"127.0.0.1:{portal.port}"})
    response = conn.getresponse()
    body = response.read().decode()
    conn.close()
    return response, body


def test_probe_redirects_and_sign_in_releases_only_that_client(served, iptables):
    portal = served(_portal())

    probe, _ = _request(portal, "GET", "/generate_204", host="connectivitycheck.gstatic.com")
    assert probe.status == 302 and probe.getheader("Location") == portal.url

    page, body = _request(portal, "GET", "/")
    assert page.status == 200 and page.getheader("Cache-Control") == "no-store"
    assert "WiLab Captive Portal" in body and "&lt;b&gt;lab&lt;/b&gt;" in body and "<b>lab" not in body
    assert "192.168.120.0/24" in body and CLIENT_MAC in body and 'action="/login"' in body

    for _ in range(2):
        login, _ = _request(portal, "POST", "/login")
        assert login.status == 303 and login.getheader("Location") == portal.url
    rule = ["-s", "127.0.0.1", "-m", "mac", "--mac-source", CLIENT_MAC, "-j", "RETURN"]
    assert iptables == [
        ["-t", "nat", "-I", "wilab-cp-wls16", "1", *rule],
        ["-I", "wilab-cp-wls16", "1", *rule],
    ]
    assert portal.is_authorized("127.0.0.1", CLIENT_MAC)
    assert not portal.is_authorized("127.0.0.1", "aa:bb:cc:dd:ee:02")

    _, body = _request(portal, "GET", "/")
    assert "You are signed in" in body and 'action="/login"' not in body


def test_unidentified_client_is_not_released(served, iptables):
    portal = served(_portal(mac=None))
    response, body = _request(portal, "POST", "/login")
    assert response.status == 400 and "could not identify" in body
    assert iptables == []


def test_malformed_content_length_is_400_not_a_traceback(served, iptables):
    """NET-10 #2."""
    portal = served(_portal())
    conn = http.client.HTTPConnection("127.0.0.1", portal.port, timeout=5)
    conn.putrequest("POST", "/login", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{portal.port}")
    conn.putheader("Content-Length", "abc")
    conn.endheaders()
    response = conn.getresponse()
    conn.close()
    assert response.status == 400
    assert iptables == []


def test_port_in_use_is_a_clear_error_and_rolls_back(iptables, monkeypatch):
    """NET-10 #1: EADDRINUSE names the port and the setting; no rule is left behind."""
    import socket

    # conftest replaces the real server; this test needs the real bind.
    monkeypatch.setattr(
        captive.CaptivePortal, "_open_server",
        lambda self: captive._PortalHTTPServer((self.gateway, self.port), self),
    )
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    try:
        portal = _portal(port=busy.getsockname()[1])
        with pytest.raises(captive.CaptivePortalError, match="already in use.*captive_portal_port"):
            portal.start()
    finally:
        busy.close()
    assert any(call[:1] == ["-X"] or "-X" in call for call in iptables)  # chains removed


def test_portal_serves_on_the_configured_port_and_redirects_port_80(iptables):
    portal = _portal(port=8081)
    assert portal.url == "http://127.0.0.1:8081/"
    portal._open_server = Mock()
    portal.start()
    dnat = next(c for c in iptables if "--dport" in c and c[c.index("--dport") + 1] == "80")
    assert dnat[-1] == "127.0.0.1:8081"


def test_start_redirects_dns_and_http_and_stop_removes_only_its_rules(iptables):
    portal = _portal(port=80)
    portal.start()
    jump = ["-i", "wls16", "-m", "comment", "--comment", "wilab-captive-wls16", "-j", "wilab-cp-wls16"]
    for rule in (
        ["-t", "nat", "-A", "wilab-cp-wls16", "-p", "udp", "--dport", "53",
         "-j", "DNAT", "--to-destination", "127.0.0.1:53"],
        ["-t", "nat", "-A", "wilab-cp-wls16", "-p", "tcp", "--dport", "80",
         "-j", "DNAT", "--to-destination", "127.0.0.1:80"],
        ["-A", "wilab-cp-wls16", "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"],
    ):
        assert rule in iptables
    # Traffic is diverted only once the chains are complete.
    assert iptables[-2:] == [["-t", "nat", "-I", "PREROUTING", "1", *jump], ["-I", "FORWARD", "1", *jump]]
    iptables.clear()

    portal.stop()
    assert iptables == [
        ["-t", "nat", "-D", "PREROUTING", *jump],
        ["-t", "nat", "-F", "wilab-cp-wls16"], ["-t", "nat", "-X", "wilab-cp-wls16"],
        ["-D", "FORWARD", *jump],
        ["-F", "wilab-cp-wls16"], ["-X", "wilab-cp-wls16"],
    ]
    with pytest.raises(captive.CaptivePortalError):
        portal.authorize("127.0.0.1")


def test_stale_cleanup_removes_every_portal_chain(iptables):
    captive.remove_stale_captive_rules()
    assert {tuple(call[-1:]) for call in iptables if "-X" in call} == {("wilab-cp-wls16",), ("wilab-cp-other",)}
    assert not any("unrelated" in " ".join(call) for call in iptables)


def test_captive_dns_answers_every_query_with_the_gateway():
    server = DhcpServer()
    captive_config = server._generate_config(
        "wls16", "192.168.120.1", "192.168.120.10,192.168.120.250", "/tmp/leases", "8.8.8.8",
        captive_dns=True,
    )
    assert "address=/#/192.168.120.1" in captive_config and "except-interface=lo" in captive_config
    assert "port=0" not in captive_config
    assert "dhcp-option=option:dns-server,8.8.8.8" in captive_config
    plain = server._generate_config("wls16", "192.168.120.1", "a,b", "/tmp/leases", "8.8.8.8")
    assert "port=0" in plain and "address=/#/" not in plain


def _captive_request(**kwargs) -> NetworkCreateRequest:
    return NetworkCreateRequest(
        ssid="Portal", channel=6, encryption="open", band="2.4ghz", tx_power_level=4,
        captive_portal=True, **kwargs,
    )


def test_network_lifecycle_starts_and_removes_the_portal(monkeypatch, iptables):
    mgr = NetworkManager(load_config())
    dhcp_start = Mock(return_value={})
    monkeypatch.setattr(mgr.dhcp_server, "start", dhcp_start)
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "start", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())

    status = mgr.start_network("wls16", _captive_request())
    assert dhcp_start.call_args.kwargs["captive_dns"] is True
    assert status.captive_portal is True and status.captive_portal_url == "http://192.168.120.1:8081/"
    portal = mgr.captive_portals["wls16"]
    assert portal.gateway == "192.168.120.1"
    assert portal.context()["ssid"] == "Portal"

    mgr.stop_network("wls16")
    assert "wls16" not in mgr.captive_portals and "wls16" not in mgr.active
    assert ["-X", "wilab-cp-wls16"] in iptables


def test_portal_failure_rolls_back_the_network(monkeypatch, iptables):
    mgr = NetworkManager(load_config())
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.hostapd_manager, "start", Mock())
    stop_ap = Mock()
    monkeypatch.setattr(mgr.hostapd_manager, "stop", stop_ap)

    def fail_on_chain(args):
        if "-N" in args:
            raise CommandError("chain exists")
        return ""

    monkeypatch.setattr(captive, "execute_iptables", fail_on_chain)
    with pytest.raises(StartupFailure, match="captive portal"):
        mgr.start_network("wls16", _captive_request())
    assert not mgr.captive_portals and not mgr.active
    stop_ap.assert_called()


def test_watchdog_restart_keeps_the_portal(monkeypatch):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    status = NetworkStatus(
        interface=reservation.device_id, active=True, ssid="Portal", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4, captive_portal=True,
    )
    monkeypatch.setattr(manager, "release_device", Mock())
    restart = Mock()
    monkeypatch.setattr(manager, "start_network", restart)
    manager.watchdog._restore_ap(reservations, reservation, status, False)
    assert restart.call_args.args[1].captive_portal is True
