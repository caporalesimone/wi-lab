"""Bounded recovery of APs that fail after startup."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Literal

from .. import heartbeat, log
from ..models import NetworkCreateRequest
from ..network.commands import CommandError
from ..network.dhcp import DhcpServerError
from ..reservation import Reservation, ReservationManager
from .failures import FailureKind
from .hostapd import DFS_READY_TIMEOUT, Probe
from .interface import interface_present

if TYPE_CHECKING:
    from ..devices import Device
    from .active import ActiveNetwork
    from .manager import NetworkManager

logger = logging.getLogger(__name__)
# Repair budgets per adapter come from config.yaml (`watchdog:`, by default 3 in
# any 60 minutes, a driver may have its own): at most `limit` AP restores in the
# window, and the next failure inside it quarantines the adapter. DHCP restarts
# have their own budget (WD-3): when it is used up, or a DHCP restart fails, the
# watchdog restarts the whole network instead.
# Ticks (5 s each) between checks of what a running network needs beyond its
# processes: gateway address, firewall rules, captive portal (WD-7).
VERIFY_EVERY = 6
# Seconds between two ticks of one antenna, and the least time between two
# ticks when the hostapd control monitor wakes the watchdog early (PERF-4).
TICK = 5.0
WAKE_GAP = 0.5
# Probe misses that restart the AP, counted in half misses: hostapd answering
# "not ENABLED" (or not running) counts 2, a probe that timed out counts 1. So
# 3 real answers restart the AP, while only 6 slow probes in a row do (WD-10).
MISS_LIMIT = 6
# Delay before each new attempt after a restore that failed for a non-radio
# reason; the last value repeats while the reservation is valid.
RETRY_BACKOFF = (15.0, 30.0, 60.0, 120.0, 300.0)
# What the watchdog does when a restore (or a later restore attempt) fails, by
# kind (ARCH-2):
# - isolate: quarantine the adapter even if the reservation was released
#   meanwhile, since the rollback may have left processes or rules up
# - quarantine: quarantine the adapter; a restore cancelled meanwhile does
#   nothing instead (a later attempt of an owed network quarantines all the same)
# - retry_later: owe the network and try again after RETRY_BACKOFF
# A quarantine counts as a radio fault (USB recovery) when kind.radio.
# A failed cleanup with the adapter present is tried once more (REV-10, T-20):
# the owed retry starts with a cleanup, and only a second failure quarantines,
# without a USB reset. One xtables lock held by another tool no longer costs
# the client its reservation. If the release ends the reservation meanwhile,
# its own cleanup (with the WD-6 backoff) takes over the leftovers.
_ON_RESTORE_FAILURE: dict[FailureKind, Literal["isolate", "quarantine", "retry_later"]] = {
    FailureKind.CLEANUP_FAILED: "retry_later",
    FailureKind.RADIO_CLEANUP_FAILED: "isolate",
    FailureKind.TRANSIENT_RADIO: "quarantine",
    FailureKind.CONFIGURATION: "retry_later",
    FailureKind.CONFLICT: "retry_later",
}


@dataclass
class DeviceWatch:
    """What the watchdog remembers about one antenna between two ticks (Fable 4.1).

    The restore budgets belong to the adapter, so they are not reset when the
    client recreates the network.
    """

    device: str
    current: "ActiveNetwork | None" = None   # the network the counters below are about
    misses: int = 0                          # probe misses, in half misses (WD-10)
    restores: deque[float] = field(default_factory=deque)        # monotonic times of AP restores
    dhcp_restores: deque[float] = field(default_factory=deque)   # same, DHCP-only restarts (WD-3)
    restart_network: str = ""   # why the whole network must be restored on the next tick (WD-3, WD-7)
    restart_reason: str = ""    # the same, as the stable reason shown in GET .../network restarts
    healthy_ticks: int = 0      # since the last network check (WD-7)
    last_error: str = ""        # log a repeated failure's traceback once (WD-9)
    dfs_since: float | None = None   # monotonic start of a radar check after a radar event (REV-12)


@dataclass
class _Pending:
    """A network the watchdog still owes to its reservation after a failed restore."""

    reservation: Reservation
    request: NetworkCreateRequest
    band: str
    channel: int
    failures: int = 1
    next_try: float = 0.0


class _Stopping(threading.Event):
    """The watchdog's stop flag: setting it also wakes every watcher waiting for its tick."""

    def __init__(self, on_set: Callable[[], None]) -> None:
        super().__init__()
        self._on_set = on_set

    def set(self) -> None:
        super().set()
        self._on_set()


class NetworkWatchdog:
    def __init__(self, manager: "NetworkManager") -> None:
        self.manager = manager
        self._wakeups: dict[str, threading.Event] = {}
        self._watches: dict[str, DeviceWatch] = {}   # read by GET /antennas/{interface} (health)
        self._wakeups_lock = threading.Lock()
        self.stopping = _Stopping(self._wake_all)
        self.states: dict[str, tuple[Reservation, str]] = {}
        self._reservations: ReservationManager | None = None
        # device -> network owed after a failed restore; guarded by the device lock
        self._pending: dict[str, _Pending] = {}

    def start(self, reservations: ReservationManager) -> None:
        """Watch every managed device, and each one discovery adds later; once only."""
        if self._reservations is not None:
            return
        self._reservations = reservations
        self.manager.devices.subscribe(partial(self._start_watcher, reservations))

    def _start_watcher(self, reservations: ReservationManager, device: "Device") -> None:
        """One watcher thread per device (the registry calls this once per device)."""
        threading.Thread(
            target=self._watch, args=(reservations, device.device_id),
            name=f"ap-watchdog-{device.device_id}", daemon=True,
        ).start()

    def wake(self, device: str) -> None:
        """Run the next tick of *device* now, not at the end of its 5 s (PERF-4).

        Called by the hostapd control monitor when its connection is lost or
        hostapd reports AP-DISABLED: a crash is restored in about a second.
        """
        self._wakeup(device).set()

    def _wakeup(self, device: str) -> threading.Event:
        with self._wakeups_lock:
            return self._wakeups.setdefault(device, threading.Event())

    def _wake_all(self) -> None:
        with self._wakeups_lock:
            for event in self._wakeups.values():
                event.set()

    def _pause(self, device: str) -> bool:
        """Wait for the next tick of *device*; True when the watchdog stops.

        TICK seconds, or less when woken; a woken tick still waits WAKE_GAP after
        the previous one, so a burst of wake-ups cannot run ticks back to back.
        """
        wakeup = self._wakeup(device)
        if self.stopping.wait(WAKE_GAP):
            return True
        if wakeup.wait(TICK - WAKE_GAP):
            wakeup.clear()
        return self.stopping.is_set()

    def owes(self, device: str) -> bool:
        """True while a network is owed to a reservation after a failed restore."""
        return device in self._pending

    def retire(self, device: str) -> None:
        """Drop the counters of a retired device (WD-5); its watcher thread ends by itself."""
        self._watches.pop(device, None)
        self._pending.pop(device, None)
        self.states.pop(device, None)
        self.wake(device)

    def _watch(self, reservations: ReservationManager, device: str) -> None:
        log.bind(antenna=device)   # this thread watches one antenna for its whole life
        watch = self._watches.setdefault(device, DeviceWatch(device))
        me = self.manager.devices.get(device)
        while not self._pause(device):
            if self.manager.devices.get(device) is not me:
                # Retired (WD-5); if it came back, a new watcher started for it.
                heartbeat.forget(f"watchdog:{device}")
                return
            heartbeat.beat(f"watchdog:{device}")
            self.tick(reservations, watch)

    def tick(self, reservations: ReservationManager, watch: "DeviceWatch") -> None:
        """One check of one antenna: everything the watchdog remembers is in *watch*.

        Skipped when another operation holds the antenna. Never raises: the loop
        must survive anything (WD-9); a repeated failure logs its traceback once.
        """
        device = watch.device
        lock = self.manager.devices.lock(device)
        if not lock.acquire(blocking=False):
            return
        try:
            reservation = reservations.snapshot().get(device)
            with log.context(reservation=reservation.reservation_id if reservation is not None else None):
                self._tick(reservations, watch, reservation)
        except Exception as exc:  # this loop must survive anything (WD-9)
            if repr(exc) != watch.last_error:
                logger.exception("Could not check or restore network on %s", device)
            watch.last_error = repr(exc)
        else:
            watch.last_error = ""
        finally:
            lock.release()

    def _tick(
        self, reservations: ReservationManager, watch: "DeviceWatch", reservation: Reservation | None,
    ) -> None:
        device = watch.device
        status = self.manager.active.get(device)
        pending = self._pending.get(device)
        if pending is not None and (
            status is not None  # restored, or the client created a network itself
            or reservation is not pending.reservation  # released, expired or quarantined
            or self._cancelled(pending.reservation)
        ):
            self._drop_pending(device)
        elif pending is not None:
            if time.monotonic() >= pending.next_try:
                self._retry_pending(reservations, pending)
                watch.current, watch.misses = self.manager.active.get(device), 0
            return
        if reservation is None or status is None:
            self.states.pop(device, None)
        if status is not watch.current:
            self.states.pop(device, None)
            watch.current, watch.misses = status, 0
            watch.restart_network = watch.restart_reason = ""
        if status is None or reservation is None or self._cancelled(reservation):
            return
        if self.manager.stop_failed(device):
            # Half stopped on purpose: repairing it would undo the client's stop.
            return
        alive = self.manager.hostapd_manager.is_running(device)
        probe = self.manager.hostapd_manager.probe(device) if alive else Probe(False)
        if self._radar_check(watch, status, probe):
            return
        enabled = probe.enabled
        watch.misses = 0 if enabled else watch.misses + (1 if enabled is None else 2)
        if not alive or watch.misses >= MISS_LIMIT or watch.restart_network:
            self._restart(reservations, watch, reservation, status, alive)
        elif watch.misses == 0 and not self.manager.dhcp_server.is_running(device):
            self._repair_dhcp(reservations, watch, reservation, status)
        elif watch.misses == 0:
            if self.state(reservation) == "dhcp_failed":
                self.states.pop(device, None)
            watch.healthy_ticks += 1
            if watch.healthy_ticks >= VERIFY_EVERY:
                watch.healthy_ticks = 0
                watch.restart_network = self._verify(device)
                watch.restart_reason = "network_check_failed" if watch.restart_network else ""

    def _radar_check(self, watch: "DeviceWatch", status: "ActiveNetwork", probe: Probe) -> bool:
        """Follow a radar event on a DFS channel (REV-12); True while hostapd is in its radar check.

        A radar makes hostapd leave the channel: it moves to another one (the AP
        stays `ENABLED`) or runs a new radar check (`DFS`, up to DFS_READY_TIMEOUT).
        Neither is a fault: misses are not counted during the check, and the
        channel in use is what GET .../network shows. A check that lasts longer
        counts as misses again.
        """
        if probe.channel is not None and probe.channel != status.radio_channel:
            moved = probe.channel != status.channel
            if moved or status.radio_channel is not None:
                logger.warning(
                    "hostapd on %s moved from channel %d to %d (radar event)",
                    watch.device, status.radio_channel or status.channel, probe.channel,
                )
            status.radio_channel = probe.channel if moved else None
        if probe.state != "DFS":
            watch.dfs_since = None
            return False
        now = time.monotonic()
        if watch.dfs_since is None:
            watch.dfs_since = now
            logger.warning("hostapd on %s is checking for radar; waiting up to %.0f s", watch.device, DFS_READY_TIMEOUT)
        return now - watch.dfs_since < DFS_READY_TIMEOUT

    def _restart(
        self, reservations: ReservationManager, watch: "DeviceWatch", reservation: Reservation,
        status: "ActiveNetwork", alive: bool,
    ) -> None:
        """Restore the whole network through the AP budget (WD-1)."""
        device = watch.device
        if watch.restart_network:
            logger.warning("%s; restarting the network", watch.restart_network)
        if not alive:
            self.manager.hostapd_manager.report_exit(device)
        reservation.record_restart("ap", (
            "hostapd_not_running" if not alive
            else watch.restart_reason or (
                "hostapd_not_enabled" if watch.misses >= MISS_LIMIT else "network_check_failed"
            )
        ))
        watch.restart_network = watch.restart_reason = ""
        self.states[device] = (reservation, "restoring_ap")
        now = time.monotonic()
        limit, window = self._budget(device, "ap_restores")
        while watch.restores and now - watch.restores[0] > window:
            watch.restores.popleft()
        exhausted = len(watch.restores) >= limit
        if exhausted:
            logger.warning(
                "AP on %s failed again after %d restores in %.0f min; quarantining",
                device, len(watch.restores), window / 60,
            )
        else:
            logger.warning(
                "Restoring AP on %s (restore %d of %d in the last %.0f min)",
                device, len(watch.restores) + 1, limit, window / 60,
            )
        try:
            self._restore_ap(reservations, reservation, status, exhausted)
            watch.current = self.manager.active.get(device)
            watch.restores.append(now)
            watch.misses = 0
        finally:
            if self.states.get(device, (None, ""))[1] == "restoring_ap":
                self.states.pop(device, None)

    def _repair_dhcp(
        self, reservations: ReservationManager, watch: "DeviceWatch", reservation: Reservation,
        status: "ActiveNetwork",
    ) -> None:
        """Restart dnsmasq alone, within its own budget (WD-3)."""
        device = watch.device
        now = time.monotonic()
        limit, window = self._budget(device, "dhcp_restarts")
        while watch.dhcp_restores and now - watch.dhcp_restores[0] > window:
            watch.dhcp_restores.popleft()
        if len(watch.dhcp_restores) < limit:
            watch.dhcp_restores.append(now)
            logger.warning(
                "Restarting DHCP on %s (restart %d of %d in the last %.0f min)",
                device, len(watch.dhcp_restores), limit, window / 60,
            )
            reservation.record_restart("dhcp", "dnsmasq_not_running")
            self._restore_dhcp(reservations, reservation, status)
            failed = self.state(reservation) == "dhcp_failed"
        else:
            self.states[device] = (reservation, "dhcp_failed")
            failed = True
        # On the next tick, restore the whole network through the AP budget
        # (WD-1); dhcp_failed stays visible until then.
        if failed and reservations.snapshot().get(device) is reservation:
            watch.restart_network = f"DHCP on {device} cannot be repaired alone"
            watch.restart_reason = "dhcp_failed"

    def budget_use(self, device: str, kind: str) -> tuple[int, int, int, float | None]:
        """Repairs of *kind* in the window, the limit, the window in minutes, and when
        (wall time) the oldest of them leaves the window; for the health of GET /antennas/{interface}."""
        limit, window = self._budget(device, kind)
        watch = self._watches.get(device)
        times: list[float] = []
        if watch is not None:
            for _ in range(3):   # the watchdog thread may append meanwhile
                try:
                    times = list(watch.restores if kind == "ap_restores" else watch.dhcp_restores)
                    break
                except RuntimeError:
                    continue
        now = time.monotonic()
        recent = [t for t in times if now - t <= window]
        frees_at = time.time() + (min(recent) + window - now) if recent else None
        return len(recent), limit, int(window // 60), frees_at

    def _budget(self, device: str, kind: str) -> tuple[int, float]:
        """`limit` and window in seconds of *kind* for *device*, by its driver (config.yaml)."""
        managed = self.manager.devices.get(device)
        budget = self.manager.config.watchdog.budget(kind, managed.driver if managed is not None else None)
        return budget.limit, budget.window_minutes * 60.0

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
        with self.manager.devices.lock(device):
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
        self, reservation: Reservation, request: NetworkCreateRequest,
        band: str, channel: int, reason: object,
    ) -> None:
        """Report a failed restore and schedule a new attempt (WD-2)."""
        device = reservation.device_id
        self._pending[device] = _Pending(
            reservation, request, band, channel, next_try=time.monotonic() + RETRY_BACKOFF[0],
        )
        self.states[device] = (reservation, "restore_failed")
        logger.warning(
            "AP restore failed on %s: %s; next attempt in %.0f s", device, reason, RETRY_BACKOFF[0],
        )

    def _retry_pending(self, reservations: ReservationManager, pending: _Pending) -> None:
        from .manager import StartupFailure

        reservation = pending.reservation
        device = reservation.device_id
        try:
            self.manager.release_device(device)  # leftovers of the previous attempt
        except RuntimeError:
            # Second failed cleanup in a row: someone must look (ARCH-10). Radio
            # fault only if the adapter is gone (REV-10).
            logger.exception("Unsafe cleanup before AP restore retry on %s", device)
            self._drop_pending(device)
            self.manager.quarantine_radio(
                reservations, reservation, radio_fault=not interface_present(device),
                band=pending.band, channel=pending.channel,
            )
            return
        try:
            # A release during the restore stops it at once, like a create (REV-6).
            self.manager.start_network(
                device, pending.request, reservation.expires_at, allow_internal_retry=True,
                cancelled=lambda: self._cancelled(reservation),
            )
        except StartupFailure as exc:
            if _ON_RESTORE_FAILURE[exc.kind] != "retry_later":
                logger.warning("AP restore retry on %s failed: %s; quarantining", device, exc)
                self._drop_pending(device)
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=exc.kind.radio,
                    band=pending.band, channel=pending.channel,
                )
                return
            self._fail_again(pending, exc)
            return
        except Exception as exc:  # ValueError (unknown antenna, no subnet), or anything unexpected (REV-1)
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
        network: "ActiveNetwork", budget_exhausted: bool,
    ) -> None:
        from .manager import StartupFailure

        device = reservation.device_id
        band, channel = network.band, network.channel
        if self._cancelled(reservation):
            return
        try:
            self.manager.release_device(device)
        except RuntimeError as exc:
            if not interface_present(network.interface):
                # The adapter is gone under the network: a radio fault, USB recovery.
                logger.warning("AP watchdog cleanup on %s failed with the adapter gone", device, exc_info=True)
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=True, band=band, channel=channel,
                )
            elif not self._cancelled(reservation):
                # Not a radio fault (REV-10): the owed restore cleans up again first,
                # and quarantines (without USB reset) only if that fails too.
                logger.warning("AP watchdog cleanup on %s failed", device, exc_info=True)
                self._owe(reservation, network.restart_request(), band, channel, exc)
            return
        if self._cancelled(reservation):
            return
        if budget_exhausted:
            self.manager.quarantine_radio(
                reservations, reservation, radio_fault=True, band=band, channel=channel,
            )
            return
        # The create request as received, with the Internet access and TX power
        # level of the moment: no settings to rebuild or to find missing (ARCH-3).
        request = network.restart_request()
        try:
            # Same internal retries as a create request (WD-2).
            self.manager.start_network(
                device, request, reservation.expires_at, allow_internal_retry=True,
                cancelled=lambda: self._cancelled(reservation),
            )
        except StartupFailure as exc:
            logger.warning("AP restart failed on %s: %s", device, exc)
            action = _ON_RESTORE_FAILURE[exc.kind]
            if action == "isolate" or (action == "quarantine" and not self._cancelled(reservation)):
                self.manager.quarantine_radio(
                    reservations, reservation, radio_fault=exc.kind.radio, band=band, channel=channel,
                )
            elif not self._cancelled(reservation):
                self._owe(reservation, request, band, channel, exc)
            return
        except Exception as exc:  # ValueError (unknown antenna, no subnet), or anything unexpected (REV-1)
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
        self, reservations: ReservationManager, reservation: Reservation, status: "ActiveNetwork",
    ) -> None:
        device = reservation.device_id
        if self._cancelled(reservation) or status.subnet is None:
            return
        self.states[device] = (reservation, "restoring_dhcp")
        try:
            self.manager.dhcp_server.stop(device, keep_leases=True)
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
            # The next tick restores the whole network (WD-3): a WARNING (ARCH-10).
            logger.warning("DHCP restart failed on %s", device, exc_info=True)
            try:
                self.manager.dhcp_server.stop(device, keep_leases=True)
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
