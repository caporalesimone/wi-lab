"""Device reservation management.

Tracks exclusive ownership windows for Wi-Lab devices.
Each reservation binds a device to a cryptographically secure token
for a specified duration.
"""

import secrets
import threading
import time
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Union

from .config import Capability

logger = logging.getLogger(__name__)

RESERVATION_TOKEN_BYTES = 4  # 8 hex chars


class NoDeviceAvailableError(Exception):
    """All devices are currently reserved.

    ``next_available_at`` is None when every holder has an unlimited reservation: there
    is then no scheduled release to report, and claiming one would be a lie the client
    acts on (a countdown that fires immediately and retries into another refusal).
    """

    def __init__(self, next_available_at: Optional[float]) -> None:
        self.next_available_at = next_available_at
        super().__init__("No device available")

    @property
    def next_available_in(self) -> Optional[int]:
        if self.next_available_at is None:
            return None
        return max(0, int(self.next_available_at - time.time()))


class UnknownDeviceError(Exception):
    """A specific device was requested by name and Wi-Lab does not manage it."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"Unknown device '{device_id}'")


class CapabilityUnsatisfiableError(Exception):
    """No configured device can ever satisfy the request.

    Permanent, unlike :class:`NoDeviceAvailableError`: waiting does not add capabilities
    to the pool, so a client must change the request rather than retry it.

    Attributes:
        requested: The capability set that could not be satisfied.
        available: Capability ids present across ALL configured devices, free or not.
            Computed over the whole pool precisely because that is what makes the
            failure permanent.
        device_id: Set when a specific device was pinned and lacks the capabilities,
            so the API can say which device rather than talking about the pool.
        missing: The subset the pinned device does not provide.
    """

    def __init__(
        self,
        requested: Iterable[Capability],
        available: Iterable[str],
        device_id: Optional[str] = None,
        missing: Iterable[Capability] = (),
    ) -> None:
        self.requested: FrozenSet[Capability] = frozenset(requested)
        self.available: List[str] = sorted(available)
        self.device_id = device_id
        self.missing: FrozenSet[Capability] = frozenset(missing)
        super().__init__("No device provides the requested capabilities")


@dataclass(frozen=True)
class DeviceSpec:
    """A managed device and the capabilities it declares.

    ``index`` is the position in config.yaml. It is used as the selection tie-break so
    the outcome is reproducible and matches declaration order.
    """

    device_id: str
    capabilities: FrozenSet[Capability] = field(default_factory=frozenset)
    index: int = 0


@dataclass
class Reservation:
    """Active device reservation."""
    reservation_id: str
    device_id: str
    duration_seconds: int
    created_at: float
    expires_at: Optional[float]  # None = unlimited (no expiry)

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

    def __init__(self, devices: Sequence[Union[DeviceSpec, str]]) -> None:
        """Build the pool.

        Args:
            devices: Managed devices, in declaration order. A plain ``str`` is accepted
                and becomes a capability-less device; this keeps the many existing call
                sites that pass ``["dev0", "dev1"]`` working unchanged.

        ``Sequence[DeviceSpec | str]`` rather than ``list[DeviceSpec] | list[str]``:
        the union-of-lists form rejects a mixed list and narrows badly under mypy.
        """
        self._devices: List[DeviceSpec] = [
            d if isinstance(d, DeviceSpec)
            else DeviceSpec(device_id=d, capabilities=frozenset(), index=i)
            for i, d in enumerate(devices)
        ]
        self._by_id: Dict[str, DeviceSpec] = {d.device_id: d for d in self._devices}
        self._reservations: Dict[str, Reservation] = {}   # reservation_id -> Reservation
        self._device_to_rid: Dict[str, str] = {}           # device_id -> reservation_id
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        duration_seconds: int,
        required_capabilities: Iterable[Capability] = (),
        device_id: Optional[str] = None,
    ) -> Reservation:
        """Reserve the best matching device.

        Args:
            duration_seconds: How long to hold the reservation (0 = unlimited).
            required_capabilities: Capabilities the assigned device must provide.
                Empty means "no requirement".
            device_id: Pin a specific device instead of selecting one.

        Returns:
            The newly created Reservation.

        Raises:
            UnknownDeviceError: ``device_id`` is not managed by Wi-Lab.
            CapabilityUnsatisfiableError: No configured device provides the requested
                capabilities (permanent - retrying will not help).
            NoDeviceAvailableError: Matching devices exist but all are reserved
                (transient - ``next_available_at`` covers the matching subset only,
                or is None when every holder is unlimited).
        """
        required = frozenset(required_capabilities)
        with self._lock:
            self._purge_expired()

            if device_id is not None:
                chosen = self._resolve_pinned(device_id, required)
            else:
                chosen = self._resolve_best(required)

            reservation_id = secrets.token_hex(RESERVATION_TOKEN_BYTES)
            now = time.time()
            reservation = Reservation(
                reservation_id=reservation_id,
                device_id=chosen.device_id,
                duration_seconds=duration_seconds,
                created_at=now,
                expires_at=None if duration_seconds == 0 else now + duration_seconds,
            )
            self._reservations[reservation_id] = reservation
            self._device_to_rid[chosen.device_id] = reservation_id
            logger.info(
                "Reservation %s created for device %s (duration %ds, required %s, provides %s)",
                reservation_id, chosen.device_id, duration_seconds,
                sorted(c.value for c in required) or "-",
                sorted(c.value for c in chosen.capabilities) or "-",
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

    def delete_all(self) -> int:
        """Release all active reservations. Returns number removed."""
        with self._lock:
            self._purge_expired()
            count = len(self._reservations)
            self._reservations.clear()
            self._device_to_rid.clear()
            if count:
                logger.info("All reservations released (%d)", count)
            return count

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

    def _resolve_pinned(self, device_id: str, required: FrozenSet[Capability]) -> DeviceSpec:
        """Resolve an explicitly requested device, or raise the precise reason it cannot."""
        spec = self._by_id.get(device_id)
        if spec is None:
            raise UnknownDeviceError(device_id)
        missing = required - spec.capabilities
        if missing:
            raise CapabilityUnsatisfiableError(
                requested=required,
                available=self._all_capability_ids(),
                device_id=device_id,
                missing=missing,
            )
        if device_id in self._device_to_rid:
            # The ETA is this device's own expiry: the caller pinned it, so when some
            # other device frees up is irrelevant to them.
            raise NoDeviceAvailableError(self._soonest_expiry(among={device_id}))
        return spec

    def _resolve_best(self, required: FrozenSet[Capability]) -> DeviceSpec:
        """Select the least capable device that satisfies `required`, or raise."""
        matching = [d for d in self._devices if required <= d.capabilities]
        if not matching:
            # Nothing in the pool can ever serve this: permanent, not a capacity problem.
            raise CapabilityUnsatisfiableError(
                requested=required,
                available=self._all_capability_ids(),
            )
        chosen = self._select(required)
        if chosen is None:
            # Matching devices exist but are all busy. The ETA must cover only those:
            # a 2.4-only antenna freeing up in 30s is no use to a 5 GHz request.
            raise NoDeviceAvailableError(
                self._soonest_expiry(among={d.device_id for d in matching})
            )
        return chosen

    def _select(self, required: FrozenSet[Capability]) -> Optional[DeviceSpec]:
        """Least capable free device satisfying `required`; None if none is free.

        Minimality is a preference, never a filter: an over-capable device is used when
        it is the only one free. Ranking by surplus first and declaration index second
        keeps scarce multi-band hardware for requests that actually need it, while
        staying reproducible.

        The index is redundant with min()'s "first minimal element" guarantee today. It
        is stated anyway so the tie-break is an intentional, testable property rather
        than an accident of CPython, and so it survives a later change to sorted().
        """
        candidates = [
            d for d in self._devices
            if d.device_id not in self._device_to_rid and required <= d.capabilities
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda d: (len(d.capabilities - required), d.index))

    def _all_capability_ids(self) -> Set[str]:
        """Capability ids across the whole pool, free or not."""
        return {c.value for d in self._devices for c in d.capabilities}

    def _remove(self, reservation_id: str) -> None:
        r = self._reservations.pop(reservation_id, None)
        if r:
            self._device_to_rid.pop(r.device_id, None)

    def _purge_expired(self) -> None:
        expired = [rid for rid, r in self._reservations.items() if r.is_expired]
        for rid in expired:
            logger.info("Reservation %s expired, purging", rid)
            self._remove(rid)

    def _soonest_expiry(self, among: Optional[Set[str]] = None) -> Optional[float]:
        """Earliest expires_at among active reservations, or None if all are unlimited.

        Args:
            among: Restrict to reservations holding these devices. Callers pass the set
                that could actually serve the request, so the ETA describes a device the
                client can really use.

        Returning time.time() for the all-unlimited case (as this did) tells the client
        "available now" about a pool nothing is scheduled to leave.
        """
        timed = [
            r.expires_at for r in self._reservations.values()
            if r.expires_at is not None and (among is None or r.device_id in among)
        ]
        if not timed:
            return None
        return min(timed)
