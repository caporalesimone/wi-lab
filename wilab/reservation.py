"""Device reservation management.

Tracks exclusive ownership windows for Wi-Lab devices.
Each reservation binds a device to a cryptographically secure token
for a specified duration.
"""

import secrets
import threading
import time
import logging
from _thread import RLock
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from typing import Dict, Optional

logger = logging.getLogger(__name__)

RESERVATION_TOKEN_BYTES = 4  # 8 hex chars


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
    expires_at: Optional[float]  # None = unlimited (no expiry)
    radio_failures: int = 0
    retry_at: float = 0.0
    release_requests: int = 0

    @property
    def expires_in(self) -> Optional[int]:
        """Seconds remaining until expiry (clamped to 0). None if unlimited."""
        if self.expires_at is None:
            return None
        return max(0, int(self.expires_at - time.time()))

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at


class ReservationManager:
    """In-memory reservation store with thread-safe operations."""

    def __init__(
        self,
        device_ids: list[str],
        cleanup: Callable[[str], None] | None = None,
        device_lock: Callable[[str], RLock] | None = None,
    ) -> None:
        self._device_ids = list(device_ids)
        self._reservations: Dict[str, Reservation] = {}   # reservation_id -> Reservation
        self._device_to_rid: Dict[str, str] = {}           # device_id -> reservation_id
        self._lock = threading.RLock()
        self._blocked: dict[str, bool] = {}
        self._own_locks: dict[str, RLock] | None = None
        if device_lock is None:
            self._own_locks = {device_id: threading.RLock() for device_id in device_ids}
            device_lock = self._own_locks.__getitem__
        self._device_lock = device_lock
        self._cleanup = cleanup

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self, duration_seconds: int) -> Reservation:
        """Reserve the first available device.

        Args:
            duration_seconds: How long to hold the reservation.

        Returns:
            The newly created Reservation.

        Raises:
            ValueError: If no device is available.
        """
        with self._lock:
            device_id = self._first_available()
            if device_id is not None:
                return self._reserve(device_id, duration_seconds)

        cleanup_error = self._purge_expired(continue_on_error=True)
        with self._lock:
            device_id = self._first_available()
            if device_id is not None:
                return self._reserve(device_id, duration_seconds)
            if cleanup_error is not None:
                raise cleanup_error
            if any(self._blocked.values()) or len(self._blocked) == len(self._device_ids):
                raise DeviceRecoveryUnavailable(any(self._blocked.values()))
            raise NoDeviceAvailableError(self._soonest_expiry())

    def quarantine(self, reservation: Reservation, *, recovering: bool) -> None:
        """Invalidate an owner and exclude its antenna in one store operation."""
        with self._device_lock(reservation.device_id), self._lock:
            if self._reservations.get(reservation.reservation_id) is not reservation:
                raise RuntimeError("Cannot quarantine a stale reservation")
            self._blocked[reservation.device_id] = recovering
            self._remove(reservation.reservation_id)

    def finish_recovery(self, device_id: str, *, recovered: bool) -> None:
        with self._lock:
            if recovered:
                self._blocked.pop(device_id, None)
            else:
                self._blocked[device_id] = False

    def recovery_snapshot(self) -> dict[str, bool]:
        with self._lock:
            return self._blocked.copy()

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

    def get(self, reservation_id: str) -> Optional[Reservation]:
        """Return reservation if still valid, else None."""
        with self._lock:
            r = self._reservations.get(reservation_id)
            if r is None or not r.is_expired:
                return r
        self._cleanup_expired(r)
        return None

    def delete(self, reservation_id: str) -> bool:
        """Release a reservation. Returns True if it existed."""
        with self._lock:
            reservation = self._reservations.get(reservation_id)
        return self._delete(reservation) if reservation is not None else False

    def _delete(self, reservation: Reservation) -> bool:
        reservation_id = reservation.reservation_id
        with self._lock:
            reservation.release_requests += 1
        try:
            with self._device_lock(reservation.device_id):
                with self._lock:
                    current = self._reservations.get(reservation_id)
                if current is not reservation:
                    return False
                expired = reservation.is_expired
                self._release(reservation)
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

    def device_for(self, reservation_id: str) -> Optional[str]:
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
        """Sweep expired reservations outside the request path."""
        self._purge_expired(continue_on_error=True)

    @contextmanager
    def hold(self, reservation_id: str) -> Iterator[Reservation | None]:
        """Keep a reservation valid against concurrent release while in use."""
        with self._lock:
            reservation = self._reservations.get(reservation_id)
        if reservation is None:
            yield None
            return
        with self._device_lock(reservation.device_id):
            with self._lock:
                current = self._reservations.get(reservation_id)
            yield reservation if current is reservation and not reservation.is_expired else None

    # ------------------------------------------------------------------
    # Store mutations use self._lock; cleanup runs only under the device lock.
    # Never wait for a device lock while holding self._lock.
    # ------------------------------------------------------------------

    def _first_available(self) -> Optional[str]:
        for did in self._device_ids:
            if did not in self._device_to_rid and did not in self._blocked:
                return did
        return None

    def _remove(self, reservation_id: str) -> None:
        r = self._reservations.pop(reservation_id, None)
        if r:
            self._device_to_rid.pop(r.device_id, None)

    def _release(self, reservation: Reservation) -> None:
        if self._cleanup is not None:
            try:
                self._cleanup(reservation.device_id)
            except Exception as exc:
                logger.exception("Failed to clean up device %s", reservation.device_id)
                raise ReservationCleanupError(
                    f"Failed to clean up device {reservation.device_id}"
                ) from exc
        with self._lock:
            self._remove(reservation.reservation_id)

    def _cleanup_expired(self, reservation: Reservation) -> None:
        lock = self._device_lock(reservation.device_id)
        if not lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                current = self._reservations.get(reservation.reservation_id)
            if current is reservation and reservation.is_expired:
                logger.info("Purging expired reservation for %s", reservation.device_id)
                self._release(reservation)
        finally:
            lock.release()

    def _purge_expired(
        self, *, continue_on_error: bool = False
    ) -> ReservationCleanupError | None:
        expired = [r for r in self.snapshot().values() if r.is_expired]
        first_error = None
        for reservation in expired:
            try:
                self._cleanup_expired(reservation)
            except ReservationCleanupError as exc:
                if not continue_on_error:
                    raise
                if first_error is None:
                    first_error = exc
        return first_error

    def _soonest_expiry(self) -> float | None:
        """Return the earliest expires_at among active reservations (excluding unlimited)."""
        timed = [r.expires_at for r in self._reservations.values() if r.expires_at is not None]
        if not timed:
            return None
        return min(timed)
