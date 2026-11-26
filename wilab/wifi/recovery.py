"""Quarantined Wi-Fi adapter recovery."""

import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .. import heartbeat
from ..network.commands import CommandError, execute_command, execute_iw
from .interface import interface_present

if TYPE_CHECKING:
    from ..reservation import ReservationManager
    from .manager import NetworkManager

logger = logging.getLogger(__name__)
RESET_ATTEMPTS = 10
RESET_INTERVAL = 60
# Re-probe of quarantined adapters with no recovery running ("unavailable"):
# delay before each attempt, the last value repeats forever.
REPROBE_DELAYS = (30.0, 60.0, 120.0, 300.0, 600.0, 900.0)
REPROBE_TICK = 5.0
DEFAULT_PROBE_RADIO = ("2.4ghz", 6)


def _usb_target(interface: str, port: str) -> tuple[str, str]:
    link = Path("/sys/class/net") / interface
    function = (link / "device").resolve(strict=True)
    device = (Path("/sys/bus/usb/devices") / port).resolve(strict=True)
    if function.parent != device or function.name != f"{port}:1.0":
        raise CommandError("Interface does not match the authorized USB port")
    if (device / "bDeviceClass").read_text().strip() == "09":
        raise CommandError("USB hubs cannot be reset")
    functions = [p for p in device.iterdir() if p.name.startswith(f"{port}:")]
    if set(functions) != {function} or {p.name for p in (function / "net").iterdir()} != {interface}:
        raise CommandError("USB device is not dedicated to this Wi-Fi interface")
    bus = int((device / "busnum").read_text())
    address = int((device / "devnum").read_text())
    if not (1 <= bus <= 999 and 1 <= address <= 127):
        raise CommandError("Invalid USB bus or device number")
    return f"{bus:03d}/{address:03d}", (link / "address").read_text().strip()


def _require_not_upstream(interface: str) -> None:
    for family in ("-4", "-6"):
        routes = json.loads(execute_command(["ip", "-j", family, "route", "show", "default"]))
        if any(route.get("dev") == interface for route in routes):
            raise CommandError("Cannot reset an upstream interface")


def _quiesce(interface: str) -> None:
    """Bring the radio down before a check.

    A USB re-enumeration creates a new device; systemd-networkd leaves it alone
    through the rule of ``wilab.network.unmanaged``, but it may come up again.
    """
    _require_not_upstream(interface)
    execute_command(["ip", "link", "set", "dev", interface, "down"])


def _require_idle(interface: str) -> None:
    link = json.loads(execute_command(["ip", "-j", "link", "show", "dev", interface]))
    info = execute_iw(["dev", interface, "info"])
    if len(link) != 1 or "UP" in link[0]["flags"] or "type managed" not in {
        line.strip() for line in info.splitlines()
    }:
        raise CommandError("Recovery requires an idle managed/DOWN interface")
    _require_not_upstream(interface)


class RadioRecovery:
    def __init__(self, manager: "NetworkManager") -> None:
        self._manager = manager
        self._stopping = threading.Event()
        # device -> (failed re-probes, monotonic time of the next attempt)
        self._reprobe: dict[str, tuple[int, float]] = {}
        # device -> (band, channel) of the last network, used for the probe AP
        self._last_radio: dict[str, tuple[str, int]] = {}
        self._reprobe_started = False

    def stop(self) -> None:
        self._stopping.set()

    def remember_radio(self, device: str, band: str, channel: int) -> None:
        if band in ("2.4ghz", "5ghz") and channel > 0:
            self._last_radio[device] = (band, channel)

    def start_reprobe(self, reservations: "ReservationManager") -> None:
        """Start the background loop that gives unavailable adapters another chance."""
        if self._reprobe_started:
            return
        self._reprobe_started = True

        def loop() -> None:
            while not self._stopping.wait(REPROBE_TICK):
                heartbeat.beat("reprobe")
                try:
                    self.reprobe_unavailable(reservations)
                except Exception:
                    # Never let one unexpected error end the loop for good.
                    logger.exception("Re-probe of unavailable adapters failed")

        threading.Thread(target=loop, name="unavailable-reprobe", daemon=True).start()

    def reprobe_unavailable(self, reservations: "ReservationManager", now: float | None = None) -> None:
        """Probe each adapter that is quarantined with no recovery running, with backoff.

        Covers every way to become "unavailable": a failed cleanup, a non-USB
        or non-radio fault, an upstream-free adapter whose USB recovery was
        exhausted, or an adapter that disconnected and came back. A successful
        AP + DHCP probe makes the adapter allocatable again without a service
        restart.
        """
        now = time.monotonic() if now is None else now
        snapshot = reservations.recovery_snapshot()
        for device in list(self._reprobe):
            if snapshot.get(device) is not False:
                # Recovered, or a USB recovery is running again: restart the backoff later.
                del self._reprobe[device]
        for device, recovering in snapshot.items():
            if recovering or self._stopping.is_set():
                continue
            failures, due = self._reprobe.setdefault(device, (0, now + REPROBE_DELAYS[0]))
            if now < due:
                continue
            if self._probe_unavailable(device):
                self._reprobe.pop(device, None)
                reservations.finish_recovery(device, recovered=True)
                logger.warning("Adapter %s passed the probe and is allocatable again", device)
                continue
            failures += 1
            delay = REPROBE_DELAYS[min(failures, len(REPROBE_DELAYS) - 1)]
            self._reprobe[device] = (failures, now + delay)
            logger.info(
                "Adapter %s still unavailable after re-probe %d; next attempt in %.0f s",
                device, failures, delay,
            )

    def _probe_unavailable(self, device: str) -> bool:
        if not interface_present(device):
            logger.info("Adapter %s is not present; re-probe skipped", device)
            return False
        band, channel = self._last_radio.get(device, DEFAULT_PROBE_RADIO)
        with self._manager.device_lock(device):
            if self._stopping.is_set():
                return False
            try:
                self._manager.release_device(device)  # finish any pending cleanup
                _quiesce(device)
                _require_idle(device)
                self._manager.probe_recovered_radio(device, band, channel)
                _quiesce(device)
                _require_idle(device)
            except (CommandError, OSError, ValueError, RuntimeError, KeyError) as exc:
                logger.info("Re-probe of %s failed: %s", device, exc)
                return False
        return not self._stopping.is_set()

    def schedule(
        self, reservations: "ReservationManager", interface: str, port: str, band: str, channel: int,
    ) -> None:
        threading.Thread(
            target=self._recover, args=(reservations, interface, port, band, channel),
            name=f"usb-recovery-{interface}", daemon=True,
        ).start()

    def _recover(
        self, reservations: "ReservationManager", interface: str, port: str, band: str, channel: int,
    ) -> None:
        recovered = False
        mac: str | None = None
        try:
            for attempt in range(1, RESET_ATTEMPTS + 1):
                if self._stopping.is_set() or (attempt > 1 and self._stopping.wait(RESET_INTERVAL)):
                    return
                with self._manager.device_lock(interface):
                    if self._stopping.is_set():
                        return
                    try:
                        self._manager.release_device(interface)
                        _quiesce(interface)
                        _require_idle(interface)
                        target, current_mac = _usb_target(interface, port)
                        if mac is not None and current_mac != mac:
                            raise CommandError("USB adapter identity changed")
                        mac = current_mac
                        logger.warning("USB recovery attempt %d/%d for %s", attempt, RESET_ATTEMPTS, interface)
                        execute_command(["usbreset", target], timeout=15)
                        if self._verify(interface, port, mac):
                            if self._stopping.is_set():
                                return
                            self._manager.probe_recovered_radio(interface, band, channel)
                            _quiesce(interface)
                            _require_idle(interface)
                            if self._stopping.is_set():
                                return
                            recovered = True
                            logger.info("USB recovery verified for %s", interface)
                            return
                    except (CommandError, OSError, ValueError, RuntimeError, KeyError) as e:
                        logger.warning("USB recovery attempt %d for %s failed: %s", attempt, interface, e)
        finally:
            reservations.finish_recovery(interface, recovered=recovered)
            if not recovered and not self._stopping.is_set():
                logger.error("USB recovery exhausted for %s; adapter remains quarantined", interface)

    def _verify(self, interface: str, port: str, mac: str) -> bool:
        for _ in range(20):
            if self._stopping.wait(0.5):
                return False
            try:
                _, current_mac = _usb_target(interface, port)
            except FileNotFoundError:
                continue
            if current_mac != mac:
                raise CommandError("USB adapter identity changed after reset")
            _quiesce(interface)
            execute_iw(["dev", interface, "set", "type", "managed"])
            try:
                execute_command(["ip", "link", "set", "dev", interface, "up"])
            finally:
                execute_command(["ip", "link", "set", "dev", interface, "down"])
            _quiesce(interface)
            _require_idle(interface)
            return True
        raise CommandError("USB adapter did not reappear")
