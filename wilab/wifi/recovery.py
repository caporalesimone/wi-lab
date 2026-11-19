"""Quarantined Wi-Fi adapter recovery."""

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ..network.commands import CommandError, execute_command, execute_iw

if TYPE_CHECKING:
    from ..reservation import ReservationManager
    from .manager import NetworkManager

logger = logging.getLogger(__name__)
RESET_ATTEMPTS = 10
RESET_INTERVAL = 60


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


def _require_idle(interface: str) -> None:
    link = json.loads(execute_command(["ip", "-j", "link", "show", "dev", interface]))
    info = execute_iw(["dev", interface, "info"])
    if len(link) != 1 or "UP" in link[0]["flags"] or "type managed" not in {
        line.strip() for line in info.splitlines()
    }:
        raise CommandError("Recovery requires an idle managed/DOWN interface")
    for family in ("-4", "-6"):
        routes = json.loads(execute_command(["ip", "-j", family, "route", "show", "default"]))
        if any(route.get("dev") == interface for route in routes):
            raise CommandError("Cannot reset an upstream interface")


class RadioRecovery:
    def __init__(self, manager: "NetworkManager") -> None:
        self._manager = manager
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

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
            execute_command(["ip", "link", "set", "dev", interface, "down"])
            execute_iw(["dev", interface, "set", "type", "managed"])
            try:
                execute_command(["ip", "link", "set", "dev", interface, "up"])
            finally:
                execute_command(["ip", "link", "set", "dev", interface, "down"])
            _require_idle(interface)
            return True
        raise CommandError("USB adapter did not reappear")
