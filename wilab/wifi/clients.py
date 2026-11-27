"""The clients of a running network: associated stations with a DHCP lease (ARCH-1)."""

import logging
import os
import time

from ..devices import DeviceRegistry
from ..models import ClientInfo
from ..network.captive import CaptivePortal
from ..network.commands import CommandError, execute_ip, execute_iw
from ..network.dhcp import DhcpServer

logger = logging.getLogger(__name__)

CLIENTS_CACHE_SECONDS = 1.5   # reuse of the client list between two reads (PERF-2)


class ClientLister:
    """Lists clients from `iw station dump` and the dnsmasq lease file.

    *captive_portals* is the manager's own dict of running portals, read on
    each call for the clients' sign-in state.
    """

    def __init__(
        self, devices: DeviceRegistry, dhcp_server: DhcpServer, captive_portals: dict[str, CaptivePortal],
    ) -> None:
        self._devices = devices
        self._dhcp_server = dhcp_server
        self._captive_portals = captive_portals
        # Client list per device, reused for CLIENTS_CACHE_SECONDS (PERF-2): clients
        # polling GET .../network every second cost one `iw station dump` at most.
        self._cache: dict[str, tuple[float, list[ClientInfo]]] = {}

    def connected(self, device_id: str) -> list[ClientInfo]:
        """
        List currently connected WiFi clients using real-time data from iw station dump.
        Optionally enriches with IP from DHCP lease file if available.

        Args:
            device_id: Device identifier (interface name)

        Returns:
            List of ClientInfo objects (MAC and IP address if known)
        """
        cached = self._cache.get(device_id)
        if cached is not None and time.monotonic() - cached[0] < CLIENTS_CACHE_SECONDS:
            return list(cached[1])
        clients = self._read(device_id)
        self._cache[device_id] = (time.monotonic(), clients)
        return list(clients)

    def forget(self, device_id: str) -> None:
        """Drop the cached list of a stopped network."""
        self._cache.pop(device_id, None)

    def _read(self, device_id: str) -> list[ClientInfo]:
        clients: list[ClientInfo] = []

        # Get interface for this network
        cfg_net = self._devices.get(device_id)
        if not cfg_net:
            return clients

        interface = cfg_net.interface

        # Get currently associated stations using iw (real-time)
        try:
            station_output = execute_iw(["dev", interface, "station", "dump"])
        except Exception as e:
            logger.warning("Could not get station dump for %s: %s", interface, e)
            return clients

        # Parse iw station dump output to extract MAC addresses
        # Format: "Station xx:xx:xx:xx:xx:xx (on wlanX)" followed by stats
        connected_macs = []
        for line in station_output.splitlines():
            line = line.strip()
            if line.startswith("Station "):
                parts = line.split()
                if len(parts) >= 2:
                    mac = parts[1].lower()
                    connected_macs.append(mac)

        if not connected_macs:
            return clients

        mac_to_ip = self.leases(device_id)
        portal = self._captive_portals.get(device_id)

        # Build client list: only include clients with BOTH WiFi association AND valid DHCP lease
        for mac in connected_macs:
            client_ip = mac_to_ip.get(mac)
            if client_ip:  # Only count as connected if they have a valid IP lease
                clients.append(ClientInfo(
                    mac=mac, ip=client_ip,
                    captive_authorized=portal.is_authorized(client_ip, mac) if portal else None,
                ))

        return clients

    def leases(self, device_id: str) -> dict[str, str]:
        """Return MAC -> IP for unexpired DHCP leases of a network."""
        mac_to_ip: dict[str, str] = {}
        now = int(time.time())
        dhcp_info = self._dhcp_server.get_subnet_info(device_id)
        lease_file = dhcp_info.get("lease_file") if dhcp_info else None
        if lease_file and os.path.exists(lease_file):
            try:
                with open(lease_file) as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 3 and parts[0].isdigit() and int(parts[0]) > now:
                            mac_to_ip[parts[1].lower()] = parts[2]
            except OSError as e:
                logger.warning("Could not read lease file: %s", e)
        return mac_to_ip

    def mac_of(self, device_id: str, ip: str) -> str | None:
        """Identify a client by IP from its DHCP lease, else from the neighbour table."""
        mac = next((mac for mac, lease_ip in self.leases(device_id).items() if lease_ip == ip), None)
        if mac is not None:
            return mac
        try:
            neighbour = execute_ip(["neigh", "show", ip, "dev", device_id]).split()
        except CommandError:
            return None
        return neighbour[neighbour.index("lladdr") + 1] if "lladdr" in neighbour[:-1] else None
