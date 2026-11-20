import time
import logging
import os
from typing import Dict, Optional, List
from ipaddress import IPv4Network
from itertools import islice
import re
import threading
import secrets
from collections.abc import Callable
from _thread import RLock
from ..config import AppConfig
from ..models import NetworkCreateRequest, NetworkStatus, ClientInfo, NetworkTxPower
from ..timestamps import format_utc_timestamp
from ..network.dhcp import DhcpServer, DhcpServerError
from ..network.nat import NatManager
from ..network.isolation import IsolationManager
from ..network.subnet import host_ipv4_networks
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from .hostapd import HostapdManager, HostapdError, HostapdRadioFailure, HostapdSegfault
from .recovery import RadioRecovery
from .watchdog import NetworkWatchdog
from ..reservation import Reservation, ReservationManager
from .channels import ChannelManager
from .interface import validate_interface_exists, validate_interface_wireless, validate_interface_ap_mode, InterfaceError
from ..network.commands import (
    CommandError, command_deadline, execute_command, execute_ip, execute_iw,
)

logger = logging.getLogger(__name__)

STARTUP_RETRY_BUDGET = 5.0
STARTUP_RETRY_DELAY = 0.75
MIN_RETRY_ATTEMPT_TIME = 0.75


class TxPowerMismatchError(Exception):
    """Raised when reported TX power does not match the requested level."""


class StartupFailure(ValueError):
    def __init__(self, message: str, *, radio: bool = False, cleanup_failed: bool = False):
        super().__init__(message)
        self.radio = radio
        self.cleanup_failed = cleanup_failed


class NetworkManager:
    """Manages WiFi AP network lifecycle including DHCP, NAT, and isolation."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.active: Dict[str, NetworkStatus] = {}
        self.dhcp_server = DhcpServer()
        self.nat_manager = NatManager(upstream_interface=config.upstream_interface)
        self.hostapd_manager = HostapdManager()
        self.isolation_manager = IsolationManager()
        self._channel_manager = ChannelManager(allow_dfs_channels=config.allow_dfs_channels)
        self.qos_manager: QosManager | None = None
        self.qos_profile_manager: QosProfileManager | None = None
        self._device_locks = {n.device_id: threading.RLock() for n in config.networks}
        self._device_locks_guard = threading.Lock()
        self._firewall_lock = threading.Lock()
        self._subnet_lock = threading.Lock()
        self._assigned_subnets: dict[str, IPv4Network] = {}
        self.expire_reservations: Callable[[], None] | None = None
        self.recovery = RadioRecovery(self)
        self.watchdog = NetworkWatchdog(self)
        # Background expiry checker to auto-stop networks at timeout
        self._expiry_thread = threading.Thread(target=self._expiry_loop, daemon=True)
        self._expiry_thread.start()
        logger.info("NetworkManager initialized")

    def _configure_networkmanager_unmanaged(self, interface: str) -> None:
        """Best-effort: ask NetworkManager to stop managing AP interface."""
        try:
            execute_command(["nmcli", "--version"])
        except CommandError:
            logger.debug("nmcli not available, skipping NetworkManager unmanaged setup")
            return

        try:
            execute_command(["nmcli", "device", "set", interface, "managed", "no"])
            # Drop any active NM connection on the device to release control quickly.
            execute_command(["nmcli", "device", "disconnect", interface], check=False)
            time.sleep(0.2)
            logger.info(f"Configured {interface} as unmanaged in NetworkManager")
        except CommandError as e:
            logger.warning(f"Could not configure NetworkManager unmanaged for {interface}: {e}")

    def _get_subnet(self, device_id: str) -> str:
        """Allocate or reuse a non-overlapping /24 before a new AP start."""
        devices = [n.device_id for n in self.config.networks]
        if device_id not in devices:
            raise ValueError("Unknown device_id")

        base_net = IPv4Network(self.config.dhcp_base_network, strict=False)
        if base_net.prefixlen != 24:
            raise ValueError("dhcp_base_network must be a /24 network")

        with self._subnet_lock:
            host_networks = host_ipv4_networks()
            previous = self._assigned_subnets.get(device_id)
            if previous is not None and not any(previous.overlaps(route) for route in host_networks):
                return str(previous)

            assigned = set(self._assigned_subnets.values())
            candidates = (
                subnet for subnet in base_net.supernet(new_prefix=16).subnets(new_prefix=24)
                if subnet >= base_net and subnet not in assigned
                and not any(subnet.overlaps(route) for route in host_networks)
            )
            # Preserve pool order even when a later antenna starts first.
            earlier_unassigned = sum(
                device not in self._assigned_subnets for device in devices[:devices.index(device_id)]
            )
            subnet = next(islice(candidates, earlier_unassigned, None), None)
            if subnet is None:
                raise ValueError(f"No available /24 AP subnet for {device_id} from {base_net}")
            self._assigned_subnets[device_id] = subnet
            return str(subnet)

    def device_lock(self, device_id: str) -> RLock:
        """Serialize lifecycle operations only for this device."""
        with self._device_locks_guard:
            lock = self._device_locks.get(device_id)
            if lock is None:
                lock = self._device_locks[device_id] = threading.RLock()
            return lock

    def release_device(self, device_id: str) -> None:
        """Stop all tracked resources before a device can be reassigned."""
        with self.device_lock(device_id):
            with self._firewall_lock:
                firewall_pending = self.nat_manager.has_pending_network(device_id)
            if (
                device_id in self.active
                or device_id in self.hostapd_manager._instances
                or device_id in self.dhcp_server.list_active()
                or firewall_pending
            ):
                self.stop_network(device_id)
            if device_id in self.active:
                raise RuntimeError(f"Network {device_id} is still active")

    def start_network(
        self, device_id: str, req: NetworkCreateRequest,
        expires_at_timestamp: float | None = None, *, allow_internal_retry: bool = True,
    ) -> NetworkStatus:
        with self.device_lock(device_id):
            return self._start_network(device_id, req, expires_at_timestamp, allow_internal_retry)

    def quarantine_radio(
        self, reservations: ReservationManager, reservation: Reservation, *, radio_fault: bool,
        band: str, channel: int,
    ) -> None:
        device = reservation.device_id
        port = next(n.usb_recovery_port for n in self.config.networks if n.device_id == device)
        if not radio_fault or self.config.upstream_interface == device:
            port = None
        reservations.quarantine(reservation, recovering=port is not None)
        if port is not None:
            try:
                self.recovery.schedule(reservations, device, port, band, channel)
            except RuntimeError:
                reservations.finish_recovery(device, recovered=False)
                logger.exception("Could not schedule USB recovery for %s", device)

    def probe_recovered_radio(self, device: str, band: str, channel: int) -> None:
        """Verify AP and DHCP startup without publishing a user network or enabling NAT."""
        subnet = self._get_subnet(device)
        net = IPv4Network(subnet)
        try:
            self.hostapd_manager.start(
                net_id=device, interface=device, ssid=f"wilab-check-{secrets.token_hex(4)}",
                channel=channel, encryption="wpa2", password=secrets.token_hex(24),
                hidden=True, band=band, country_code=self.config.country_code,
            )
            execute_ip(["addr", "add", f"{net[1]}/{net.prefixlen}", "dev", device])
            self.dhcp_server.start(device, device, subnet, self.config.dns_server, probe=True)
            if not self.hostapd_manager.is_enabled(device) or not self.dhcp_server.is_running(device):
                raise CommandError("Recovery AP or DHCP process is not ready")
        except (HostapdError, DhcpServerError) as exc:
            raise CommandError("Recovery AP/DHCP probe failed") from exc
        finally:
            self.release_device(device)

    def _start_network(
        self, device_id: str, req: NetworkCreateRequest,
        expires_at_timestamp: float | None, allow_internal_retry: bool,
    ) -> NetworkStatus:
        """
        Start an AP network with DHCP server.
        
        Args:
            device_id: Device identifier (interface name)
            req: Network creation parameters (SSID, channel, encryption, etc.)
            expires_at_timestamp: Expiration epoch (from reservation). None for unlimited reservations.
            
        Returns:
            NetworkStatus with active network details
        """
        retry_deadline = time.monotonic() + STARTUP_RETRY_BUDGET
        if expires_at_timestamp is not None:
            retry_deadline = min(
                retry_deadline,
                time.monotonic() + (expires_at_timestamp - time.time()),
            )
        logger.info(f"Starting network {device_id} with SSID '{req.ssid}'")
        
        # Validate device_id exists in config
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        if not cfg_net:
            raise ValueError("Unknown device_id")
        
        # Check if network is already active (check both self.active and hostapd)
        if device_id in self.active:
            raise ValueError(f"Network {device_id} is already active. Stop it first before creating a new one.")
        
        # Clear any tracked resources left by a failed startup before retrying.
        try:
            self.release_device(device_id)
        except RuntimeError as e:
            raise StartupFailure(f"Failed to clean up previous startup: {e}", cleanup_failed=True) from e
        
        expires_at_str = format_utc_timestamp(expires_at_timestamp)
        
        # Select a safe subnet before configuring the AP or gateway.
        subnet = self._get_subnet(device_id)
        net = IPv4Network(subnet)
        gateway = f"{net[1]}/{net.prefixlen}"
        
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

        # Best-effort: prevent NetworkManager/wpa_supplicant from contending AP interface.
        self._configure_networkmanager_unmanaged(cfg_net.interface)
        
        for retrying in (False, True):
            stage = "start AP"
            try:
                with command_deadline(retry_deadline if retrying else None):
                    if not internet_enabled:
                        stage = "block Internet"
                        try:
                            with self._firewall_lock:
                                self.nat_manager.block_internet(cfg_net.interface, device_id)
                        except RuntimeError as exc:
                            raise CommandError(str(exc)) from exc
                    stage = "start AP"
                    self.hostapd_manager.start(
                        net_id=device_id,
                        interface=cfg_net.interface,
                        ssid=req.ssid,
                        channel=req.channel,
                        encryption=req.encryption,
                        password=req.password,
                        hidden=req.hidden,
                        band=req.band,
                        country_code=self.config.country_code,
                    )
                    stage = "assign gateway IP"
                    execute_ip(["addr", "add", gateway, "dev", cfg_net.interface])
                    logger.info("Gateway IP %s assigned to %s", gateway, cfg_net.interface)
                    stage = "configure DHCP"
                    self.dhcp_server.start(
                        net_id=device_id,
                        interface=cfg_net.interface,
                        subnet=subnet,
                        dns_server=self.config.dns_server,
                    )
                    if retrying and (
                        time.monotonic() >= retry_deadline
                        or (expires_at_timestamp is not None and time.time() >= expires_at_timestamp)
                    ):
                        stage = "complete startup retry"
                        raise CommandError("Startup retry deadline expired")
            except (HostapdError, CommandError, DhcpServerError) as e:
                logger.error("Failed to %s for %s: %s", stage, device_id, e)
                try:
                    self.release_device(device_id)
                except RuntimeError:
                    logger.exception("Startup rollback failed for %s", device_id)
                    raise StartupFailure(
                        f"Failed to {stage}: {e}",
                        radio=isinstance(e, HostapdRadioFailure) or (retrying and stage == "start AP"),
                        cleanup_failed=True,
                    ) from e

                if (
                    not retrying
                    and allow_internal_retry
                    and req.band == "2.4ghz"
                    and isinstance(e, HostapdSegfault)
                    and retry_deadline - time.monotonic()
                    >= STARTUP_RETRY_DELAY + MIN_RETRY_ATTEMPT_TIME
                ):
                    time.sleep(STARTUP_RETRY_DELAY)
                    if (
                        retry_deadline - time.monotonic() >= MIN_RETRY_ATTEMPT_TIME
                        and (expires_at_timestamp is None or time.time() < expires_at_timestamp)
                    ):
                        logger.info("Retrying AP startup once after segfault on %s", device_id)
                        continue
                raise StartupFailure(
                    f"Failed to {stage}: {e}",
                    radio=isinstance(e, HostapdRadioFailure) or (retrying and stage == "start AP"),
                ) from e
            else:
                if retrying:
                    logger.info("AP startup retry recovered %s", device_id)
                break

        # Apply TX power level from request
        tx_power_level = req.tx_power_level
        try:
            self._set_tx_power(cfg_net.interface, tx_power_level, req.channel)
            runtime_dbm = self._read_current_txpower(cfg_net.interface)
            logger.info(f"TX power set for {device_id}: requested level {tx_power_level}, runtime reported {runtime_dbm} dBm")
        except Exception as e:
            logger.warning(f"Failed to set TX power for {device_id}: {e}")
        
        # Create status object
        expires_in = int(expires_at_timestamp - time.time()) if expires_at_timestamp is not None else None
        status = NetworkStatus(
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
        object.__setattr__(status, '_expires_at_timestamp', expires_at_timestamp)  # type: ignore[attr-defined]
        
        # Enable NAT if internet access is enabled
        if internet_enabled:
            try:
                with self._firewall_lock:
                    self.nat_manager.enable_nat(cfg_net.interface, device_id, subnet)
                logger.info(f"NAT enabled for {device_id}")
            except Exception as e:
                logger.error(f"Failed to enable NAT for {device_id}: {e}")
                # Don't fail network creation if NAT fails, just log
        
        # Apply isolation rules to prevent inter-network traffic
        try:
            with self._firewall_lock:
                self.isolation_manager.add_network(subnet)
            logger.info(f"Isolation rules applied for {device_id} ({subnet})")
        except Exception as e:
            logger.error(f"Failed to apply isolation rules for {device_id}: {e}")
        #     # Don't fail network creation if isolation fails
        logger.info(f"Isolation disabled for testing (network {device_id})")
        
        self.active[device_id] = status
        logger.info(f"Network {device_id} started successfully (expires at {expires_at_str})")
        
        return status

    def stop_network(self, device_id: str) -> None:
        with self.device_lock(device_id):
            self._stop_network(device_id)

    def _stop_network(self, device_id: str) -> None:
        """
        Stop an AP network and clean up DHCP and NAT.
        
        Args:
            device_id: Device identifier (interface name)
        """
        logger.info(f"Stopping network {device_id}")
        errors: list[str] = []
        
        # Get interface and subnet before removing from active dict
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        subnet = self.active[device_id].subnet if device_id in self.active else None
        
        # Clear QoS rules before tearing down the network
        if cfg_net and self.qos_manager is not None:
            try:
                if self.qos_profile_manager is not None:
                    self.qos_profile_manager.stop_profile(cfg_net.interface, self.qos_manager)
                self.qos_manager.clear_qos(cfg_net.interface)
            except Exception as e:
                logger.error(f"Error clearing QoS rules: {e}")
                errors.append(f"QoS: {e}")

        # Stop hostapd
        hostapd_stopped = False
        try:
            self.hostapd_manager.stop(device_id)
            hostapd_stopped = True
        except Exception as e:
            logger.error(f"Error stopping hostapd: {e}")
            errors.append(f"hostapd: {e}")
        
        # Disable NAT if it was enabled
        if cfg_net and hostapd_stopped:
            try:
                with self._firewall_lock:
                    self.nat_manager.release_network(cfg_net.interface, device_id)
            except Exception as e:
                logger.error(f"Error disabling NAT: {e}")
                errors.append(f"NAT: {e}")
        
        # Remove isolation rules
        if subnet:
            try:
                with self._firewall_lock:
                    self.isolation_manager.remove_network(subnet)
                logger.info(f"Isolation rules removed for {device_id} ({subnet})")
            except Exception as e:
                logger.error(f"Error removing isolation rules: {e}")
                errors.append(f"isolation: {e}")
        
        # Stop DHCP server
        try:
            self.dhcp_server.stop(device_id)
        except Exception as e:
            logger.error(f"Error stopping DHCP server: {e}")
            errors.append(f"DHCP: {e}")

        if errors:
            raise RuntimeError(f"Failed to stop network {device_id}: {'; '.join(errors)}")
        
        # Remove from active dict
        self.active.pop(device_id, None)
        
        logger.info(f"Network {device_id} stopped")

    def get_status(self, device_id: str) -> Optional[NetworkStatus]:
        with self.device_lock(device_id):
            return self._get_status(device_id)

    def _get_status(self, device_id: str) -> NetworkStatus | None:
        """
        Get current status of a network.
        Auto-expires networks past their timeout.
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            NetworkStatus object or None if unknown device_id
        """
        st = self.active.get(device_id)
        if not st:
            # Return inactive status if known device_id
            cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
            if not cfg_net:
                return None
            return NetworkStatus(interface=cfg_net.interface, active=False)
        
        # Check if network has expired (use internal timestamp)
        if hasattr(st, '_expires_at_timestamp') and st._expires_at_timestamp is not None and st._expires_at_timestamp < time.time():
            logger.info(f"Network {device_id} expired, stopping")
            self.stop_network(device_id)
            cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
            if not cfg_net:
                return None
            return NetworkStatus(interface=cfg_net.interface, active=False)
        if hasattr(st, '_expires_at_timestamp') and st._expires_at_timestamp is not None:
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        
        # Add DHCP info and clients if active
        if st.active:
            dhcp_info = self.dhcp_server.get_subnet_info(device_id)
            clients = self.list_clients(device_id)
            st.dhcp = dhcp_info if dhcp_info else {}
            st.clients = clients
            st.clients_connected = len(clients)

            if st.tx_power_level is not None:
                reported_level: int | None = None
                reported_dbm: float | None = None
                if st.channel is not None:
                    try:
                        caps = self._get_channel_capabilities(st.interface, st.channel)
                        levels_dbm = self._compute_level_dbm(caps["max_dbm"])
                        reported_dbm = self._read_current_txpower(st.interface)
                        if reported_dbm is not None:
                            reported_level = min(
                                levels_dbm,
                                key=lambda lvl: abs(levels_dbm[lvl] - reported_dbm),  # type: ignore[operator]
                            )
                    except Exception as exc:
                        logger.warning(f"Failed to build tx_power status for {device_id}: {exc}")

                st.tx_power = NetworkTxPower(
                    requested_level=st.tx_power_level,
                    reported_level=reported_level,
                    reported_dbm=reported_dbm,
                )
        
        return st

    def get_summary(self, device_id: str) -> Optional[dict]:
        """Backward-compatible summary view for a network."""
        st = self.get_status(device_id)
        if st is None:
            return None

        clients = st.clients or []
        return {
            "interface": st.interface,
            "active": st.active,
            "dhcp": st.dhcp or {},
            "clients_connected": st.clients_connected if st.clients_connected is not None else len(clients),
            "clients": [c.model_dump() if hasattr(c, "model_dump") else c for c in clients],
        }

    def enable_internet(self, device_id: str) -> NetworkStatus:
        """
        Enable Internet access for a network (NAT forwarding).
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            Updated NetworkStatus
        """
        logger.info(f"Enabling Internet for network {device_id}")
        
        st = self.get_status(device_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive device_id")
        
        # Get interface for NAT rules
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        if not cfg_net:
            raise ValueError("Unknown device_id")
        
        # Enable NAT if not already enabled
        if not st.internet_enabled:
            try:
                with self._firewall_lock:
                    self.nat_manager.enable_nat(cfg_net.interface, device_id, st.subnet or self._get_subnet(device_id))
                logger.info(f"NAT rules applied for {device_id}")
            except Exception as e:
                logger.error(f"Failed to enable NAT: {e}")
                raise RuntimeError(f"Cannot enable Internet: {e}") from e
        
        st.internet_enabled = True
        if hasattr(st, '_expires_at_timestamp') and st._expires_at_timestamp is not None:
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        self.active[device_id] = st
        logger.info(f"Internet enabled for {device_id}")
        
        return st

    def disable_internet(self, device_id: str) -> NetworkStatus:
        """
        Disable Internet access for a network (block NAT forwarding).
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            Updated NetworkStatus
        """
        logger.info(f"Disabling Internet for network {device_id}")
        
        st = self.get_status(device_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive device_id")
        
        # Get interface for NAT rules
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        if not cfg_net:
            raise ValueError("Unknown device_id")
        
        # Disable NAT if currently enabled
        if st.internet_enabled:
            try:
                with self._firewall_lock:
                    self.nat_manager.disable_nat(cfg_net.interface, device_id, st.subnet or self._get_subnet(device_id))
                logger.info(f"NAT rules removed for {device_id}")
            except Exception as e:
                logger.error(f"Failed to disable NAT: {e}")
                raise RuntimeError(f"Cannot disable Internet: {e}") from e
        
        st.internet_enabled = False
        if hasattr(st, '_expires_at_timestamp') and st._expires_at_timestamp is not None:
            st.expires_in = max(0, int(st._expires_at_timestamp - time.time()))
        self.active[device_id] = st
        logger.info(f"Internet disabled for {device_id}")
        
        return st

    def list_clients(self, device_id: str) -> List[ClientInfo]:
        """
        List currently connected WiFi clients using real-time data from iw station dump.
        Optionally enriches with IP from DHCP lease file if available.
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            List of ClientInfo objects (MAC and IP address if known)
        """
        clients: list[ClientInfo] = []
        
        # Get interface for this network
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
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
        dhcp_info = self.dhcp_server.get_subnet_info(device_id)
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
            client_ip = mac_to_ip.get(mac)
            if client_ip:  # Only count as connected if they have a valid IP lease
                clients.append(ClientInfo(mac=mac, ip=client_ip))
        
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
        self.recovery.stop()
        self.watchdog.stopping.set()
        logger.info("Shutting down all networks")
        device_ids = {n.device_id for n in self.config.networks} | self.active.keys()
        for device_id in device_ids:
            try:
                self.release_device(device_id)
            except Exception as e:
                logger.error(f"Error stopping {device_id}: {e}")
        logger.info("All networks shut down")

    # ---- TX power management ----

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
        info = self._channel_manager.get_channels(interface)
        for ch in info.channels_24ghz + info.channels_5ghz:
            if ch.channel == channel:
                return {"frequency_mhz": ch.frequency_mhz, "max_dbm": ch.max_power_dbm}
        raise ValueError(f"Channel {channel} not supported on interface {interface}")

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

    def _reported_level_from_dbm(self, levels_dbm: Dict[int, float], reported_dbm: Optional[float]) -> Optional[int]:
        if reported_dbm is None:
            return None
        return min(levels_dbm, key=lambda lvl: abs(levels_dbm[lvl] - reported_dbm))

    def _set_tx_power(self, interface: str, level: int, channel: int, verify_change: bool = False) -> dict:
        """
        Set TX power for interface.
        
        Args:
            interface: WiFi interface
            level: Power level 1-4
            channel: WiFi channel
            verify_change: If True, wait 3s and verify power actually changed
            
        Returns:
            Dict with tx power info
        """
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        caps = self._get_channel_capabilities(interface, channel)
        levels_dbm = self._compute_level_dbm(caps["max_dbm"])
        desired_dbm = levels_dbm[level]
        desired_mbm = int(round(desired_dbm * 100))
        
        try:
            execute_iw(["dev", interface, "set", "txpower", "fixed", str(desired_mbm)])
        except CommandError as e:
            raise ValueError(f"Failed to set txpower: {e}") from e

        power_after = None
        if verify_change:
            # Wait for driver to apply change
            time.sleep(3)
            power_after = self._read_current_txpower(interface)

            # Compare requested vs reported directly.
            if power_after is not None and abs(power_after - desired_dbm) > 0.5:
                logger.warning(
                    f"{interface}: TX power mismatch (requested={desired_dbm}, reported={power_after})"
                )
                raise TxPowerMismatchError("Interface does not support dynamic power change.")
        
        result = {
            "interface": interface,
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "tx_power": {
                "requested_level": level,
                "reported_level": self._reported_level_from_dbm(levels_dbm, power_after),
                "reported_dbm": power_after,
            },
        }
        return result

    def set_tx_power_level(self, device_id: str, level: int) -> dict:
        """
        Change TX power level for active network.
        Verifies if change was applied and warns if interface doesn't support dynamic changes.
        """
        st = self.get_status(device_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive device_id")
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        if not cfg_net:
            raise ValueError("Unknown device_id")
        
        # Set power with verification (waits 3s and checks if change applied)
        info = self._set_tx_power(cfg_net.interface, level, st.channel, verify_change=True)
        st.tx_power_level = level
        self.active[device_id] = st
        return info

    def get_tx_power_info(self, device_id: str) -> dict:
        """
        Get current TX power info for network.
        Compares configured level with actual interface power and warns if mismatch.
        """
        st = self.get_status(device_id)
        if not st or not st.active:
            raise ValueError("Unknown or inactive device_id")
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = next((n for n in self.config.networks if n.device_id == device_id), None)
        if not cfg_net:
            raise ValueError("Unknown device_id")
        
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
        
        # Keep mismatch as server-side observability; GET payload no longer exposes warning.
        if reported_dbm is not None and abs(reported_dbm - expected_dbm) > 0.5:
            logger.info(f"{device_id}: Power mismatch - expected {expected_dbm} dBm, reported {reported_dbm} dBm")
        
        result = {
            "interface": cfg_net.interface,
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "tx_power": {
                "requested_level": level,
                "reported_level": self._reported_level_from_dbm(levels_dbm, reported_dbm),
                "reported_dbm": reported_dbm,
            },
        }
        return result

    def _expiry_loop(self) -> None:
        """Background loop to auto-expire networks without requiring API calls."""
        while not self.watchdog.stopping.wait(5):
            try:
                now = time.time()
                # Copy keys to avoid mutation during iteration
                for device_id, st in self.active.copy().items():
                    self._expire_network(device_id, st, now)
                if self.expire_reservations is not None:
                    self.expire_reservations()
            except Exception as e:
                logger.debug(f"[expiry-loop] Loop error: {e}")

    def _expire_network(self, device_id: str, status: NetworkStatus, now: float) -> None:
        timestamp = getattr(status, '_expires_at_timestamp', None)
        if timestamp is None or timestamp >= now:
            return
        lock = self.device_lock(device_id)
        if not lock.acquire(blocking=False):
            return
        try:
            if self.active.get(device_id) is not status:
                return
            logger.info(f"[expiry-loop] Network {device_id} expired, stopping")
            try:
                self.stop_network(device_id)
            except RuntimeError as e:
                logger.error(f"[expiry-loop] Failed stopping {device_id}: {e}")
        finally:
            lock.release()


