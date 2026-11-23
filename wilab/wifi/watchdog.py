"""Bounded recovery of APs that fail after startup."""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import NetworkCreateRequest, NetworkStatus
from ..network.dhcp import DhcpServerError
from ..reservation import Reservation, ReservationManager

if TYPE_CHECKING:
    from .manager import NetworkManager

logger = logging.getLogger(__name__)
# AP restore budget per adapter: at most RESTORE_LIMIT restores in any RESTORE_WINDOW
# seconds. The next failure inside the window quarantines the adapter.
RESTORE_LIMIT = 3
RESTORE_WINDOW = 3600.0
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
        self.watch([device.device_id for device in self.manager.config.networks])

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
        attempted_dhcp = False
        while not self.stopping.wait(5):
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
                    attempted_dhcp = False
                if status is None or reservation is None or self._cancelled(reservation):
                    continue
                alive = self.manager.hostapd_manager.is_running(device)
                misses = 0 if alive and self.manager.hostapd_manager.is_enabled(device) else misses + 1
                if not alive or misses >= 3:
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
                    try:
                        self._restore_ap(reservations, reservation, status, exhausted)
                        current = self.manager.active.get(device)
                        restores.append(now)
                        misses = 0
                    finally:
                        if self.states.get(device, (None, ""))[1] == "restoring_ap":
                            self.states.pop(device, None)
                elif misses == 0 and not self.manager.dhcp_server.is_running(device):
                    if not attempted_dhcp:
                        attempted_dhcp = True
                        self._restore_dhcp(reservations, reservation, status)
                    else:
                        self.states[device] = (reservation, "dhcp_failed")
                elif misses == 0 and self.state(reservation) == "dhcp_failed":
                    self.states.pop(device, None)
            except (OSError, RuntimeError, ValueError):
                logger.exception("Could not check or restore network on %s", device)
            finally:
                lock.release()

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
            self.manager.start_network(
                device, pending.request, reservation.expires_at, allow_internal_retry=True,
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
        except ValueError as exc:
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
            )
            # Same internal retries as a create request (WD-2).
            self.manager.start_network(
                device, request, reservation.expires_at, allow_internal_retry=True,
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
        except ValueError as exc:
            logger.warning("AP restart failed on %s: %s", device, exc)
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
