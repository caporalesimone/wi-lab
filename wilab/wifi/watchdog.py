"""Bounded recovery of APs that fail after startup."""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import heartbeat
from ..models import NetworkCreateRequest, NetworkStatus
from ..network.commands import CommandError
from ..network.dhcp import DhcpServerError
from ..reservation import Reservation, ReservationManager

if TYPE_CHECKING:
    from .manager import NetworkManager

logger = logging.getLogger(__name__)
# AP restore budget per adapter: at most RESTORE_LIMIT restores in any RESTORE_WINDOW
# seconds. The next failure inside the window quarantines the adapter.
RESTORE_LIMIT = 3
RESTORE_WINDOW = 3600.0
# DHCP restart budget per adapter, same window (WD-3). When it is used up, or a
# DHCP restart fails, the watchdog restarts the whole network instead.
DHCP_RESTORE_LIMIT = 3
# Ticks (5 s each) between checks of what a running network needs beyond its
# processes: gateway address, firewall rules, captive portal (WD-7).
VERIFY_EVERY = 6
# Probe misses that restart the AP, counted in half misses: hostapd answering
# "not ENABLED" (or not running) counts 2, a probe that timed out counts 1. So
# 3 real answers restart the AP, while only 6 slow probes in a row do (WD-10).
MISS_LIMIT = 6
# Delay before each new attempt after a restore that failed for a non-radio
# reason; the last value repeats while the reservation is valid.
RETRY_BACKOFF = (15.0, 30.0, 60.0, 120.0, 300.0)


@dataclass
class _Pending:
    """A network the watchdog still owes to its reservation after a failed restore."""

    reservation: Reservation
    request: NetworkCreateRequest | None  # None: original settings unknown, cannot retry
    band: str
    channel: int
    failures: int = 1
    next_try: float = 0.0


class NetworkWatchdog:
    def __init__(self, manager: "NetworkManager") -> None:
        self.manager = manager
        self.stopping = threading.Event()
        self.states: dict[str, tuple[Reservation, str]] = {}
        self._reservations: ReservationManager | None = None
        self._watched: set[str] = set()
        self._watch_lock = threading.Lock()
        # device -> network owed after a failed restore; guarded by the device lock
        self._pending: dict[str, _Pending] = {}

    def start(self, reservations: ReservationManager) -> None:
        self._reservations = reservations
        self.watch([device.device_id for device in self.manager.config.antennas])

    def watch(self, device_ids: list[str]) -> None:
        """Start one watcher thread per device; devices already watched are ignored."""
        with self._watch_lock:
            if self._reservations is None:
                return
            for device_id in device_ids:
                if device_id in self._watched:
                    continue
                self._watched.add(device_id)
                threading.Thread(
                    target=self._watch, args=(self._reservations, device_id),
                    name=f"ap-watchdog-{device_id}", daemon=True,
                ).start()

    def _watch(self, reservations: ReservationManager, device: str) -> None:
        current = None
        misses = 0
        # Monotonic times of recent AP restores. The budget belongs to the adapter,
        # so it is not reset when the client recreates the network.
        restores: deque[float] = deque()
        dhcp_restores: deque[float] = deque()  # same, for DHCP-only restarts (WD-3)
        restart_network = ""  # why the whole network must be restored on the next tick (WD-3, WD-7)
        restart_reason = ""  # the same, as the stable reason shown in GET .../network restarts
        healthy_ticks = 0  # since the last network check (WD-7)
        last_error = ""  # log a repeated failure's traceback once (WD-9)
        while not self.stopping.wait(5):
            heartbeat.beat(f"watchdog:{device}")
            lock = self.manager.device_lock(device)
            if not lock.acquire(blocking=False):
                continue
            try:
                status = self.manager.active.get(device)
                reservation = reservations.snapshot().get(device)
                pending = self._pending.get(device)
                if pending is not None and (
                    status is not None  # restored, or the client created a network itself
                    or reservation is not pending.reservation  # released, expired or quarantined
                    or self._cancelled(pending.reservation)
                ):
                    self._drop_pending(device)
                elif pending is not None:
                    if pending.request is not None and time.monotonic() >= pending.next_try:
                        self._retry_pending(reservations, pending)
                        current, misses = self.manager.active.get(device), 0
                    continue
                if reservation is None or status is None:
                    self.states.pop(device, None)
                if status is not current:
                    self.states.pop(device, None)
                    current, misses = status, 0
                    restart_network = restart_reason = ""
                if status is None or reservation is None or self._cancelled(reservation):
                    continue
                if self.manager.stop_failed(device):
                    # Half stopped on purpose: repairing it would undo the client's stop.
                    continue
                alive = self.manager.hostapd_manager.is_running(device)
                enabled = self.manager.hostapd_manager.is_enabled(device) if alive else False
                misses = 0 if enabled else misses + (1 if enabled is None else 2)
                if not alive or misses >= MISS_LIMIT or restart_network:
                    if restart_network:
                        logger.warning("%s; restarting the network", restart_network)
                    reservation.record_restart("ap", (
                        "hostapd_not_running" if not alive
                        else restart_reason or (
                            "hostapd_not_enabled" if misses >= MISS_LIMIT else "network_check_failed"
                        )
                    ))
                    restart_network = restart_reason = ""
                    self.states[device] = (reservation, "restoring_ap")
                    now = time.monotonic()
                    while restores and now - restores[0] > RESTORE_WINDOW:
                        restores.popleft()
                    exhausted = len(restores) >= RESTORE_LIMIT
                    if exhausted:
                        logger.warning(
                            "AP on %s failed again after %d restores in %.0f s; quarantining",
                            device, len(restores), RESTORE_WINDOW,
                        )
                    else:
                        logger.warning(
                            "Restoring AP on %s (restore %d of %d in the last hour)",
                            device, len(restores) + 1, RESTORE_LIMIT,
                        )
                    try:
                        self._restore_ap(reservations, reservation, status, exhausted)
                        current = self.manager.active.get(device)
                        restores.append(now)
                        misses = 0
                    finally:
                        if self.states.get(device, (None, ""))[1] == "restoring_ap":
                            self.states.pop(device, None)
                elif misses == 0 and not self.manager.dhcp_server.is_running(device):
                    now = time.monotonic()
                    while dhcp_restores and now - dhcp_restores[0] > RESTORE_WINDOW:
                        dhcp_restores.popleft()
                    if len(dhcp_restores) < DHCP_RESTORE_LIMIT:
                        dhcp_restores.append(now)
                        logger.warning(
                            "Restarting DHCP on %s (restart %d of %d in the last hour)",
                            device, len(dhcp_restores), DHCP_RESTORE_LIMIT,
                        )
                        reservation.record_restart("dhcp", "dnsmasq_not_running")
                        self._restore_dhcp(reservations, reservation, status)
                        failed = self.state(reservation) == "dhcp_failed"
                    else:
                        self.states[device] = (reservation, "dhcp_failed")
                        failed = True
                    # On the next tick, restore the whole network through the AP
                    # budget (WD-1); dhcp_failed stays visible until then.
                    if failed and reservations.snapshot().get(device) is reservation:
                        restart_network = f"DHCP on {device} cannot be repaired alone"
                        restart_reason = "dhcp_failed"
                elif misses == 0:
                    if self.state(reservation) == "dhcp_failed":
                        self.states.pop(device, None)
                    healthy_ticks += 1
                    if healthy_ticks >= VERIFY_EVERY:
                        healthy_ticks = 0
                        restart_network = self._verify(device)
                        restart_reason = "network_check_failed" if restart_network else ""
            except Exception as exc:  # this loop must survive anything (WD-9)
                if repr(exc) != last_error:
                    logger.exception("Could not check or restore network on %s", device)
                last_error = repr(exc)
            else:
                last_error = ""
            finally:
                lock.release()

    def _verify(self, device: str) -> str:
        """Check and repair the network on `device` in place.

        Returns why the whole network must be restored, or "" when it need not.
        """
        try:
            repaired, restore = self.manager.verify_network(device)
        except (CommandError, DhcpServerError, RuntimeError) as exc:  # RuntimeError: no upstream, NAT
            logger.warning("Could not verify the network on %s: %s", device, exc)
            return ""
        if restore:
            return f"Network on {device} lost {', '.join(repaired)}"
        if repaired:
            logger.warning("Network on %s lost %s; repaired in place", device, ", ".join(repaired))
        return ""

    def state(self, reservation: Reservation) -> str | None:
        entry = self.states.get(reservation.device_id)
        return entry[1] if entry is not None and entry[0] is reservation else None

    def _cancelled(self, reservation: Reservation) -> bool:
        return self.stopping.is_set() or reservation.is_expired or reservation.release_requests > 0

    def forget(self, device: str) -> bool:
        """Stop retrying a failed restore; True if one was pending.

        Called when the client creates a network or deletes the failed one,
        so the watchdog never races the client for the antenna.
        """
        with self.manager.device_lock(device):
            return self._drop_pending(device)

    def _drop_pending(self, device: str) -> bool:
        pending = self._pending.pop(device, None)
        if pending is None:
            return False
        entry = self.states.get(device)
        if entry is not None and entry[1] == "restore_failed":
            self.states.pop(device, None)
        return True

    def _owe(
        self, reservation: Reservation, request: NetworkCreateRequest | None,
        band: str, channel: int, reason: object,
    ) -> None:
        """Report a failed restore and schedule a new attempt (WD-2)."""
        device = reservation.device_id
        self._pending[device] = _Pending(
            reservation, request, band, channel, next_try=time.monotonic() + RETRY_BACKOFF[0],
        )
        self.states[device] = (reservation, "restore_failed")
        if request is None:
            logger.error("AP restore failed on %s and cannot be retried: %s", device, reason)
        else:
            logger.warning(
                "AP restore failed on %s: %s; next attempt in %.0f s", device, reason, RETRY_BACKOFF[0],
            )

    def _retry_pending(self, reservations: ReservationManager, pending: _Pending) -> None:
        from .manager import StartupFailure

        reservation = pending.reservation
        device = reservation.device_id
        assert pending.request is not None
        try:
            self.manager.release_device(device)  # leftovers of the previous attempt
        except RuntimeError:
            logger.exception("Unsafe cleanup before AP restore retry on %s", device)
            self._drop_pending(device)
            self.manager.quarantine_radio(
                reservations, reservation, radio_fault=False, band=pending.band, channel=pending.channel,
            )
            return
        try:
            # A release during the restore stops it at once, like a create (REV-6).
            self.manager.start_network(
                device, pending.request, reservation.expires_at, allow_internal_retry=True,
                cancelled=lambda: self._cancelled(reservation),
            )
        except StartupFailure as exc:
            if exc.cleanup_failed or exc.radio:
                logger.warning("AP restore retry on %s failed: %s; quarantining", device, exc)
                self._drop_pending(device)
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=exc.radio,
                    band=pending.band, channel=pending.channel,
                )
                return
            self._fail_again(pending, exc)
            return
        except Exception as exc:  # ValueError, or anything unexpected (REV-1)
            if not isinstance(exc, ValueError):
                logger.exception("AP restore retry failed unexpectedly on %s", device)
            self._fail_again(pending, exc)
            return
        self._drop_pending(device)
        logger.warning("AP on %s restored after %d failed attempts", device, pending.failures)
        if self._cancelled(reservation):
            try:
                self.manager.release_device(device)
            except RuntimeError:
                logger.exception("Could not clean up cancelled AP restore on %s", device)
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=False, band=pending.band, channel=pending.channel,
                )

    def _fail_again(self, pending: _Pending, reason: object) -> None:
        pending.failures += 1
        delay = RETRY_BACKOFF[min(pending.failures - 1, len(RETRY_BACKOFF) - 1)]
        pending.next_try = time.monotonic() + delay
        logger.warning(
            "AP restore attempt %d on %s failed: %s; next attempt in %.0f s",
            pending.failures, pending.reservation.device_id, reason, delay,
        )

    def _restore_ap(
        self, reservations: ReservationManager, reservation: Reservation,
        status: NetworkStatus, budget_exhausted: bool,
    ) -> None:
        from .manager import StartupFailure

        device = reservation.device_id
        radio_known = status.band is not None and status.channel is not None
        band, channel = status.band or "", status.channel or 0
        if self._cancelled(reservation):
            return
        try:
            self.manager.release_device(device)
        except RuntimeError:
            logger.exception("Unsafe AP watchdog cleanup on %s", device)
            self.manager.quarantine_radio(
                reservations, reservation, radio_fault=radio_known, band=band, channel=channel,
            )
            return
        if self._cancelled(reservation):
            return
        if budget_exhausted:
            self.manager.quarantine_radio(
                reservations, reservation, radio_fault=radio_known, band=band, channel=channel,
            )
            return
        request: NetworkCreateRequest | None = None
        try:
            if not (radio_known and status.ssid and status.encryption and status.tx_power_level):
                raise ValueError("Missing original AP settings")
            request = NetworkCreateRequest(
                ssid=status.ssid, password=status.password, channel=channel,
                encryption=status.encryption, band=band, hidden=bool(status.hidden),
                internet_enabled=status.internet_enabled, captive_portal=status.captive_portal,
                tx_power_level=status.tx_power_level,
                channel_width=status.channel_width or 20,
                wifi_generation=status.wifi_generation or 4,
            )
            # Same internal retries as a create request (WD-2).
            self.manager.start_network(
                device, request, reservation.expires_at, allow_internal_retry=True,
                cancelled=lambda: self._cancelled(reservation),
            )
        except StartupFailure as exc:
            logger.warning("AP restart failed on %s: %s", device, exc)
            if exc.cleanup_failed or (exc.radio and not self._cancelled(reservation)):
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=exc.radio, band=band, channel=channel,
                )
            elif not self._cancelled(reservation):
                self._owe(reservation, request, band, channel, exc)
            return
        except Exception as exc:  # ValueError (settings), or anything unexpected (REV-1)
            if isinstance(exc, ValueError):
                logger.warning("AP restart failed on %s: %s", device, exc)
            else:
                logger.exception("AP restart failed unexpectedly on %s", device)
            if not self._cancelled(reservation):
                self._owe(reservation, request, band, channel, exc)
            return
        if self._cancelled(reservation):
            try:
                self.manager.release_device(device)
            except RuntimeError:
                logger.exception("Could not clean up cancelled AP restart on %s", device)
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=False, band=band, channel=channel,
                )

    def _restore_dhcp(
        self, reservations: ReservationManager, reservation: Reservation, status: NetworkStatus,
    ) -> None:
        device = reservation.device_id
        if self._cancelled(reservation) or status.subnet is None:
            return
        self.states[device] = (reservation, "restoring_dhcp")
        try:
            self.manager.dhcp_server.stop(device)
        except DhcpServerError:
            self._isolate_dhcp_failure(reservations, reservation)
            return
        try:
            if not self._cancelled(reservation):
                self.manager.dhcp_server.start(
                    device, status.interface, status.subnet, self.manager.config.dns_server,
                    **({"captive_dns": True} if status.captive_portal else {}),
                )
                if not self.manager.dhcp_server.is_running(device):
                    raise DhcpServerError("Restarted DHCP process is not running")
        except DhcpServerError:
            logger.exception("DHCP restart failed on %s", device)
            try:
                self.manager.dhcp_server.stop(device)
            except DhcpServerError:
                self._isolate_dhcp_failure(reservations, reservation)
                return
            self.states[device] = (reservation, "dhcp_failed")
        else:
            self.states.pop(device, None)

    def _isolate_dhcp_failure(
        self, reservations: ReservationManager, reservation: Reservation,
    ) -> None:
        device = reservation.device_id
        logger.exception("Unsafe DHCP watchdog cleanup on %s", device)
        try:
            self.manager.release_device(device)
        except RuntimeError:
            logger.exception("Could not fully tear down quarantined network on %s", device)
        self.states.pop(device, None)
        self.manager.quarantine_radio(
            reservations, reservation, radio_fault=False, band="", channel=0,
        )
