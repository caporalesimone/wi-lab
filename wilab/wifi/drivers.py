"""Reload the kernel driver of the Wi-Fi adapters (`make reload-drivers`, ARCH-11 D1).

An adapter whose firmware hangs can crash hostapd on every start until its driver
is reloaded: unloading and loading the module makes the kernel detect it anew.
Reloading a module resets EVERY adapter it drives, so it runs only with the
service stopped, and never for a module that also drives the host's own network
(the interface with the default route, or `upstream_interface`).
"""

import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..network.commands import CommandError, execute_command

logger = logging.getLogger(__name__)

SERVICE_NAME = "wi-lab.service"
MODULE_NAME = re.compile(r"^[A-Za-z0-9_]+$")   # checked before the name reaches modprobe
REAPPEAR_TIMEOUT = 20.0                        # seconds for the interfaces to come back
POLL_INTERVAL = 0.5


class DriverError(Exception):
    """A driver cannot be identified or reloaded."""


@dataclass
class ReloadResult:
    module: str
    interfaces: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def service_is_running() -> bool:
    """Whether the Wi-Lab service runs (or starts): its networks may be in use."""
    try:
        state = execute_command(["systemctl", "is-active", SERVICE_NAME], check=False).strip()
    except CommandError:
        return False
    return state in ("active", "activating", "reloading")


def driver_module(interface: str) -> str:
    """The kernel module that drives *interface* (`mt7921u`, `rtw88_8822bu`, ...)."""
    link = f"/sys/class/net/{interface}/device/driver/module"
    try:
        module = os.path.basename(os.path.realpath(link, strict=True))
    except OSError as exc:
        raise DriverError(f"Cannot find the driver module of {interface} (built into the kernel?): {exc}") from exc
    if not MODULE_NAME.match(module):
        raise DriverError(f"Unexpected driver name {module!r} for {interface}")
    return module


def _present(interface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{interface}")


def _reload(module: str, interfaces: list[str]) -> None:
    logger.warning("Reloading driver %s (adapters: %s)", module, ", ".join(interfaces))
    try:
        execute_command(["modprobe", "-r", module], timeout=30.0)
        execute_command(["modprobe", module], timeout=30.0)
    except CommandError as exc:
        raise DriverError(f"Cannot reload driver {module}: {exc}") from exc
    deadline = time.monotonic() + REAPPEAR_TIMEOUT
    while (missing := [i for i in interfaces if not _present(i)]) and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
    if missing:
        # USB adapters may come back under a new name: discovery adds them when the service starts.
        logger.warning("After reloading %s, %s did not come back with the same name", module, ", ".join(missing))


def reload_drivers(
    interfaces: Iterable[str], protected: Iterable[str],
    module_of: Callable[[str], str] = driver_module,
) -> list[ReloadResult]:
    """Reload each module of *interfaces* once; refuse a module that drives one of *protected*.

    *protected* are the host's own interfaces (default route, upstream). A failure
    is reported in the results and does not stop the other modules.
    """
    by_module: dict[str, list[str]] = {}
    results: list[ReloadResult] = []
    for interface in interfaces:
        try:
            by_module.setdefault(module_of(interface), []).append(interface)
        except DriverError as exc:
            results.append(ReloadResult("unknown", [interface], str(exc)))
    host_modules: dict[str, str] = {}
    for interface in protected:
        try:
            host_modules[module_of(interface)] = interface
        except DriverError:
            continue   # a virtual or built-in host interface has no module to protect
    for module, names in by_module.items():
        if module in host_modules:
            results.append(ReloadResult(module, names, (
                f"not reloaded: {module} also drives {host_modules[module]}, the host's network"
            )))
            continue
        try:
            _reload(module, names)
            results.append(ReloadResult(module, names))
        except DriverError as exc:
            results.append(ReloadResult(module, names, str(exc)))
    return results
