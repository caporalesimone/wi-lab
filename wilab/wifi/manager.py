import time
import logging
import os
from typing import Dict, Optional, List
from ipaddress import IPv4Network
from datetime import datetime
import re
import threading
from ..config import AppConfig
from ..models import NetworkCreateRequest, NetworkStatus, ClientInfo
from ..network.dhcp import DhcpServer, DhcpServerError
from ..network.nat import NatManager
from ..network.isolation import IsolationManager
from .hostapd import HostapdManager, HostapdError
from .interface import validate_interface_exists, validate_interface_wireless, validate_interface_ap_mode, InterfaceError
from ..network.commands import execute_iw, execute_command, CommandError

logger = logging.getLogger(__name__)


class NetworkManager:
    """Manages WiFi AP network lifecycle including DHCP, NAT, and isolation."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.active: Dict[str, NetworkStatus] = {}
        self.dhcp_server = DhcpServer()
        self.nat_manager = NatManager(upstream_interface=config.upstream_interface)
        self.hostapd_manager = HostapdManager()
        self.isolation_manager = IsolationManager()
        self._lock = threading.Lock()
        # Background expiry checker to auto-stop networks at timeout
        self._expiry_thread = threading.Thread(target=self._expiry_loop, daemon=True)
        self._expiry_thread.start()
        logger.info("NetworkManager initialized")

    def _get_subnet(self, net_id: str) -> str:
        """Assign a /24 subnet by incrementing the third octet from dhcp_base_network."""
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")

        base_net = IPv4Network(self.config.dhcp_base_network, strict=False)
        if base_net.prefixlen != 24:
            raise ValueError("dhcp_base_network must be a /24 network")

        try:
            idx = [n.net_id for n in self.config.networks].index(net_id)
        except ValueError as exc:
            raise ValueError("Unknown net_id for subnet allocation") from exc

        octets = str(base_net.network_address).split('.')
        third_octet = int(octets[2]) + idx
        if third_octet > 255:
            raise ValueError(f"Cannot allocate subnet for {net_id}: octet overflow")
        octets[2] = str(third_octet)
        return '.'.join(octets) + '/24'

    def start_network(self, net_id: str, req: NetworkCreateRequest) -> NetworkStatus:
        """
        Start an AP network with DHCP server.
        
        Args:
            net_id: Network identifier
            req: Network creation parameters (SSID, channel, encryption, etc.)
            
        Returns:
            NetworkStatus with active network details
        """
        logger.info(f"Starting network {net_id} with SSID '{req.ssid}'")
        
        # Validate net_id exists in config
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")
        
        # Check if network is already active (check both self.active and hostapd)
        if net_id in self.active:
            raise ValueError(f"Network {net_id} is already active. Stop it first before creating a new one.")
        
        # Also check if hostapd is running (in case network was marked inactive but processes still running)
        if self.hostapd_manager.is_running(net_id):
            logger.warning(f"hostapd is running for {net_id} but network not in active dict, cleaning up")
            self.stop_network(net_id)
        
        # Calculate timeout
        now = time.time()
        timeout = req.timeout or self.config.default_timeout
        
        # Enforce min/max timeout bounds
        if timeout < self.config.min_timeout:
            timeout = self.config.min_timeout
        if timeout > self.config.max_timeout:
            timeout = self.config.max_timeout
        
        expires_at_timestamp = now + timeout
        expires_at_str = datetime.fromtimestamp(expires_at_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        # Get subnet (from config or calculated)
        subnet = self._get_subnet(net_id)
        
        # Validate interface
        logger.info(f"Validating interface {cfg_net.interface}")
        try:
            validate_interface_exists(cfg_net.interface)
            validate_interface_wireless(cfg_net.interface)
            validate_interface_ap_mode(cfg_net.interface)
        except InterfaceError as e:
            logger.error(f"Interface validation failed: {e}")
            raise ValueError(str(e)) from e

        # Determine internet enabled status
        internet_enabled = (
            req.internet_enabled
            if req.internet_enabled is not None
            else self.config.internet_enabled_by_default
        )
        
        # Start DHCP server
        try:
            dhcp_info = self.dhcp_server.start(
                net_id=net_id,
                interface=cfg_net.interface,
                subnet=subnet,
                dns_server=self.config.dns_server
            )
            logger.info(f"DHCP server started: {dhcp_info}")
        except DhcpServerError as e:
            logger.error(f"Failed to start DHCP server: {e}")
            raise ValueError(f"Failed to configure DHCP: {e}") from e
        
        # Start hostapd for AP mode
        try:
            hostapd_info = self.hostapd_manager.start(
                net_id=net_id,
                interface=cfg_net.interface,
                ssid=req.ssid,
                channel=req.channel,
                encryption=req.encryption,
                password=req.password,
                hidden=req.hidden,
                band=req.band
            )
            logger.info(f"hostapd started: {hostapd_info}")
        except HostapdError as e:
            logger.error(f"Failed to start hostapd: {e}")
            # Rollback DHCP
            try:
                self.dhcp_server.stop(net_id)
            except Exception:
                pass
            raise ValueError(f"Failed to start AP: {e}") from e

        # Assign gateway IP (.1) to interface AFTER hostapd starts (hostapd resets the interface)
        # subnet is e.g. "192.168.120.0/24", gateway must be .1
        from ipaddress import IPv4Network as IPv4Net
        from ..network.commands import execute_ip, CommandError
        net = IPv4Net(subnet, strict=False)
        gateway_ip = str(net.network_address + 1)  # .1 of the subnet
        try:
            # Check if IP is already present
            ip_addr_output = execute_ip(["addr", "show", cfg_net.interface])
            if gateway_ip not in ip_addr_output:
                logger.info(f"Assigning gateway IP {gateway_ip}/24 to interface {cfg_net.interface}")
                execute_ip(["addr", "add", f"{gateway_ip}/24", "dev", cfg_net.interface])
                logger.info(f"Gateway IP {gateway_ip}/24 assigned to {cfg_net.interface}")
            else:
                logger.info(f"Gateway IP {gateway_ip}/24 already present on {cfg_net.interface}")
        except CommandError as e:
            logger.error(f"Failed to assign gateway IP: {e}")
            # Rollback hostapd and DHCP
            try:
                self.hostapd_manager.stop(net_id)
                self.dhcp_server.stop(net_id)
            except Exception:
                pass
            raise ValueError(f"Failed to assign gateway IP: {e}")

        # Apply TX power level from request
        tx_power_level = req.tx_power_level
        try:
            tx_info = self._set_tx_power(cfg_net.interface, tx_power_level, req.channel)
            logger.info(f"TX power set for {net_id}: level {tx_power_level} -> {tx_info.get('current_dbm')} dBm")
        except Exception as e:
            tx_info = None
            logger.warning(f"Failed to set TX power for {net_id}: {e}")
        
        # Create status object
        expires_in = int(expires_at_timestamp - time.time())
        status = NetworkStatus(
            net_id=net_id,
            interface=cfg_net.interface,
            active=True,
            ssid=req.ssid,
            channel=req.channel,
            password=req.password,
            encryption=req.encryption,
            band=req.band,
            hidden=req.hidden,
            subnet=subnet,
            internet_enabled=internet_enabled,
            tx_power_level=tx_power_level,
            expires_at=expires_at_str,
            expires_in=expires_in,
        )
        # Store internal timestamp for expiration checking
        status._expires_at_timestamp = expires_at_timestamp
        
        self.active[net_id] = status
        
        # Enable NAT if internet access is enabled
        if internet_enabled:
            try:
                self.nat_manager.enable_nat(cfg_net.interface, net_id)
                logger.info(f"NAT enabled for {net_id}")
            except Exception as e:
                logger.error(f"Failed to enable NAT for {net_id}: {e}")
                # Don't fail network creation if NAT fails, just log
        
        # Apply isolation rules to prevent inter-network traffic
        try:
            self.isolation_manager.add_network(subnet)
            logger.info(f"Isolation rules applied for {net_id} ({subnet})")
        except Exception as e:
            logger.error(f"Failed to apply isolation rules for {net_id}: {e}")
        #     # Don't fail network creation if isolation fails
        logger.info(f"Isolation disabled for testing (network {net_id})")
        
        logger.info(f"Network {net_id} started successfully (expires at {expires_at_str})")
        
        return status

    def stop_network(self, net_id: str) -> None:
        """
        Stop an AP network and clean up DHCP and NAT.
        
        Args:
            net_id: Network identifier
        """
        logger.info(f"Stopping network {net_id}")
        
        # Get interface and subnet before removing from active dict
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        subnet = self.active[net_id].subnet if net_id in self.active else None
        
        # Stop hostapd
        try:
            self.hostapd_manager.stop(net_id)
        except Exception as e:
            logger.error(f"Error stopping hostapd: {e}")
        
        # Disable NAT if it was enabled
        if net_id in self.active and self.active[net_id].internet_enabled and cfg_net:
            try:
                self.nat_manager.disable_nat(cfg_net.interface, net_id)
            except Exception as e:
                logger.error(f"Error disabling NAT: {e}")
        
        # Remove isolation rules
        if subnet:
            try:
                self.isolation_manager.remove_network(subnet)
                logger.info(f"Isolation rules removed for {net_id} ({subnet})")
            except Exception as e:
                logger.error(f"Error removing isolation rules: {e}")
        
        # Stop DHCP server
        try:
            self.dhcp_server.stop(net_id)
        except Exception as e:
            logger.error(f"Error stopping DHCP server: {e}")
        
        # Remove from active dict
        if net_id in self.active:
            with self._lock:
                if net_id in self.active:
                    del self.active[net_id]
        
        logger.info(f"Network {net_id} stopped")

    def get_status(self, net_id: str) -> Optional[NetworkStatus]:
        """
        Get current status of a network.
        Auto-expires networks past their timeout.
        
        Args:
            net_id: Network identifier
            
        Returns:
            NetworkStatus object or None if unknown net_id
        """
        st = self.active.get(net_id)
        if not st:
            # Return inactive status if known net_id
            cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
            if not cfg_net:
                return None
            return NetworkStatus(net_id=net_id, interface=cfg_net.interface, active=False)
        
        # Check if network has expired (use internal timestamp)
        if hasattr(st, '_expires_at_timestamp') and st._expires_at_timestamp < time.time():
            logger.info(f"Network {net_id} expired, stopping")
            self.stop_network(net_id)
            cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
            return NetworkStatus(net_id=net_id, interface=cfg_net.interface, active=False)
        
        # Update expires_in dynamically
        if hasattr(st, '_expires_at_timestamp'):
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        
        return st

    def get_summary(self, net_id: str) -> Optional[dict]:
        """Return a compact summary of network state for debugging/monitoring."""
        st = self.get_status(net_id)
        if not st:
            return None
        dhcp_info = self.dhcp_server.get_subnet_info(net_id)
        clients = self.list_clients(net_id)
        return {
            "net_id": st.net_id,
            "interface": st.interface,
            "active": st.active,
            "internet_enabled": st.internet_enabled,
            "expires_at": st.expires_at,
            "ssid": st.ssid,
            "channel": st.channel,
            "encryption": st.encryption,
            "band": st.band,
            "hidden": st.hidden,
            "subnet": st.subnet,
            "dhcp": dhcp_info if dhcp_info else {},
            "clients_connected": len(clients),
            "clients": clients,
        }

    def enable_internet(self, net_id: str) -> NetworkStatus:
        """
        Enable Internet access for a network (NAT forwarding).
        
        Args:
            net_id: Network identifier
            
        Returns:
            Updated NetworkStatus
        """
        logger.info(f"Enabling Internet for network {net_id}")
        
        st = self.get_status(net_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive net_id")
        
        # Get interface for NAT rules
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")
        
        # Enable NAT if not already enabled
        if not st.internet_enabled:
            try:
                self.nat_manager.enable_nat(cfg_net.interface, net_id)
                logger.info(f"NAT rules applied for {net_id}")
            except Exception as e:
                logger.error(f"Failed to enable NAT: {e}")
                raise RuntimeError(f"Cannot enable Internet: {e}") from e
        
        st.internet_enabled = True
        if hasattr(st, '_expires_at_timestamp'):
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        self.active[net_id] = st
        logger.info(f"Internet enabled for {net_id}")
        
        return st

    def disable_internet(self, net_id: str) -> NetworkStatus:
        """
        Disable Internet access for a network (block NAT forwarding).
        
        Args:
            net_id: Network identifier
            
        Returns:
            Updated NetworkStatus
        """
        logger.info(f"Disabling Internet for network {net_id}")
        
        st = self.get_status(net_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive net_id")
        
        # Get interface for NAT rules
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")
        
        # Disable NAT if currently enabled
        if st.internet_enabled:
            try:
                self.nat_manager.disable_nat(cfg_net.interface, net_id)
                logger.info(f"NAT rules removed for {net_id}")
            except Exception as e:
                logger.error(f"Failed to disable NAT: {e}")
                # Continue anyway to update state
        
        st.internet_enabled = False
        if hasattr(st, '_expires_at_timestamp'):
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        self.active[net_id] = st
        logger.info(f"Internet disabled for {net_id}")
        
        return st

    def list_clients(self, net_id: str) -> List[ClientInfo]:
        """
        List currently connected WiFi clients using real-time data from iw station dump.
        Optionally enriches with IP from DHCP lease file if available.
        
        Args:
            net_id: Network identifier
            
        Returns:
            List of ClientInfo objects (MAC and IP address if known)
        """
        clients = []
        
        # Get interface for this network
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            return clients
        
        interface = cfg_net.interface
        
        # Get currently associated stations using iw (real-time)
        try:
            station_output = execute_iw(["dev", interface, "station", "dump"])
        except Exception as e:
            logger.warning(f"Could not get station dump for {interface}: {e}")
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

        # Build MAC -> IP mapping from DHCP lease file (only valid leases)
        mac_to_ip = {}
        now = int(time.time())
        dhcp_info = self.dhcp_server.get_subnet_info(net_id)
        if dhcp_info:
            lease_file = dhcp_info.get('lease_file')
            if lease_file and os.path.exists(lease_file):
                try:
                    with open(lease_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) >= 3:
                                try:
                                    lease_expiry = int(parts[0])
                                except Exception:
                                    continue
                                # Only include valid (non-expired) leases
                                if lease_expiry > now:
                                    mac = parts[1].lower()
                                    ip = parts[2]
                                    mac_to_ip[mac] = ip
                except Exception as e:
                    logger.warning(f"Could not read lease file: {e}")

        # Build client list: only include clients with BOTH WiFi association AND valid DHCP lease
        for mac in connected_macs:
            ip = mac_to_ip.get(mac)
            if ip:  # Only count as connected if they have a valid IP lease
                clients.append(ClientInfo(mac=mac, ip=ip))
        
        return clients

    def services_status(self) -> dict:
        """Return minimal service status (dnsmasq, hostapd, iptables)."""
        return {
            "dnsmasq": self.dhcp_server.status(),
            "hostapd": self.hostapd_manager.status(),
            "iptables": self.nat_manager.status(),
        }
    
    def shutdown_all(self) -> None:
        """Shutdown all active networks."""
        logger.info("Shutting down all networks")
        net_ids = list(self.active.keys())
        for net_id in net_ids:
            try:
                self.stop_network(net_id)
            except Exception as e:
                logger.error(f"Error stopping {net_id}: {e}")
        logger.info("All networks shut down")

    # ---- TX power management ----

    def _get_phy_for_interface(self, interface: str) -> str:
        info = execute_iw([interface, "info"])
        for line in info.splitlines():
            if "wiphy" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    return parts[1]
        raise ValueError(f"Cannot determine wiphy for interface {interface}")
    
    def _read_current_txpower(self, interface: str) -> Optional[float]:
        """Read current TX power from interface in dBm. Returns None if unavailable."""
        try:
            output = execute_iw(["dev", interface, "info"])
            # Look for: txpower 20.00 dBm or txpower 5.00 dBm
            pattern = re.compile(r"txpower\s+([\d.]+)\s+dBm")
            for line in output.splitlines():
                m = pattern.search(line)
                if m:
                    return float(m.group(1))
        except Exception as e:
            logger.warning(f"Failed to read current txpower for {interface}: {e}")
        return None

    def _get_channel_capabilities(self, interface: str, channel: int) -> dict:
        phy = self._get_phy_for_interface(interface)
        output = execute_iw(["phy" + phy, "info"])
        # Pattern: * 2437.0 MHz [6] (20.0 dBm) or * 2437 MHz [6] (20.0 dBm)
        pattern = re.compile(r"\*\s+([\d.]+)\s+MHz\s+\[(\d+)\].*\(([-0-9.]+) dBm\)")
        freq_mhz = None
        max_dbm = None
        for line in output.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            freq = float(m.group(1))
            chan = int(m.group(2))
            dbm = float(m.group(3))
            if chan == channel:
                freq_mhz = int(freq)  # Convert to int for cleaner output
                max_dbm = dbm
                break
        if freq_mhz is None or max_dbm is None:
            raise ValueError(f"Channel {channel} not supported on interface {interface}")
        return {"frequency_mhz": freq_mhz, "max_dbm": max_dbm}

    def _compute_level_dbm(self, max_dbm: float) -> Dict[int, float]:
        # Linearly split max power into four steps
        levels = {
            1: round(max_dbm * 0.25, 1),
            2: round(max_dbm * 0.50, 1),
            3: round(max_dbm * 0.75, 1),
            4: round(max_dbm, 1),
        }
        # Ensure monotonic and at least 1 dBm for lower steps
        levels[1] = max(1.0, levels[1])
        levels[2] = max(levels[1], levels[2])
        levels[3] = max(levels[2], levels[3])
        levels[4] = max(levels[3], levels[4])
        return levels

    def _set_tx_power(self, interface: str, level: int, channel: int, verify_change: bool = False) -> dict:
        """
        Set TX power for interface.
        
        Args:
            interface: WiFi interface
            level: Power level 1-4
            channel: WiFi channel
            verify_change: If True, wait 3s and verify power actually changed
            
        Returns:
            Dict with power info and optional warning if change not supported
        """
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        caps = self._get_channel_capabilities(interface, channel)
        levels_dbm = self._compute_level_dbm(caps["max_dbm"])
        desired_dbm = levels_dbm[level]
        desired_mbm = int(round(desired_dbm * 100))
        
        # Read current power before change (if verifying)
        power_before = None
        if verify_change:
            power_before = self._read_current_txpower(interface)
        
        try:
            execute_iw(["dev", interface, "set", "txpower", "fixed", str(desired_mbm)])
        except CommandError as e:
            raise ValueError(f"Failed to set txpower: {e}") from e
        
        warning = None
        power_after = None
        if verify_change:
            # Wait for driver to apply change
            time.sleep(3)
            power_after = self._read_current_txpower(interface)
            
            # Check if power actually changed (tolerance 0.5 dBm)
            if power_after is not None and power_before is not None:
                if abs(power_after - power_before) < 0.5:
                    warning = "Interface does not support dynamic power change. Please recreate the network with desired power level."
                    logger.warning(f"{interface}: TX power change not applied (before={power_before}, after={power_after})")
        
        result = {
            "interface": interface,
            "channel": channel,
            "frequency_mhz": caps["frequency_mhz"],
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "current_level": level,
            "current_dbm": desired_dbm,
            "reported_dbm": power_after,  # Power reported by interface after change
        }
        if warning:
            result["warning"] = warning
        return result

    def set_tx_power_level(self, net_id: str, level: int) -> dict:
        """
        Change TX power level for active network.
        Verifies if change was applied and warns if interface doesn't support dynamic changes.
        """
        st = self.get_status(net_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive net_id")
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")
        
        # Set power with verification (waits 3s and checks if change applied)
        info = self._set_tx_power(cfg_net.interface, level, st.channel, verify_change=True)
        st.tx_power_level = level
        self.active[net_id] = st
        return {"net_id": net_id, **info}

    def get_tx_power_info(self, net_id: str) -> dict:
        """
        Get current TX power info for network.
        Compares configured level with actual interface power and warns if mismatch.
        """
        st = self.get_status(net_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive net_id")
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = next((n for n in self.config.networks if n.net_id == net_id), None)
        if not cfg_net:
            raise ValueError("Unknown net_id")
        
        # Get configured level
        level = st.tx_power_level
        if level is None:
            raise ValueError("TX power level not set for this network")
        
        # Get channel capabilities and compute levels
        caps = self._get_channel_capabilities(cfg_net.interface, st.channel)
        levels_dbm = self._compute_level_dbm(caps["max_dbm"])
        expected_dbm = levels_dbm[level]
        
        # Read actual current power from interface
        reported_dbm = self._read_current_txpower(cfg_net.interface)
        
        # Check if there's a mismatch (tolerance 0.5 dBm)
        warning = None
        if reported_dbm is not None and abs(reported_dbm - expected_dbm) > 0.5:
            warning = "Interface does not support dynamic power change. Please recreate the network with desired power level."
            logger.info(f"{net_id}: Power mismatch - expected {expected_dbm} dBm, reported {reported_dbm} dBm")
        
        result = {
            "net_id": net_id,
            "interface": cfg_net.interface,
            "channel": st.channel,
            "frequency_mhz": caps["frequency_mhz"],
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "current_level": level,
            "current_dbm": expected_dbm,
            "reported_dbm": reported_dbm,
        }
        if warning:
            result["warning"] = warning
        return result

    def _expiry_loop(self) -> None:
        """Background loop to auto-expire networks without requiring API calls."""
        while True:
            try:
                now = time.time()
                # Copy keys to avoid mutation during iteration
                with self._lock:
                    items = list(self.active.items())
                for net_id, st in items:
                    # Some tests may not set internal timestamp; guard accordingly
                    ts = getattr(st, '_expires_at_timestamp', None)
                    if ts is not None and ts < now:
                        logger.info(f"[expiry-loop] Network {net_id} expired, stopping")
                        try:
                            self.stop_network(net_id)
                        except Exception as e:
                            logger.error(f"[expiry-loop] Failed stopping {net_id}: {e}")
            except Exception as e:
                logger.debug(f"[expiry-loop] Loop error: {e}")
            # Run every 5 seconds
            time.sleep(5)


