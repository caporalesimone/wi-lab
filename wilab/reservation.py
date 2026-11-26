"""Device reservation management.

Tracks exclusive ownership windows for Wi-Lab devices.
Each reservation binds a device to a cryptographically secure token
for a specified duration.
"""

import logging
import secrets
import threading
import time
from _thread import RLock
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RESERVATION_TOKEN_BYTES = 4  # 8 hex chars

# Why a reservation ID ended, kept ENDED_TTL seconds so that every call with the
# ID answers 404 with this reason. The values are part of the API contract.
RELEASED = "reservation_released"
EXPIRED = "reservation_expired"
INVALIDATED = "reservation_invalidated"
NOT_FOUND = "reservation_not_found"   # never existed, or ended more than ENDED_TTL ago
ENDED_TTL = 3600.0


class NoDeviceAvailableError(Exception):
    """All devices are currently reserved."""

    def __init__(self, next_available_at: float | None) -> None:
        self.next_available_at = next_available_at
        super().__init__("No device available")

    @property
    def next_available_in(self) -> int | None:
        if self.next_available_at is None:
            return None
        return max(0, int(self.next_available_at - time.time()))


class ReservationCleanupError(Exception):
    """A device could not be safely released."""


class UnknownDeviceError(ValueError):
    """No managed device has the requested interface."""


class DeviceRecoveryUnavailable(Exception):
    """No device can be allocated because of recovery or quarantine."""

    def __init__(self, recovering: bool) -> None:
        self.recovering = recovering
        super().__init__("No device available during recovery" if recovering else "Devices unavailable")


@dataclass
class Reservation:
    """Active device reservation."""
    reservation_id: str
    device_id: str
    duration_seconds: int
    created_at: float
    expires_at: float | None  # None = unlimited (no expiry)
    release_requests: int = 0
    # Watchdog repairs over the whole reservation: they only grow, so a client
    # compares them before and after a test even if it recreated the network.
    ap_restarts: int = 0
    dhcp_restarts: int = 0
    last_restart_at: float | None = None
    last_restart_reason: str | None = None

    def record_restart(self, kind: str, reason: str) -> None:
        """Count a watchdog repair: `ap` (clients disconnected) or `dhcp`."""
        if kind == "ap":
            self.ap_restarts += 1
        else:
            self.dhcp_restarts += 1
        self.last_restart_at = time.time()
        self.last_restart_reason = reason

    @property
    def expires_in(self) -> int | None:
        """Seconds remaining until expiry (clamped to 0). None if unlimited."""
        if self.expires_at is None:
            return None
        return max(0, int(self.expires_at - time.time()))

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at


class DeviceBusyError(Exception):
    """Another operation on this device is still running (RACE-1)."""

    def __init__(self, device_id: str) -> None:
        super().__init__(f"Another operation on {device_id} is still running")
        self.device_id = device_id


class ReservationManager:
    """In-memory reservation store with thread-safe operations."""

    def __init__(
        self,
        device_ids: list[str],
        cleanup: Callable[[str], None] | None = None,
        device_lock: Callable[[str], RLock] | None = None,
        cleanup_due: Callable[[str], bool] | None = None,
        cleanup_wait: Callable[[str], float] | None = None,
        before_release: Callable[[str], object] | None = None,
        on_expiry: Callable[[str], object] | None = None,
    ) -> None:
        self._device_ids = list(device_ids)
        self._reservations: dict[str, Reservation] = {}   # reservation_id -> Reservation
        self._device_to_rid: dict[str, str] = {}           # device_id -> reservation_id
        self._lock = threading.RLock()
        self._blocked: dict[str, bool] = {}
        self._own_locks: dict[str, RLock] | None = None
        if device_lock is None:
            self._own_locks = {device_id: threading.RLock() for device_id in device_ids}
            device_lock = self._own_locks.__getitem__
        self._device_lock = device_lock
        self._cleanup = cleanup
        # WD-6: background sweeps skip a device whose failed cleanup is backing off.
        self._cleanup_due = cleanup_due or (lambda _device: True)
        # Seconds until the next background cleanup of a device whose cleanup failed.
        self._cleanup_wait = cleanup_wait or (lambda _device: 0.0)
        # Cancels an AP start in progress, which holds the device lock, so that a
        # release never waits for a long start (asynchronous create).
        self._before_release = before_release or (lambda _device: None)
        self._on_expiry = on_expiry or (lambda _device: None)
        self._failing_cleanup: set[str] = set()  # log the traceback once per failure series
        self._ended: dict[str, tuple[str, float]] = {}  # reservation_id -> (reason, monotonic)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, duration_seconds: int, device_id: str | None = None) -> Reservation:
        """Reserve *device_id*, or the first available device when it is None.

        Raises:
            UnknownDeviceError: *device_id* is not a managed device.
            NoDeviceAvailableError: every device (or *device_id*) is reserved, or
                held by a cleanup that failed and is retried in the background.
            DeviceRecoveryUnavailable: the devices (or *device_id*) are quarantined.
        """
        if device_id is not None:
            return self._create_on(device_id, duration_seconds)
        with self._lock:
            device_id = self._first_available()
            if device_id is not None:
                return self._reserve(device_id, duration_seconds)

        # A failed cleanup keeps its device held; the background sweep repeats it.
        self._purge_expired(continue_on_error=True, background=True)
        with self._lock:
            device_id = self._first_available()
            if device_id is not None:
                return self._reserve(device_id, duration_seconds)
            if any(self._blocked.values()) or len(self._blocked) == len(self._device_ids):
                raise DeviceRecoveryUnavailable(any(self._blocked.values()))
            raise NoDeviceAvailableError(self._soonest_expiry())

    def _create_on(self, device_id: str, duration_seconds: int) -> Reservation:
        """Reserve one given device; an expired owner is cleaned up first."""
        with self._lock:
            if device_id not in self._device_ids:
                raise UnknownDeviceError(device_id)
        for _ in range(2):
            with self._lock:
                if device_id in self._blocked:
                    raise DeviceRecoveryUnavailable(self._blocked[device_id])
                owner_id = self._device_to_rid.get(device_id)
                if owner_id is None:
                    return self._reserve(device_id, duration_seconds)
                owner = self._reservations[owner_id]
                if not owner.is_expired:
                    raise NoDeviceAvailableError(owner.expires_at)
            try:
                # Returns at once if another call holds the device, or if a failed
                # cleanup is waiting for its next background attempt.
                self._cleanup_expired(owner, background=True)
            except ReservationCleanupError:
                # Held until the background sweep cleans it: try again then.
                raise NoDeviceAvailableError(time.time() + self._cleanup_wait(device_id)) from None
        # Still held by the expired owner: free at its next cleanup, never in the past.
        raise NoDeviceAvailableError(time.time() + self._cleanup_wait(device_id))

    def quarantine(self, reservation: Reservation, *, recovering: bool) -> None:
        """Invalidate an owner and exclude its antenna in one store operation."""
        with self._device_lock(reservation.device_id), self._lock:
            if self._reservations.get(reservation.reservation_id) is not reservation:
                raise RuntimeError("Cannot quarantine a stale reservation")
            self._blocked[reservation.device_id] = recovering
            self._remove(reservation.reservation_id, INVALIDATED)

    def finish_recovery(self, device_id: str, *, recovered: bool) -> None:
        with self._lock:
            if recovered:
                self._blocked.pop(device_id, None)
            else:
                self._blocked[device_id] = False

    def recovery_snapshot(self) -> dict[str, bool]:
        with self._lock:
            return self._blocked.copy()

    def is_idle(self) -> bool:
        """No valid reservation and no USB recovery running.

        Reads without the store lock, so a stalled lock holder cannot block the
        check that decides whether Wi-Lab may restart itself (STAB-1). An
        expired reservation that was not purged yet counts as gone.
        """
        for _ in range(3):
            try:
                reservations = list(self._reservations.values())
                recovering = any(list(self._blocked.values()))
            except RuntimeError:  # dict changed during the copy; read again
                continue
            return not recovering and all(r.is_expired for r in reservations)
        return False

    def add_devices(self, device_ids: list[str]) -> None:
        """Make newly discovered devices allocatable; known devices are ignored."""
        with self._lock:
            for device_id in device_ids:
                if device_id in self._device_ids:
                    continue
                if self._own_locks is not None:
                    self._own_locks.setdefault(device_id, threading.RLock())
                self._device_ids.append(device_id)

    def _reserve(self, device_id: str, duration_seconds: int) -> Reservation:
        reservation_id = secrets.token_hex(RESERVATION_TOKEN_BYTES)
        while reservation_id in self._reservations:
            reservation_id = secrets.token_hex(RESERVATION_TOKEN_BYTES)
        now = time.time()
        reservation = Reservation(
            reservation_id=reservation_id,
            device_id=device_id,
            duration_seconds=duration_seconds,
            created_at=now,
            expires_at=None if duration_seconds == 0 else now + duration_seconds,
        )
        self._reservations[reservation_id] = reservation
        self._device_to_rid[device_id] = reservation_id
        logger.info("Reservation created for device %s (duration %ds)", device_id, duration_seconds)
        return reservation

    def get(self, reservation_id: str) -> Reservation | None:
        """Return reservation if still valid, else None."""
        with self._lock:
            r = self._reservations.get(reservation_id)
            if r is None or not r.is_expired:
                return r
        try:
            # A cleanup that already failed is repeated by the background sweep only.
            self._cleanup_expired(r, background=True)
        except ReservationCleanupError:
            pass  # logged by _release; the background sweep repeats it
        return None

    def delete(self, reservation_id: str, reason: str = RELEASED) -> bool:
        """Release a reservation. Returns True if it existed."""
        with self._lock:
            reservation = self._reservations.get(reservation_id)
        return self._delete(reservation, reason) if reservation is not None else False

    def ended_reason(self, reservation_id: str) -> str:
        """Why *reservation_id* is no longer valid: one of the reason constants."""
        with self._lock:
            self._prune_ended()
            ended = self._ended.get(reservation_id)
            if ended is not None:
                return ended[0]
            current = self._reservations.get(reservation_id)
            return EXPIRED if current is not None and current.is_expired else NOT_FOUND

    def _end(self, reservation_id: str, reason: str) -> None:
        """Remember why the ID ended; the first reason wins. Call under self._lock."""
        self._prune_ended()
        self._ended.setdefault(reservation_id, (reason, time.monotonic()))

    def _prune_ended(self) -> None:
        limit = time.monotonic() - ENDED_TTL
        for rid in [rid for rid, (_, at) in self._ended.items() if at < limit]:
            del self._ended[rid]

    def _delete(self, reservation: Reservation, reason: str = RELEASED) -> bool:
        reservation_id = reservation.reservation_id
        with self._lock:
            reservation.release_requests += 1
        try:
            self._before_release(reservation.device_id)
            with self._device_lock(reservation.device_id):
                with self._lock:
                    current = self._reservations.get(reservation_id)
                if current is not reservation:
                    return False
                expired = reservation.is_expired
                try:
                    self._release(reservation, EXPIRED if expired else reason)
                except ReservationCleanupError:
                    # The release never fails for the client: the ID is gone, the
                    # device stays held (not allocatable) and the background sweep
                    # repeats the cleanup with backoff (WD-6).
                    with self._lock:
                        if not expired:
                            self._end(reservation_id, reason)
                        reservation.expires_at = time.time()
                    logger.warning(
                        "Reservation %s released; cleanup of %s failed and is retried in the background",
                        reservation_id, reservation.device_id,
                    )
                    return not expired
                if expired:
                    return False
                logger.info("Reservation %s released", reservation_id)
                return True
        finally:
            with self._lock:
                reservation.release_requests -= 1

    def delete_all(self) -> int:
        """Release all active reservations. Returns number removed."""
        count = 0
        for reservation in self.snapshot().values():
            count += self._delete(reservation)
        return count

    def device_for(self, reservation_id: str) -> str | None:
        """Resolve reservation_id to device_id, or None if invalid/expired."""
        r = self.get(reservation_id)
        return r.device_id if r else None

    def all_active(self) -> list[Reservation]:
        """Return list of currently active (non-expired) reservations."""
        self._purge_expired()
        return [r for r in self.snapshot().values() if not r.is_expired]

    def is_device_reserved(self, device_id: str) -> bool:
        """Check if a device is currently reserved."""
        self._purge_expired()
        return device_id in self.snapshot()

    def snapshot(self) -> dict[str, Reservation]:
        """Report occupied devices, including those still awaiting cleanup."""
        with self._lock:
            return {r.device_id: r for r in self._reservations.values()}

    def expire(self) -> None:
        """Sweep expired reservations outside the request path.

        Devices whose cleanup failed are skipped until their backoff ends (WD-6).
        """
        self._purge_expired(continue_on_error=True, background=True)

    @contextmanager
    def hold(self, reservation_id: str, timeout: float | None = None) -> Iterator[Reservation | None]:
        """Keep a reservation valid against concurrent release while in use.

        With `timeout`, wait at most that long for the device lock and raise
        `DeviceBusyError` instead of parking the caller behind a slow operation
        (RACE-1). Without it, wait until the lock is free.
        """
        with self._lock:
            reservation = self._reservations.get(reservation_id)
        if reservation is None:
            yield None
            return
        lock = self._device_lock(reservation.device_id)
        if not lock.acquire(timeout=-1 if timeout is None else timeout):
            raise DeviceBusyError(reservation.device_id)
        try:
            with self._lock:
                current = self._reservations.get(reservation_id)
            yield reservation if current is reservation and not reservation.is_expired else None
        finally:
            lock.release()

    # ------------------------------------------------------------------
    # Store mutations use self._lock; cleanup runs only under the device lock.
    # Never wait for a device lock while holding self._lock.
    # ------------------------------------------------------------------

    def _first_available(self) -> str | None:
        for did in self._device_ids:
            if did not in self._device_to_rid and did not in self._blocked:
                return did
        return None

    def _remove(self, reservation_id: str, reason: str) -> None:
        r = self._reservations.pop(reservation_id, None)
        if r:
            self._device_to_rid.pop(r.device_id, None)
            self._end(reservation_id, reason)

    def _release(self, reservation: Reservation, reason: str) -> None:
        device = reservation.device_id
        if self._cleanup is not None:
            try:
                self._cleanup(device)
            except Exception as exc:
                if device in self._failing_cleanup:
                    logger.warning("Failed to clean up device %s again: %s", device, exc)
                else:
                    self._failing_cleanup.add(device)
                    logger.exception("Failed to clean up device %s", device)
                raise ReservationCleanupError(
                    f"Failed to clean up device {device}"
                ) from exc
        self._failing_cleanup.discard(device)
        with self._lock:
            self._remove(reservation.reservation_id, reason)

    def _cleanup_expired(self, reservation: Reservation, *, background: bool = False) -> None:
        if background and not self._cleanup_due(reservation.device_id):
            return
        # REV-11 point 3: forget a finished start (start_failed) now, not when the
        # next reservation on this device makes a call. A running start is not
        # cancelled here: it holds the device lock and ends on its own.
        self._on_expiry(reservation.device_id)
        lock = self._device_lock(reservation.device_id)
        if not lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                current = self._reservations.get(reservation.reservation_id)
            if current is reservation and reservation.is_expired:
                logger.info("Purging expired reservation for %s", reservation.device_id)
                self._release(reservation, EXPIRED)
        finally:
            lock.release()

    def _purge_expired(
        self, *, continue_on_error: bool = False, background: bool = False,
    ) -> ReservationCleanupError | None:
        expired = [r for r in self.snapshot().values() if r.is_expired]
        first_error = None
        for reservation in expired:
            try:
                self._cleanup_expired(reservation, background=background)
            except ReservationCleanupError as exc:
                if not continue_on_error:
                    raise
                if first_error is None:
                    first_error = exc
        return first_error

    def _soonest_expiry(self) -> float | None:
        """When a device should be free: the earliest expiry, or next cleanup of an expired one."""
        now = time.time()
        timed = [
            now + self._cleanup_wait(r.device_id) if r.is_expired else r.expires_at
            for r in self._reservations.values() if r.expires_at is not None
        ]
        return min(timed) if timed else None
