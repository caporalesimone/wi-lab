"""Minimal captive portal for a Wi-Lab access point.

Until a client presses the portal button, its DNS queries are answered by the
AP's dnsmasq with the gateway address, its HTTP requests are redirected to the
portal page, and any other forwarded traffic is rejected. Pressing the button
exempts only that client (MAC and IP) from the redirection.
"""

import html
import logging
import re
import shlex
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from itertools import pairwise

from .commands import CommandError, execute_iptables

logger = logging.getLogger(__name__)

PORTAL_PORT = 80
DNS_PORT = 53
CHAIN_PREFIX = "wilab-cp-"
JUMP_COMMENT_PREFIX = "wilab-captive-"
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_MAX_BODY = 4096


class CaptivePortalError(Exception):
    """The captive portal could not be started or stopped."""


class UnknownClientError(Exception):
    """The portal could not identify the client's MAC address."""


def _chain(net_id: str) -> str:
    return f"{CHAIN_PREFIX}{net_id}"


def _iptables_listing(table: str | None, chain: str | None = None) -> list[list[str]]:
    prefix = ["-t", table] if table else []
    output = execute_iptables([*prefix, "-S", *([chain] if chain else [])])
    return [shlex.split(line) for line in output.splitlines() if line.strip()]


def _remove_rules(net_id: str | None) -> None:
    """Delete jump rules and chains of one portal, or of every portal when *net_id* is None."""
    def owned(name: str, prefix: str) -> bool:
        return name == f"{prefix}{net_id}" if net_id is not None else name.startswith(prefix)

    for table, parent in (("nat", "PREROUTING"), (None, "FORWARD")):
        prefix = ["-t", table] if table else []
        for tokens in _iptables_listing(table, parent):
            comments = [value for option, value in pairwise(tokens) if option == "--comment"]
            if tokens[:2] == ["-A", parent] and any(owned(c, JUMP_COMMENT_PREFIX) for c in comments):
                execute_iptables([*prefix, "-D", *tokens[1:]])
        for tokens in _iptables_listing(table):
            if tokens[:1] == ["-N"] and len(tokens) >= 2 and owned(tokens[1], CHAIN_PREFIX):
                execute_iptables([*prefix, "-F", tokens[1]])
                execute_iptables([*prefix, "-X", tokens[1]])


def remove_stale_captive_rules() -> None:
    """Remove captive portal rules left by a previous Wi-Lab process."""
    try:
        _remove_rules(None)
    except (CommandError, ValueError) as exc:
        logger.warning("Cannot remove stale captive portal rules: %s", exc)


class CaptivePortal:
    """Firewall redirection and portal web server for one access point."""

    def __init__(
        self, *, interface: str, net_id: str, gateway: str,
        context: Callable[[], dict[str, str]],
        lookup_mac: Callable[[str], str | None],
        firewall_lock: threading.Lock,
        port: int = PORTAL_PORT,
    ) -> None:
        self.interface = interface
        self.net_id = net_id
        self.gateway = gateway
        self.port = port
        self.context = context
        self._lookup_mac = lookup_mac
        self._firewall_lock = firewall_lock
        self._lock = threading.Lock()
        self._authorized: set[tuple[str, str]] = set()
        self._closed = False
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.gateway}/" if self.port == 80 else f"http://{self.gateway}:{self.port}/"

    def start(self) -> None:
        chain = _chain(self.net_id)
        jump = ["-i", self.interface, "-m", "comment", "--comment", f"{JUMP_COMMENT_PREFIX}{self.net_id}"]
        try:
            with self._firewall_lock:
                execute_iptables(["-t", "nat", "-N", chain])
                for protocol in ("udp", "tcp"):
                    execute_iptables([
                        "-t", "nat", "-A", chain, "-p", protocol, "--dport", str(DNS_PORT),
                        "-j", "DNAT", "--to-destination", f"{self.gateway}:{DNS_PORT}",
                    ])
                execute_iptables([
                    "-t", "nat", "-A", chain, "-p", "tcp", "--dport", "80",
                    "-j", "DNAT", "--to-destination", f"{self.gateway}:{self.port}",
                ])
                execute_iptables(["-N", chain])
                execute_iptables(["-A", chain, "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"])
                execute_iptables(["-A", chain, "-j", "REJECT"])
                execute_iptables(["-t", "nat", "-I", "PREROUTING", "1", *jump, "-j", chain])
                execute_iptables(["-I", "FORWARD", "1", *jump, "-j", chain])
            server = self._open_server()
        except (CommandError, OSError) as exc:
            try:
                with self._firewall_lock:
                    _remove_rules(self.net_id)
            except (CommandError, ValueError):
                logger.exception("Cannot roll back captive portal rules for %s", self.net_id)
            raise CaptivePortalError(f"Cannot start captive portal: {exc}") from exc
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name=f"captive-portal-{self.net_id}", daemon=True,
        )
        self._thread.start()
        logger.info("Captive portal for %s serving %s", self.net_id, self.url)

    def _open_server(self) -> ThreadingHTTPServer:
        return _PortalHTTPServer((self.gateway, self.port), self)

    def stop(self) -> None:
        """Stop the web server, then remove every rule including client exemptions."""
        with self._lock:
            self._closed = True
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            with self._firewall_lock:
                _remove_rules(self.net_id)
        except (CommandError, ValueError) as exc:
            raise CaptivePortalError(f"Cannot remove captive portal rules: {exc}") from exc
        with self._lock:
            self._authorized.clear()
        logger.info("Captive portal for %s stopped", self.net_id)

    def client_mac(self, ip: str) -> str | None:
        mac = self._lookup_mac(ip)
        return mac.lower() if mac and _MAC.match(mac.lower()) else None

    def is_authorized(self, ip: str, mac: str | None) -> bool:
        with self._lock:
            return mac is not None and (mac.lower(), ip) in self._authorized

    def authorize(self, ip: str) -> str:
        """Exempt the client at *ip* from the portal; return its MAC address."""
        ip = str(IPv4Address(ip))
        mac = self.client_mac(ip)
        if mac is None:
            raise UnknownClientError(f"No MAC address known for {ip}")
        with self._lock:
            if self._closed:
                raise CaptivePortalError("Captive portal is stopping")
            if (mac, ip) in self._authorized:
                return mac
            chain = _chain(self.net_id)
            match = ["-s", ip, "-m", "mac", "--mac-source", mac, "-j", "RETURN"]
            try:
                with self._firewall_lock:
                    execute_iptables(["-t", "nat", "-I", chain, "1", *match])
                    try:
                        execute_iptables(["-I", chain, "1", *match])
                    except CommandError:
                        execute_iptables(["-t", "nat", "-D", chain, *match])
                        raise
            except CommandError as exc:
                raise CaptivePortalError(f"Cannot authorize {ip}: {exc}") from exc
            self._authorized.add((mac, ip))
        logger.info("Captive portal on %s authorized client %s (%s)", self.net_id, mac, ip)
        return mac


class _PortalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], portal: CaptivePortal) -> None:
        self.portal = portal
        super().__init__(address, _PortalHandler)


_PAGE_STYLE = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#eef2f7;margin:0;
padding:24px;color:#1f2933}main{max-width:480px;margin:0 auto;background:#fff;border-radius:12px;
padding:24px;box-shadow:0 2px 10px rgba(0,0,0,.08)}h1{margin-top:0;font-size:1.5rem}
table{width:100%;border-collapse:collapse;margin:16px 0}th{text-align:left;color:#52606d;font-weight:500;
padding:6px 8px 6px 0;white-space:nowrap;vertical-align:top}td{padding:6px 0;word-break:break-all}
button{width:100%;padding:14px;font-size:1rem;border:0;border-radius:8px;background:#2563eb;color:#fff}
.ok{color:#047857;font-weight:600}.wait{color:#b45309;font-weight:600}.error{color:#b91c1c}
footer{margin-top:16px;font-size:.8rem;color:#7b8794}
"""


class _PortalHandler(BaseHTTPRequestHandler):
    server: _PortalHTTPServer
    timeout = 5
    server_version = "WiLabCaptivePortal"

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("Captive portal %s: %s", self.server.portal.net_id, format % args)

    def _on_portal(self) -> bool:
        portal = self.server.portal
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host == portal.gateway

    def _redirect(self, status: int = 302) -> None:
        self.send_response(status)
        self.send_header("Location", self.server.portal.url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self) -> None:
        if self._on_portal() and self.path.split("?", 1)[0] == "/":
            self._send_page(200)
        else:
            self._redirect()

    def do_HEAD(self) -> None:
        self._redirect()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 0:
            self.rfile.read(min(length, _MAX_BODY))
        if not (self._on_portal() and self.path.split("?", 1)[0] == "/login"):
            self._redirect(303)
            return
        try:
            self.server.portal.authorize(self.client_address[0])
        except UnknownClientError:
            self._send_page(400, "Wi-Lab could not identify this device. Reconnect to the network and retry.")
            return
        except (CaptivePortalError, ValueError):
            logger.exception("Captive portal sign-in failed on %s", self.server.portal.net_id)
            self._send_page(500, "Sign-in failed. Retry in a few seconds.")
            return
        self._redirect(303)

    def _send_page(self, status: int, error: str | None = None) -> None:
        portal = self.server.portal
        ip = self.client_address[0]
        mac = portal.client_mac(ip)
        authorized = portal.is_authorized(ip, mac)
        info = portal.context()
        rows = [
            ("Network (SSID)", info.get("ssid", "")),
            ("Band / channel", info.get("radio", "")),
            ("Subnet", info.get("subnet", "")),
            ("Gateway", portal.gateway),
            ("DHCP range", info.get("dhcp_range", "")),
            ("Your IP address", ip),
            ("Your MAC address", mac or "unknown"),
            ("Internet access", info.get("internet", "")),
            ("Network expires", info.get("expires", "")),
        ]
        table = "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>" for label, value in rows
        )
        if authorized:
            state = '<p class="ok">You are signed in. This device is no longer redirected to the portal.</p>'
            action = ""
        else:
            state = '<p class="wait">Sign in to use this network.</p>'
            action = '<form method="post" action="/login"><button type="submit">Sign in</button></form>'
        message = f'<p class="error">{html.escape(error)}</p>' if error else ""
        body = (
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>WiLab Captive Portal</title><style>{_PAGE_STYLE}</style></head><body><main>"
            f"<h1>WiLab Captive Portal</h1>{state}{message}<table>{table}</table>{action}"
            "<footer>Simulated sign-in for Wi-Lab tests. No credentials are collected.</footer>"
            "</main></body></html>"
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
