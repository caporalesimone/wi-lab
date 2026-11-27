import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import IPv4Network
from typing import Any

from .. import heartbeat, log
from ..config import AppConfig
from ..devices import Device, DeviceRegistry
from ..health import HealthChecks
from ..models import ClientInfo, NetworkCreateRequest, NetworkStatus
from ..network.captive import CaptivePortal, CaptivePortalError
from ..network.commands import (
    CommandError,
    execute_ip,
    execute_iw,
)
from ..network.dhcp import DhcpServer, DhcpServerError
from ..network.host_guard import HostGuard
from ..network.isolation import IsolationManager
from ..network.nat import NatManager
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from ..network.subnet_allocator import SubnetAllocator
from ..reservation import Reservation, ReservationManager
from ..timestamps import format_utc_timestamp
from .active import ActiveNetwork
from .channels import ChannelManager, is_dfs_channel
from .clients import ClientLister
from .failures import FailureKind
from .hostapd import (
    HostapdError,
    HostapdManager,
)
from .interface import (
    InterfaceError,
    interface_present,
    validate_interface_exists,
)
from .recovery import RadioRecovery
from .startup import RetryPolicy, StartPlan, StartupFailure, run_startup
from .txpower import TxPowerControl
from .watchdog import NetworkWatchdog

logger = logging.getLogger(__name__)

# Delay before the next background cleanup of a device whose cleanup failed, by
# number of consecutive failures; the last value repeats (WD-6). A client's
# explicit DELETE is never delayed.
CLEANUP_BACKOFF = (5.0, 15.0, 60.0, 300.0)
# Consecutive failed cleanups of one device after which the failure is logged
# as an ERROR: the background retries did not clear it, someone must look (ARCH-10).
CLEANUP_ERROR_AFTER = 3
# A TX power level the driver refuses is refused on every start (TXP-1).
TXPOWER_WARNING_INTERVAL = 3600.0
# Longest wait for a running AP start to notice a cancel (release, stop) and roll back.
CANCEL_TIMEOUT = 30.0
# Channel of the recovery probe when the last one is DFS: a probe never waits for a
# 60 s radar check under the device lock (REV-6).
PROBE_5GHZ_CHANNEL = 36
# Longest time shutdown_all spends cancelling creates and releasing antennas. With
# uvicorn's 10 s graceful shutdown and the 10 s discovery join it stays inside
# TimeoutStopSec=60s of the unit (STAB-8).
SHUTDOWN_TIMEOUT = 20.0


@dataclass
class StartJob:
    """An AP start running in the background (asynchronous create).

    `state` is `starting` until the start ends: on success the job is dropped (the
    network is active); a non-radio failure keeps it as `start_failed` with the
    error until the next create, a stop or the end of the reservation.
    """

    reservation: Reservation
    request: NetworkCreateRequest
    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    state: str = "starting"
    error: dict[str, Any] | None = None
    thread: threading.Thread | None = None


def _monotonic_deadline(expires_at: float | None) -> float | None:
    """Monotonic time of a wall-clock expiry (STAB-5); None for no expiry."""
    return None if expires_at is None else time.monotonic() + (expires_at - time.time())

class NetworkNotActive(ValueError):
    """The reservation is valid but it has no running network (API-2)."""

    def __init__(self, device_id: str) -> None:
        super().__init__(f"No access point is active on {device_id}")
        self.device_id = device_id


class NetworkStopError(RuntimeError):
    """A stop did not complete (e.g. hostapd stuck in the kernel after SIGKILL).

    Answered `503 / 1012` (stop_incomplete) with `Retry-After`. The network
    stays in `active` so that repeating the stop finishes it; until
    then the watchdog leaves it alone and `GET /access-point/{reservation_id}` reports
    `runtime_state: stop_failed`.
    """


# The API names no device_id (Fable API-6): the reservation's antenna is unknown.
UNKNOWN_ANTENNA = "The antenna of this reservation is not managed"


class NetworkManager:
    """Manages WiFi AP network lifecycle including DHCP, NAT, and isolation."""
    
    def __init__(
        self, config: AppConfig, devices: DeviceRegistry, channel_manager: ChannelManager | None = None,
    ):
        self.config = config
        # The managed devices and their locks, shared with the reservations (ARCH-4).
        self.devices = devices
        self.active: dict[str, ActiveNetwork] = {}
        self.dhcp_server = DhcpServer()
        self.nat_manager = NatManager(upstream_interface=config.upstream_interface)
        self.hostapd_manager = HostapdManager(debug_dir=config.hostapd_debug_dir)
        self.isolation_manager = IsolationManager()
        self.host_guard = HostGuard()  # SEC-3: AP clients cannot reach the host
        self.captive_portals: dict[str, CaptivePortal] = {}
        # One channel cache for the whole service (BUG-4): the API passes its own.
        self._channel_manager = channel_manager or ChannelManager(show_dfs_channels=devices.show_dfs_channels)
        self.tx_power = TxPowerControl(self._channel_manager)
        self.qos_manager: QosManager | None = None
        self.qos_profile_manager: QosProfileManager | None = None
        self._firewall_lock = threading.Lock()
        self.subnets = SubnetAllocator(config, devices)
        # WD-6: consecutive cleanup failures and next background attempt per device
        self._cleanup_failures: dict[str, int] = {}
        self._stop_failed: set[str] = set()  # stops to repeat (NetworkStopError)
        self.clients = ClientLister(devices, self.dhcp_server, self.captive_portals)
        # Asynchronous creates: one job per device, guarded by start_jobs_lock.
        self.start_jobs: dict[str, StartJob] = {}
        self.start_jobs_lock = threading.Lock()
        # Host-command health checks, refreshed by a background loop (wilab.health).
        self.health = HealthChecks(self)
        self._cleanup_retry_at: dict[str, float] = {}
        self.expire_reservations: Callable[[], None] | None = None
        self.recovery = RadioRecovery(self)
        # device -> (quarantines since the service started, wall time of the last, USB recovery)
        self.quarantines: dict[str, tuple[int, float, bool]] = {}
        self.watchdog = NetworkWatchdog(self)
        # A lost control connection or AP-DISABLED runs the antenna's next check now (PERF-4).
        self.hostapd_manager.on_change = self.watchdog.wake
        # Background expiry checker to auto-stop networks at timeout; started by
        # start(), never by the constructor (ARCH-5).
        self._expiry_thread: threading.Thread | None = None
        logger.info("NetworkManager initialized")

    def start(self) -> None:
        """Start the expiry loop; it ends with the watchdog (`watchdog.stopping`)."""
        if self._expiry_thread is not None:
            return
        self._expiry_thread = threading.Thread(target=self._expiry_loop, name="network-expiry", daemon=True)
        self._expiry_thread.start()

    @property
    def channel_manager(self) -> ChannelManager:
        """The service-wide channel and capability cache."""
        return self._channel_manager

    def _get_subnet(self, device_id: str) -> str:
        """Allocate or reuse a non-overlapping /24 before a new AP start."""
        if device_id not in self.devices:
            raise ValueError(UNKNOWN_ANTENNA)
        return self.subnets.allocate(device_id)

    def has_leftovers(self, device_id: str) -> bool:
        """True if a device that is not active still has tracked resources.

        A start that failed and could not roll back leaves them: hostapd,
        dnsmasq, the captive portal or firewall rules (REV-1).
        """
        with self._firewall_lock:
            firewall_pending = (
                self.nat_manager.has_pending_network(device_id) or self.host_guard.has(device_id)
            )
        return (
            self.hostapd_manager.is_tracked(device_id)
            or device_id in self.dhcp_server.list_active()
            or device_id in self.captive_portals
            or firewall_pending
        )

    def release_device(self, device_id: str) -> None:
        """Stop all tracked resources before a device can be reassigned."""
        with self.devices.lock(device_id):
            if device_id in self.active or self.has_leftovers(device_id):
                self._tracked_stop(device_id)
            if device_id in self.active:
                raise RuntimeError(f"Network {device_id} is still active")

    def _tracked_stop(self, device_id: str) -> None:
        """stop_network, recording failures for the background backoff (WD-6).

        The server owns this cleanup: a stop the client had to repeat is no
        longer the client's (REV-9).
        """
        self._stop_failed.discard(device_id)
        try:
            self.stop_network(device_id)
        except RuntimeError:
            failures = self._cleanup_failures.get(device_id, 0) + 1
            delay = CLEANUP_BACKOFF[min(failures, len(CLEANUP_BACKOFF)) - 1]
            self._cleanup_failures[device_id] = failures
            self._cleanup_retry_at[device_id] = time.monotonic() + delay
            if failures > 1:
                logger.log(
                    logging.ERROR if failures >= CLEANUP_ERROR_AFTER else logging.WARNING,
                    "Cleanup of %s failed %d times in a row; next background attempt in %.0f s",
                    device_id, failures, delay,
                )
            raise
        if self._cleanup_failures.pop(device_id, None) is not None:
            logger.warning("Cleanup of %s succeeded after earlier failures", device_id)
        self._cleanup_retry_at.pop(device_id, None)

    def start_job(self, reservation: Reservation) -> StartJob | None:
        """The create job of *reservation*; a job left by an ended reservation is dropped."""
        with self.start_jobs_lock:
            job = self.start_jobs.get(reservation.device_id)
            if job is not None and job.reservation is not reservation and job.done.is_set():
                del self.start_jobs[reservation.device_id]
                return None
            return job if job is not None and job.reservation is reservation else None

    def cancel_start(self, device_id: str, timeout: float = CANCEL_TIMEOUT) -> bool:
        """Cancel the create running on *device_id* and wait for its rollback.

        Called before a release or a stop takes the device lock, which the start
        holds. Returns True if a start was running. Also drops a `start_failed`.
        """
        with self.start_jobs_lock:
            job = self.start_jobs.get(device_id)
        if job is None or job.thread is threading.current_thread():
            return False  # nothing to cancel, or the start releasing its own reservation
        running = not job.done.is_set()
        job.cancel.set()
        if running and not job.done.wait(timeout):
            # The job stays in start_jobs until its thread ends (REV-8): forgotten
            # now, a later create would start a second thread next to it.
            logger.error("AP start on %s did not stop within %.0f s of the cancel", device_id, timeout)
        with self.start_jobs_lock:
            if self.start_jobs.get(device_id) is job and job.done.is_set():
                del self.start_jobs[device_id]
        return running

    def forget_finished_start(self, device_id: str) -> None:
        """Drop a start that ended (start_failed) when its reservation expires (REV-11)."""
        with self.start_jobs_lock:
            job = self.start_jobs.get(device_id)
            if job is not None and job.done.is_set():
                del self.start_jobs[device_id]

    def runs(self, device_id: str, req: NetworkCreateRequest) -> bool:
        """True if the active network of *device_id* has exactly the settings of *req*.

        A create repeated after a lost answer then gets the network instead of
        409 / 1008. Internet and TX power changed since the create make it differ.
        """
        st = self.active.get(device_id)
        if st is None or device_id in self._stop_failed:
            return False
        internet = (
            req.internet_enabled if req.internet_enabled is not None
            else self.config.internet_enabled_by_default
        )
        running = (
            st.ssid, st.password or None, st.encryption, st.band, st.channel, bool(st.hidden),
            st.channel_width or 20, st.wifi_generation or 4, st.enable_generation_fallback,
            st.internet_enabled, st.captive_portal, st.tx_power_level,
        )
        asked = (
            req.ssid, req.password or None, req.encryption, req.band, req.channel, req.hidden,
            req.channel_width, req.wifi_generation, req.enable_generation_fallback, internet,
            req.captive_portal, req.tx_power_level,
        )
        return running == asked

    def stop_failed(self, device_id: str) -> bool:
        """True after a stop that did not complete, until a stop completes."""
        return device_id in self._stop_failed

    def cleanup_wait(self, device_id: str) -> float:
        """Seconds until the next background cleanup of a device whose cleanup failed."""
        return max(0.0, self._cleanup_retry_at.get(device_id, 0.0) - time.monotonic())

    def cleanup_failures(self) -> dict[str, int]:
        """Devices whose last cleanup failed, with the failures in a row."""
        return dict(self._cleanup_failures)

    def unused(self, device_id: str) -> bool:
        """Nothing of a network is left on *device_id* (retirement, WD-5; device lock held)."""
        with self.start_jobs_lock:
            starting = device_id in self.start_jobs
        return not (
            starting or device_id in self.active or device_id in self._cleanup_failures
            or self.stop_failed(device_id) or self.hostapd_manager.is_tracked(device_id)
            or self.dhcp_server.get_subnet_info(device_id) is not None
            or self.watchdog.owes(device_id)
        )

    def forget_device(self, device: Device) -> None:
        """Drop what the service remembers about a retired device (WD-5)."""
        device_id = device.device_id
        self.quarantines.pop(device_id, None)
        self.subnets.release(device_id)
        self.recovery.forget(device_id)
        self.watchdog.retire(device_id)
        self._channel_manager.invalidate(device_id)

    def cleanup_due(self, device_id: str) -> bool:
        """False while a failed cleanup of this device waits for its next background attempt."""
        return time.monotonic() >= self._cleanup_retry_at.get(device_id, 0.0)

    def start_network(
        self, device_id: str, req: NetworkCreateRequest,
        expires_at_timestamp: float | None = None, *, allow_internal_retry: bool = True,
        cancelled: Callable[[], bool] | None = None,
    ) -> NetworkStatus:
        with self.devices.lock(device_id):
            return self._start_network(
                device_id, req, expires_at_timestamp, allow_internal_retry, cancelled,
            )

    def quarantine_radio(
        self, reservations: ReservationManager, reservation: Reservation, *, radio_fault: bool,
        band: str, channel: int,
    ) -> None:
        device = reservation.device_id
        self.recovery.remember_radio(device, band, channel)
        managed = self.devices.get(device)
        port = managed.usb_port if managed is not None else None
        if not radio_fault or self.config.upstream_interface == device:
            port = None
        reservations.quarantine(reservation, recovering=port is not None)
        count = self.quarantines.get(device, (0, 0.0, False))[0] + 1
        self.quarantines[device] = (count, time.time(), port is not None)
        if port is not None:
            try:
                self.recovery.schedule(reservations, device, port, band, channel)
            except RuntimeError:
                reservations.finish_recovery(device, recovered=False)
                logger.exception("Could not schedule USB recovery for %s", device)

    def probe_recovered_radio(self, device: str, band: str, channel: int) -> None:
        """Verify AP and DHCP startup without publishing a user network or enabling NAT."""
        # A reset adapter announces its channels again: never trust the old list (BUG-4).
        self._channel_manager.invalidate(device)
        if is_dfs_channel(band, channel):
            channel = PROBE_5GHZ_CHANNEL
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
        cancelled: Callable[[], bool] | None = None,
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
        # Validate device_id is a managed device
        cfg_net = self.devices.get(device_id)
        if not cfg_net:
            raise ValueError(UNKNOWN_ANTENNA)

        # A running network must be stopped first (the route answers 409 / 1008 before this).
        if device_id in self.active:
            raise StartupFailure(
                f"An access point is already active on {device_id}. Stop it first before creating a new one.",
                kind=FailureKind.CONFLICT,
            )
        # Logged only for a create that really starts (a refused one used to log it too).
        logger.info("Starting network %s with SSID '%s'", device_id, req.ssid)
        
        # Clear any tracked resources left by a failed startup before retrying.
        try:
            self.release_device(device_id)
        except RuntimeError as e:
            raise StartupFailure(
                f"Failed to clean up previous startup: {e}", kind=FailureKind.CLEANUP_FAILED,
            ) from e
        
        expires_at_str = format_utc_timestamp(expires_at_timestamp)
        # Monotonic from here on (STAB-5): a wall-clock jump must not expire the network.
        deadline = _monotonic_deadline(expires_at_timestamp)
        
        # Select a safe subnet before configuring the AP or gateway.
        subnet = self._get_subnet(device_id)
        
        # Validate interface
        logger.info("Validating interface %s", cfg_net.interface)
        try:
            # Wireless and AP capability were established by discovery and cannot change
            # for this interface; only its presence can (PERF-1, BUG-6).
            validate_interface_exists(cfg_net.interface)
        except InterfaceError as e:
            logger.warning("Interface validation failed: %s", e)
            if not interface_present(cfg_net.interface):
                # The adapter disconnected (USB drop or driver reset): a radio
                # fault, so the client may retry and the adapter can be recovered.
                raise StartupFailure(
                    f"Interface {cfg_net.interface} is not present", kind=FailureKind.TRANSIENT_RADIO,
                ) from e
            raise StartupFailure(str(e), stage="interface") from e

        # Determine internet enabled status
        internet_enabled = (
            req.internet_enabled
            if req.internet_enabled is not None
            else self.config.internet_enabled_by_default
        )

        # The route checked the same before (422); this picks the channel block
        # and covers starts that do not come from the API (watchdog restore).
        try:
            layout = self._channel_manager.validate_network(
                cfg_net.interface, req.band, req.channel, req.channel_width, req.wifi_generation,
                req.encryption,
            )
        except CommandError as e:
            # `iw` could not read the channels: a radio fault if the antenna is gone.
            raise StartupFailure(
                f"Cannot read the channels of {cfg_net.interface}: {e}",
                kind=(
                    FailureKind.CONFIGURATION if interface_present(cfg_net.interface)
                    else FailureKind.TRANSIENT_RADIO
                ),
                stage="interface",
            ) from e

        plan = StartPlan(
            device_id=device_id, interface=cfg_net.interface, request=req, subnet=subnet,
            internet_enabled=internet_enabled, layout=layout, cancelled=cancelled,
        )
        policy = RetryPolicy.internal() if allow_internal_retry else RetryPolicy.single()
        run_startup(self, plan, policy, deadline)

        # Apply TX power level from request
        tx_power_level = req.tx_power_level
        try:
            self.tx_power.set_level(cfg_net.interface, tx_power_level, req.channel)
            runtime_dbm = self.tx_power.read_dbm(cfg_net.interface)
            logger.info("TX power set for %s: requested level %s, runtime reported %s dBm", device_id, tx_power_level, runtime_dbm)
        except Exception as e:
            # Same cause on every start (mt7921u: -95, TXP-1): once an hour per antenna (ARCH-10).
            log.every(
                logger, logging.WARNING, ("txpower", device_id, str(e)),
                "Failed to set TX power for %s: %s", device_id, e, interval=TXPOWER_WARNING_INTERVAL,
            )
        
        network = ActiveNetwork(
            interface=cfg_net.interface,
            request=req,
            subnet=subnet,
            internet_enabled=internet_enabled,
            tx_power_level=tx_power_level,
            captive_portal_url=self.captive_portals[device_id].url if req.captive_portal else None,
            expires_at=expires_at_str,
            deadline=deadline,
        )
        self.active[device_id] = network
        logger.info("Network %s started successfully (expires at %s)", device_id, expires_at_str)
        
        return network.status()

    def stop_network(self, device_id: str, *, client: bool = False) -> None:
        """Stop the network of *device_id*.

        *client*: the stop the reservation owner asked for (DELETE /access-point/{reservation_id}).
        Only that one, when it fails, marks the network `stop_failed` for the
        owner to repeat (REV-9). A rollback, an expiry or a background cleanup
        that fails is retried by the server, not by the client.
        """
        with self.devices.lock(device_id):
            self._stop_network(device_id, client=client)

    def _stop_network(self, device_id: str, *, client: bool = False) -> None:
        """
        Stop an AP network and clean up DHCP and NAT.
        
        Args:
            device_id: Device identifier (interface name)
        """
        logger.info("Stopping network %s", device_id)
        errors: list[str] = []
        
        # Get interface and subnet before removing from active dict
        cfg_net = self.devices.get(device_id)
        # A startup rollback runs before the network is active: use the assigned
        # subnet so its isolation rules are removed too (NET-2).
        assigned = self.subnets.assigned(device_id)
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
                logger.warning("Error clearing QoS rules: %s", e)
                errors.append(f"QoS: {e}")

        # Stop hostapd
        hostapd_stopped = False
        try:
            self.hostapd_manager.stop(device_id)
            hostapd_stopped = True
        except Exception as e:
            logger.warning("Error stopping hostapd: %s", e)
            errors.append(f"hostapd: {e}")
        
        # Disable NAT if it was enabled
        if cfg_net and hostapd_stopped:
            try:
                with self._firewall_lock:
                    self.nat_manager.release_network(cfg_net.interface, device_id)
            except Exception as e:
                logger.warning("Error disabling NAT: %s", e)
                errors.append(f"NAT: {e}")

        portal = self.captive_portals.get(device_id)
        if portal is not None:
            try:
                portal.stop()
                self.captive_portals.pop(device_id, None)
            except CaptivePortalError as e:
                logger.warning("Error stopping captive portal: %s", e)
                errors.append(f"captive portal: {e}")
        
        # The host guard (SEC-3) and the isolation rules stay while hostapd may
        # still run: its clients would reach the host and the other networks.
        # The repeated stop removes them once hostapd is gone (REV-7).
        if not hostapd_stopped:
            logger.warning("Keeping host guard and isolation of %s until hostapd stops", device_id)
        else:
            try:
                with self._firewall_lock:
                    self.host_guard.remove(device_id)
            except CommandError as e:
                logger.warning("Error removing host guard: %s", e)
                errors.append(f"host guard: {e}")

        # Remove isolation rules
        if subnet and hostapd_stopped:
            try:
                with self._firewall_lock:
                    self.isolation_manager.remove_network(subnet)
                logger.info("Isolation rules removed for %s (%s)", device_id, subnet)
            except Exception as e:
                logger.warning("Error removing isolation rules: %s", e)
                errors.append(f"isolation: {e}")
        
        # Stop DHCP server
        try:
            self.dhcp_server.stop(device_id)
        except Exception as e:
            logger.warning("Error stopping DHCP server: %s", e)
            errors.append(f"DHCP: {e}")

        if errors:
            if client:
                self._stop_failed.add(device_id)
            raise NetworkStopError(f"Failed to stop the access point on {device_id}: {'; '.join(errors)}")

        # Remove from active dict
        self.active.pop(device_id, None)
        self.clients.forget(device_id)
        self._stop_failed.discard(device_id)
        
        logger.info("Network %s stopped", device_id)

    def get_status(self, device_id: str) -> NetworkStatus | None:
        with self.devices.lock(device_id):
            return self._get_status(device_id)

    def active_status(self, device_id: str) -> ActiveNetwork | None:
        """The stored state of a running network, without querying the radio (PERF-2).

        For callers that only need to know whether the network runs and its
        settings: no `iw` and no lease file. None if no network runs (an
        expired one is stopped here, like in get_status).
        """
        with self.devices.lock(device_id):
            st = self.active.get(device_id)
            if st is None:
                return None
            if st.expired(time.monotonic()):
                self._expire_held(device_id)
                return None
            return st if st.active else None

    def _get_status(self, device_id: str) -> NetworkStatus | None:
        """
        Get current status of a network.
        Auto-expires networks past their timeout.
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            NetworkStatus object or None if unknown device_id
        """
        network = self.active.get(device_id)
        if not network:
            # Return inactive status if known device_id
            cfg_net = self.devices.get(device_id)
            if not cfg_net:
                return None
            return NetworkStatus(interface=cfg_net.interface, active=False)
        
        # Check if network has expired (monotonic deadline, STAB-5)
        if network.expired(time.monotonic()):
            self._expire_held(device_id)
            cfg_net = self.devices.get(device_id)
            if not cfg_net:
                return None
            return NetworkStatus(interface=cfg_net.interface, active=False)
        # A fresh answer each time: the live reads below are never stored (ARCH-3).
        st = network.status()
        
        # Add DHCP info and clients if active
        if st.active:
            dhcp_info = self.dhcp_server.get_subnet_info(device_id)
            clients = self.list_clients(device_id)
            st.dhcp = dhcp_info if dhcp_info else {}
            st.clients = clients
            st.clients_connected = len(clients)
            st.reported_channel_width = self._read_channel_width(st.interface)

            if st.tx_power_level is not None:
                st.tx_power = self.tx_power.status(device_id, st.interface, st.channel, st.tx_power_level)
        
        return st

    def enable_internet(self, device_id: str) -> NetworkStatus:
        """
        Enable Internet access for a network (NAT forwarding).
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            Updated NetworkStatus
        """
        logger.info("Enabling Internet for network %s", device_id)
        
        st = self.active_status(device_id)
        if st is None:
            raise NetworkNotActive(device_id)
        
        # Get interface for NAT rules
        cfg_net = self.devices.get(device_id)
        if not cfg_net:
            raise ValueError(UNKNOWN_ANTENNA)
        
        # Enable NAT if not already enabled
        if not st.internet_enabled:
            try:
                with self._firewall_lock:
                    self.nat_manager.enable_nat(cfg_net.interface, device_id, st.subnet or self._get_subnet(device_id))
                logger.info("NAT rules applied for %s", device_id)
            except Exception as e:
                logger.warning("Failed to enable NAT: %s", e)
                raise RuntimeError(f"Cannot enable Internet: {e}") from e
        
        st.internet_enabled = True
        logger.info("Internet enabled for %s", device_id)
        
        return st.status()

    def disable_internet(self, device_id: str) -> NetworkStatus:
        """
        Disable Internet access for a network (block NAT forwarding).
        
        Args:
            device_id: Device identifier (interface name)
            
        Returns:
            Updated NetworkStatus
        """
        logger.info("Disabling Internet for network %s", device_id)
        
        st = self.active_status(device_id)
        if st is None:
            raise NetworkNotActive(device_id)
        
        # Get interface for NAT rules
        cfg_net = self.devices.get(device_id)
        if not cfg_net:
            raise ValueError(UNKNOWN_ANTENNA)
        
        # Disable NAT if currently enabled
        if st.internet_enabled:
            try:
                with self._firewall_lock:
                    self.nat_manager.disable_nat(cfg_net.interface, device_id)
                logger.info("NAT rules removed for %s", device_id)
            except Exception as e:
                logger.warning("Failed to disable NAT: %s", e)
                raise RuntimeError(f"Cannot disable Internet: {e}") from e
        
        st.internet_enabled = False
        logger.info("Internet disabled for %s", device_id)
        
        return st.status()

    def list_clients(self, device_id: str) -> list[ClientInfo]:
        """Connected clients (associated and with a DHCP lease), reused briefly (PERF-2)."""
        return self.clients.connected(device_id)

    def _portal_context(self, device_id: str) -> dict[str, str]:
        """Network details shown on the captive portal page."""
        st = self.active.get(device_id)
        dhcp_info = self.dhcp_server.get_subnet_info(device_id) or {}
        if st is None:
            return {"dhcp_range": str(dhcp_info.get("dhcp_range", "")).replace(",", " - ")}
        expires = None if st.deadline is None else time.time() + (st.deadline - time.monotonic())
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
            self.dhcp_server.stop(device_id, keep_leases=True)
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

    def shutdown_all(self) -> None:
        """Shutdown all active networks."""
        self.recovery.stop()
        self.watchdog.stopping.set()
        logger.info("Shutting down all networks")
        deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        # Cancel every create first, all at once: each rolls back in parallel instead
        # of holding its device lock through its retries and pauses (REV-6).
        with self.start_jobs_lock:
            starting = list(self.start_jobs)
            for job in self.start_jobs.values():
                job.cancel.set()
        for device_id in starting:
            self.cancel_start(device_id, timeout=max(0.0, deadline - time.monotonic()))
        # Antennas are released in parallel: one after the other, a pool of ten
        # could pass systemd's stop timeout and be killed half-way (STAB-8).
        device_ids = sorted(set(self.devices.ids()) | self.active.keys())
        threads = [
            threading.Thread(
                target=self._release_quietly, args=(device_id,), name=f"shutdown-{device_id}", daemon=True,
            )
            for device_id in device_ids
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        left = [thread.name.removeprefix("shutdown-") for thread in threads if thread.is_alive()]
        if left:
            logger.error(
                "Shutdown: %s not released within %.0f s", ", ".join(left), SHUTDOWN_TIMEOUT,
            )
        else:
            logger.info("All networks shut down")

    def _release_quietly(self, device_id: str) -> None:
        try:
            self.release_device(device_id)
        except Exception:
            logger.exception("Error stopping %s during shutdown", device_id)

    @staticmethod
    def _read_channel_width(interface: str) -> int | None:
        """Channel width in MHz from `iw dev <if> info` (HAP-11); None if unavailable."""
        try:
            match = re.search(r"width:\s+(\d+)\s+MHz", execute_iw(["dev", interface, "info"]))
        except CommandError as e:
            logger.warning("Failed to read channel width for %s: %s", interface, e)
            return None
        return int(match[1]) if match else None

    # ---- TX power (wilab.wifi.txpower) ----

    def set_tx_power_level(self, device_id: str, level: int) -> dict:
        """
        Change TX power level for active network.
        Verifies if change was applied and warns if interface doesn't support dynamic changes.
        """
        st = self.active_status(device_id)
        if st is None:
            raise NetworkNotActive(device_id)
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = self.devices.get(device_id)
        if not cfg_net:
            raise ValueError(UNKNOWN_ANTENNA)
        
        # Set power with verification (waits 3s and checks if change applied)
        info = self.tx_power.set_level(cfg_net.interface, level, st.channel, verify_change=True)
        st.tx_power_level = level
        return info

    def get_tx_power_info(self, device_id: str) -> dict:
        """
        Get current TX power info for network.
        Compares configured level with actual interface power and warns if mismatch.
        """
        st = self.active_status(device_id)
        if st is None:
            raise NetworkNotActive(device_id)
        if st.channel is None:
            raise ValueError("Channel unknown for this network")
        cfg_net = self.devices.get(device_id)
        if not cfg_net:
            raise ValueError(UNKNOWN_ANTENNA)
        
        # Get configured level
        level = st.tx_power_level
        if level is None:
            raise ValueError("TX power level not set for this network")
        
        return self.tx_power.info(device_id, cfg_net.interface, st.channel, level)

    def _expiry_loop(self) -> None:
        """Background loop to auto-expire networks without requiring API calls."""
        last_error = ""  # log a repeated failure's traceback once (WD-9)
        while not self.watchdog.stopping.wait(5):
            heartbeat.beat("expiry")
            try:
                now = time.monotonic()   # deadlines are monotonic (STAB-5)
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

    def _expire_network(self, device_id: str, status: ActiveNetwork, now: float) -> None:
        if not status.expired(now):
            return
        with log.context(antenna=device_id):
            self._expire_now(device_id, status)

    def _expire_now(self, device_id: str, status: ActiveNetwork) -> None:
        lock = self.devices.lock(device_id)
        if not lock.acquire(blocking=False):
            return
        try:
            if self.active.get(device_id) is status:
                self._expire_held(device_id)
        finally:
            lock.release()

    def _expire_held(self, device_id: str) -> None:
        """Stop an expired network, with the device lock held; never raises (REV-12).

        The expiry loop and the reads that find the network expired first take
        this one path: a failed stop goes to the background backoff (WD-6)
        instead of out of a GET.
        """
        if not self.cleanup_due(device_id):
            return
        first = device_id not in self._cleanup_failures
        if first:
            logger.info("Network %s expired, stopping", device_id)
        try:
            self._tracked_stop(device_id)
        except RuntimeError as e:
            if first:
                logger.warning("Failed stopping expired network %s: %s", device_id, e)


