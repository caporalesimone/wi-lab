import functools
import logging
import os
import re
import secrets
import shutil
import threading
import time
from _thread import RLock
from collections.abc import Callable
from ipaddress import IPv4Network
from itertools import islice

from .. import heartbeat
from ..config import AppConfig
from ..models import ClientInfo, NetworkCreateRequest, NetworkStatus, NetworkTxPower
from ..network.captive import CaptivePortal, CaptivePortalError
from ..network.commands import (
    CommandError,
    command_deadline,
    execute_command,
    execute_ip,
    execute_iw,
)
from ..network.dhcp import DhcpServer, DhcpServerError
from ..network.host_guard import HostGuard
from ..network.isolation import IsolationManager
from ..network.nat import NatManager
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from ..network.subnet import host_ipv4_networks
from ..reservation import Reservation, ReservationManager
from ..timestamps import format_utc_timestamp
from .channels import ChannelManager
from .hostapd import (
    HostapdError,
    HostapdManager,
    HostapdRadioFailure,
)
from .interface import (
    InterfaceError,
    interface_present,
    validate_interface_exists,
)
from .recovery import RadioRecovery
from .watchdog import NetworkWatchdog

logger = logging.getLogger(__name__)

# Transient radio failures usually clear on an immediate new start, so the
# server retries inside the request instead of handing the retry to the client.
STARTUP_ATTEMPTS = 3
# A retry starts only with at least MIN_RETRY_ATTEMPT_TIME left, so it is a real
# attempt: a start cut short by the budget would count as one more radio
# failure towards quarantine without giving the radio a chance (HAP-4).
STARTUP_RETRY_BUDGET = 20.0
STARTUP_RETRY_DELAY = 1.0
MIN_RETRY_ATTEMPT_TIME = 4.0
# Delay before the next background cleanup of a device whose cleanup failed, by
# number of consecutive failures; the last value repeats (WD-6). A client's
# explicit DELETE is never delayed.
CLEANUP_BACKOFF = (5.0, 15.0, 60.0, 300.0)


@functools.lru_cache(maxsize=1)
def _nmcli_available() -> bool:
    """Whether nmcli is installed; looked up once instead of running it on every start (PERF-1)."""
    return shutil.which("nmcli") is not None


class NetworkNotActive(ValueError):
    """The reservation is valid but it has no running network (API-2)."""

    def __init__(self, device_id: str) -> None:
        super().__init__(f"Network {device_id} is not active")
        self.device_id = device_id


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
        self.active: dict[str, NetworkStatus] = {}
        self.dhcp_server = DhcpServer()
        self.nat_manager = NatManager(upstream_interface=config.upstream_interface)
        self.hostapd_manager = HostapdManager()
        self.isolation_manager = IsolationManager()
        self.host_guard = HostGuard()  # SEC-3: AP clients cannot reach the host
        self.captive_portals: dict[str, CaptivePortal] = {}
        self._channel_manager = ChannelManager(allow_dfs_channels=config.allow_dfs_channels)
        self.qos_manager: QosManager | None = None
        self.qos_profile_manager: QosProfileManager | None = None
        self._device_locks = {n.device_id: threading.RLock() for n in config.networks}
        self._device_locks_guard = threading.Lock()
        self._firewall_lock = threading.Lock()
        self._subnet_lock = threading.Lock()
        self._assigned_subnets: dict[str, IPv4Network] = {}
        # WD-6: consecutive cleanup failures and next background attempt per device
        self._cleanup_failures: dict[str, int] = {}
        self._cleanup_retry_at: dict[str, float] = {}
        self.expire_reservations: Callable[[], None] | None = None
        self.recovery = RadioRecovery(self)
        self.watchdog = NetworkWatchdog(self)
        # Background expiry checker to auto-stop networks at timeout
        self._expiry_thread = threading.Thread(target=self._expiry_loop, daemon=True)
        self._expiry_thread.start()
        logger.info("NetworkManager initialized")

    def _configure_networkmanager_unmanaged(self, interface: str) -> None:
        """Best-effort: ask NetworkManager to stop managing AP interface."""
        if not _nmcli_available():
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
                firewall_pending = (
                    self.nat_manager.has_pending_network(device_id) or self.host_guard.has(device_id)
                )
            if (
                device_id in self.active
                or device_id in self.hostapd_manager._instances
                or device_id in self.dhcp_server.list_active()
                or device_id in self.captive_portals
                or firewall_pending
            ):
                self._tracked_stop(device_id)
            if device_id in self.active:
                raise RuntimeError(f"Network {device_id} is still active")

    def _tracked_stop(self, device_id: str) -> None:
        """stop_network, recording failures for the background backoff (WD-6)."""
        try:
            self.stop_network(device_id)
        except RuntimeError:
            failures = self._cleanup_failures.get(device_id, 0) + 1
            delay = CLEANUP_BACKOFF[min(failures, len(CLEANUP_BACKOFF)) - 1]
            self._cleanup_failures[device_id] = failures
            self._cleanup_retry_at[device_id] = time.monotonic() + delay
            if failures > 1:
                logger.warning(
                    "Cleanup of %s failed %d times in a row; next background attempt in %.0f s",
                    device_id, failures, delay,
                )
            raise
        if self._cleanup_failures.pop(device_id, None) is not None:
            logger.warning("Cleanup of %s succeeded after earlier failures", device_id)
        self._cleanup_retry_at.pop(device_id, None)

    def cleanup_due(self, device_id: str) -> bool:
        """False while a failed cleanup of this device waits for its next background attempt."""
        return time.monotonic() >= self._cleanup_retry_at.get(device_id, 0.0)

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
        self.recovery.remember_radio(device, band, channel)
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
            # Wireless and AP capability were established by discovery and cannot change
            # for this interface; only its presence can (PERF-1, BUG-6).
            validate_interface_exists(cfg_net.interface)
        except InterfaceError as e:
            logger.error(f"Interface validation failed: {e}")
            if not interface_present(cfg_net.interface):
                # The adapter disconnected (USB drop or driver reset): a radio
                # fault, so the client may retry and the adapter can be recovered.
                raise StartupFailure(
                    f"Interface {cfg_net.interface} is not present", radio=True,
                ) from e
            raise ValueError(str(e)) from e

        # Determine internet enabled status
        internet_enabled = (
            req.internet_enabled
            if req.internet_enabled is not None
            else self.config.internet_enabled_by_default
        )

        # Best-effort: prevent NetworkManager/wpa_supplicant from contending AP interface.
        self._configure_networkmanager_unmanaged(cfg_net.interface)
        
        # A classified radio failure happened in this request (HAP-3): a later
        # attempt that fails while starting the AP keeps that classification.
        radio_seen = False
        for attempt in range(1, STARTUP_ATTEMPTS + 1):
            retrying = attempt > 1
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
                        **({"captive_dns": True} if req.captive_portal else {}),
                    )
                    if req.captive_portal:
                        stage = "start captive portal"
                        portal = CaptivePortal(
                            interface=cfg_net.interface, net_id=device_id, gateway=str(net[1]),
                            context=lambda: self._portal_context(device_id),
                            lookup_mac=lambda ip: self._client_mac(device_id, ip),
                            firewall_lock=self._firewall_lock,
                        )
                        # Tracked before start so a rollback removes partial rules.
                        self.captive_portals[device_id] = portal
                        portal.start()
                    # NAT and isolation are part of the startup (NET-2): a network
                    # never reports success without the firewall it claims.
                    if internet_enabled:
                        stage = "enable Internet"
                        try:
                            with self._firewall_lock:
                                self.nat_manager.enable_nat(cfg_net.interface, device_id, subnet)
                        except RuntimeError as exc:
                            raise CommandError(str(exc)) from exc
                        logger.info("NAT enabled for %s", device_id)
                    stage = "isolate network"
                    with self._firewall_lock:
                        self.isolation_manager.add_network(subnet)
                    logger.info("Isolation rules applied for %s (%s)", device_id, subnet)
                    # The host itself is off limits to AP clients (SEC-3); part of the
                    # startup like NAT and isolation, so it is never silently missing.
                    stage = "protect host"
                    running_portal = self.captive_portals.get(device_id)
                    with self._firewall_lock:
                        self.host_guard.add(
                            cfg_net.interface, device_id,
                            running_portal.port if running_portal is not None else None,
                        )
                    if retrying and (
                        time.monotonic() >= retry_deadline
                        or (expires_at_timestamp is not None and time.time() >= expires_at_timestamp)
                    ):
                        stage = "complete startup retry"
                        raise CommandError("Startup retry deadline expired")
            except (HostapdError, CommandError, DhcpServerError, CaptivePortalError) as e:
                logger.error("Failed to %s for %s: %s", stage, device_id, e)
                radio_seen = radio_seen or isinstance(e, HostapdRadioFailure)
                radio = isinstance(e, HostapdRadioFailure) or (radio_seen and stage == "start AP")
                try:
                    self.release_device(device_id)
                except RuntimeError:
                    logger.exception("Startup rollback failed for %s", device_id)
                    raise StartupFailure(
                        f"Failed to {stage}: {e}",
                        radio=radio or not interface_present(cfg_net.interface),
                        cleanup_failed=True,
                    ) from e
                if not interface_present(cfg_net.interface):
                    # Whatever hostapd reported, the netdev vanished under it: a
                    # radio fault. An immediate internal retry cannot succeed
                    # until the adapter re-enumerates, so leave it to the client.
                    logger.warning(
                        "Interface %s disappeared during startup; treating it as a radio failure",
                        cfg_net.interface,
                    )
                    raise StartupFailure(
                        f"Failed to {stage}: interface {cfg_net.interface} disappeared ({e})",
                        radio=True,
                    ) from e

                if (
                    attempt < STARTUP_ATTEMPTS
                    and allow_internal_retry
                    and stage == "start AP"
                    and isinstance(e, HostapdRadioFailure)
                    and retry_deadline - time.monotonic()
                    >= STARTUP_RETRY_DELAY + MIN_RETRY_ATTEMPT_TIME
                ):
                    time.sleep(STARTUP_RETRY_DELAY)
                    if (
                        retry_deadline - time.monotonic() >= MIN_RETRY_ATTEMPT_TIME
                        and (expires_at_timestamp is None or time.time() < expires_at_timestamp)
                    ):
                        logger.info(
                            "Retrying AP startup (attempt %d/%d) after %s on %s",
                            attempt + 1, STARTUP_ATTEMPTS, type(e).__name__, device_id,
                        )
                        continue
                raise StartupFailure(f"Failed to {stage}: {e}", radio=radio) from e
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
            captive_portal=req.captive_portal,
            captive_portal_url=self.captive_portals[device_id].url if req.captive_portal else None,
            tx_power_level=tx_power_level,
            expires_at=expires_at_str,
            expires_in=expires_in,
        )
        # Store internal timestamp for expiration checking
        object.__setattr__(status, '_expires_at_timestamp', expires_at_timestamp)  # type: ignore[attr-defined]
        
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
        # A startup rollback runs before the network is active: use the assigned
        # subnet so its isolation rules are removed too (NET-2).
        assigned = self._assigned_subnets.get(device_id)
        subnet = self.active[device_id].subnet if device_id in self.active else (
            str(assigned) if assigned is not None else None
        )
        
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

        portal = self.captive_portals.get(device_id)
        if portal is not None:
            try:
                portal.stop()
                self.captive_portals.pop(device_id, None)
            except CaptivePortalError as e:
                logger.error("Error stopping captive portal: %s", e)
                errors.append(f"captive portal: {e}")
        
        # Remove the host guard (SEC-3)
        try:
            with self._firewall_lock:
                self.host_guard.remove(device_id)
        except CommandError as e:
            logger.error("Error removing host guard: %s", e)
            errors.append(f"host guard: {e}")

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

    def get_status(self, device_id: str) -> NetworkStatus | None:
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

    def get_summary(self, device_id: str) -> dict | None:
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
            raise NetworkNotActive(device_id)
        
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
            raise NetworkNotActive(device_id)
        
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

    def list_clients(self, device_id: str) -> list[ClientInfo]:
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

        mac_to_ip = self._leases(device_id)
        portal = self.captive_portals.get(device_id)

        # Build client list: only include clients with BOTH WiFi association AND valid DHCP lease
        for mac in connected_macs:
            client_ip = mac_to_ip.get(mac)
            if client_ip:  # Only count as connected if they have a valid IP lease
                clients.append(ClientInfo(
                    mac=mac, ip=client_ip,
                    captive_authorized=portal.is_authorized(client_ip, mac) if portal else None,
                ))
        
        return clients

    def _leases(self, device_id: str) -> dict[str, str]:
        """Return MAC -> IP for unexpired DHCP leases of a network."""
        mac_to_ip: dict[str, str] = {}
        now = int(time.time())
        dhcp_info = self.dhcp_server.get_subnet_info(device_id)
        lease_file = dhcp_info.get("lease_file") if dhcp_info else None
        if lease_file and os.path.exists(lease_file):
            try:
                with open(lease_file) as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 3 and parts[0].isdigit() and int(parts[0]) > now:
                            mac_to_ip[parts[1].lower()] = parts[2]
            except OSError as e:
                logger.warning(f"Could not read lease file: {e}")
        return mac_to_ip

    def _client_mac(self, device_id: str, ip: str) -> str | None:
        """Identify a client by IP from its DHCP lease, else from the neighbour table."""
        mac = next((mac for mac, lease_ip in self._leases(device_id).items() if lease_ip == ip), None)
        if mac is not None:
            return mac
        try:
            neighbour = execute_ip(["neigh", "show", ip, "dev", device_id]).split()
        except CommandError:
            return None
        return neighbour[neighbour.index("lladdr") + 1] if "lladdr" in neighbour[:-1] else None

    def _portal_context(self, device_id: str) -> dict[str, str]:
        """Network details shown on the captive portal page."""
        st = self.active.get(device_id)
        dhcp_info = self.dhcp_server.get_subnet_info(device_id) or {}
        if st is None:
            return {"dhcp_range": str(dhcp_info.get("dhcp_range", "")).replace(",", " - ")}
        expires = getattr(st, "_expires_at_timestamp", None)
        return {
            "ssid": st.ssid or "",
            "radio": f"{st.band} / {st.channel}",
            "subnet": st.subnet or "",
            "dhcp_range": str(dhcp_info.get("dhcp_range", "")).replace(",", " - "),
            "internet": "enabled after sign-in" if st.internet_enabled
            else "disabled on this network (sign-in does not give Internet access)",
            "expires": format_utc_timestamp(expires) or "no expiry",
        }

    def verify_network(self, device_id: str) -> tuple[list[str], bool]:
        """Check what a running network needs beyond its processes (WD-7).

        Repairs in place what can be repaired without touching the AP: the
        gateway address (then DHCP is restarted), `ip_forward`, the NAT or
        Internet-block rules and the isolation rules. Returns the repairs and
        whether the whole network must be restored instead (captive portal
        server or rules gone). The caller holds the device lock.
        """
        status = self.active.get(device_id)
        if status is None or status.subnet is None:
            return [], False
        repaired: list[str] = []
        net = IPv4Network(status.subnet)
        gateway = f"{net[1]}/{net.prefixlen}"
        addresses = execute_ip(["-4", "-o", "addr", "show", "dev", status.interface]).split()
        if gateway not in addresses:
            execute_ip(["addr", "add", gateway, "dev", status.interface])
            repaired.append("gateway address")
            self.dhcp_server.stop(device_id)
            self.dhcp_server.start(
                device_id, status.interface, status.subnet, self.config.dns_server,
                **({"captive_dns": True} if status.captive_portal else {}),
            )
        with self._firewall_lock:
            repaired += self.nat_manager.verify(status.interface, device_id, status.subnet)
            repaired += self.isolation_manager.verify()
            guard = self.host_guard.problems(device_id)
        portal = self.captive_portals.get(device_id)
        # A missing host guard is re-created with the whole network (SEC-3).
        broken = guard + (portal.problems() if portal is not None else [])
        return repaired + broken, bool(broken)

    def firewall_status(self) -> dict:
        """Read the firewall state without colliding with a rule change (NET-1)."""
        with self._firewall_lock:
            return self.nat_manager.status()

    def services_status(self) -> dict:
        """Return minimal service status (dnsmasq, hostapd, iptables)."""
        return {
            "dnsmasq": self.dhcp_server.status(),
            "hostapd": self.hostapd_manager.status(),
            "iptables": self.firewall_status(),
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

    def _read_current_txpower(self, interface: str) -> float | None:
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

    def _compute_level_dbm(self, max_dbm: float) -> dict[int, float]:
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

    def _reported_level_from_dbm(self, levels_dbm: dict[int, float], reported_dbm: float | None) -> int | None:
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
            raise NetworkNotActive(device_id)
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
            raise NetworkNotActive(device_id)
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
        last_error = ""  # log a repeated failure's traceback once (WD-9)
        while not self.watchdog.stopping.wait(5):
            heartbeat.beat("expiry")
            try:
                now = time.time()
                # Copy keys to avoid mutation during iteration
                for device_id, st in self.active.copy().items():
                    self._expire_network(device_id, st, now)
                if self.expire_reservations is not None:
                    self.expire_reservations()
            except Exception as exc:  # this loop must survive anything (WD-9)
                if repr(exc) != last_error:
                    logger.exception("[expiry-loop] Unexpected error")
                last_error = repr(exc)
            else:
                last_error = ""

    def _expire_network(self, device_id: str, status: NetworkStatus, now: float) -> None:
        timestamp = getattr(status, '_expires_at_timestamp', None)
        if timestamp is None or timestamp >= now:
            return
        lock = self.device_lock(device_id)
        if not lock.acquire(blocking=False):
            return
        try:
            if self.active.get(device_id) is not status or not self.cleanup_due(device_id):
                return
            first = device_id not in self._cleanup_failures
            if first:
                logger.info(f"[expiry-loop] Network {device_id} expired, stopping")
            try:
                self._tracked_stop(device_id)
            except RuntimeError as e:
                if first:
                    logger.error(f"[expiry-loop] Failed stopping {device_id}: {e}")
        finally:
            lock.release()


