"""Device reservation management.

Tracks exclusive ownership windows for Wi-Lab devices.
Each reservation binds a device to a cryptographically secure token
for a specified duration.
"""

import secrets
import threading
import time
import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)

RESERVATION_TOKEN_BYTES = 16  # 32 hex chars


class NoDeviceAvailableError(Exception):
    """All devices are currently reserved."""

    def __init__(self, next_available_at: float) -> None:
        self.next_available_at = next_available_at
        super().__init__("No device available")

    @property
    def next_available_in(self) -> int:
        return max(0, int(self.next_available_at - time.time()))


@dataclass
class Reservation:
    """Active device reservation."""
    reservation_id: str
    device_id: str
    duration_seconds: int
    created_at: float
    expires_at: float

    @property
    def expires_in(self) -> int:
        """Seconds remaining until expiry (clamped to 0)."""
        return max(0, int(self.expires_at - time.time()))

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


class ReservationManager:
    """In-memory reservation store with thread-safe operations."""

    def __init__(self, device_ids: list[str]) -> None:
        self._device_ids = list(device_ids)
        self._reservations: Dict[str, Reservation] = {}   # reservation_id -> Reservation
        self._device_to_rid: Dict[str, str] = {}           # device_id -> reservation_id
        self._lock = threading.Lock()

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
            self._purge_expired()

            device_id = self._first_available()
            if device_id is None:
                soonest = self._soonest_expiry()
                raise NoDeviceAvailableError(soonest)

            reservation_id = secrets.token_hex(RESERVATION_TOKEN_BYTES)
            now = time.time()
            reservation = Reservation(
                reservation_id=reservation_id,
                device_id=device_id,
                duration_seconds=duration_seconds,
                created_at=now,
                expires_at=now + duration_seconds,
            )
            self._reservations[reservation_id] = reservation
            self._device_to_rid[device_id] = reservation_id
            logger.info(
                "Reservation %s created for device %s (duration %ds)",
                reservation_id, device_id, duration_seconds,
            )
            return reservation

    def get(self, reservation_id: str) -> Optional[Reservation]:
        """Return reservation if still valid, else None."""
        with self._lock:
            r = self._reservations.get(reservation_id)
            if r is None:
                return None
            if r.is_expired:
                self._remove(reservation_id)
                return None
            return r

    def delete(self, reservation_id: str) -> bool:
        """Release a reservation. Returns True if it existed."""
        with self._lock:
            if reservation_id not in self._reservations:
                return False
            self._remove(reservation_id)
            logger.info("Reservation %s released", reservation_id)
            return True

    def device_for(self, reservation_id: str) -> Optional[str]:
        """Resolve reservation_id to device_id, or None if invalid/expired."""
        r = self.get(reservation_id)
        return r.device_id if r else None

    def all_active(self) -> list[Reservation]:
        """Return list of currently active (non-expired) reservations."""
        with self._lock:
            self._purge_expired()
            return list(self._reservations.values())

    def is_device_reserved(self, device_id: str) -> bool:
        """Check if a device is currently reserved."""
        with self._lock:
            self._purge_expired()
            return device_id in self._device_to_rid

    # ------------------------------------------------------------------
    # Internal helpers (caller must hold self._lock)
    # ------------------------------------------------------------------

    def _first_available(self) -> Optional[str]:
        for did in self._device_ids:
            if did not in self._device_to_rid:
                return did
        return None

    def _remove(self, reservation_id: str) -> None:
        r = self._reservations.pop(reservation_id, None)
        if r:
            self._device_to_rid.pop(r.device_id, None)

    def _purge_expired(self) -> None:
        expired = [rid for rid, r in self._reservations.items() if r.is_expired]
        for rid in expired:
            logger.info("Reservation %s expired, purging", rid)
            self._remove(rid)

    def _soonest_expiry(self) -> float:
        """Return the earliest expires_at among active reservations."""
        if not self._reservations:
            return time.time()
        return min(r.expires_at for r in self._reservations.values())
