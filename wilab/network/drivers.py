"""Reload the kernel driver of WiFi adapters.

A USB adapter whose firmware failed to load can crash hostapd on every start until its driver
is reloaded. Unloading and loading the module again makes the kernel detect the adapter anew.
It resets EVERY adapter that uses the module, so it is only safe while no network is running.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List

from .commands import CommandError, execute_command

logger = logging.getLogger(__name__)

# What a kernel module name looks like. Checked before the name reaches modprobe.
MODULE_NAME = re.compile(r"^[A-Za-z0-9_]+$")

SERVICE_NAME = "wi-lab.service"

# Seconds to wait for the interfaces to come back after the module is loaded again
REAPPEAR_TIMEOUT = 20.0
POLL_INTERVAL = 0.5


class DriverError(Exception):
    """A driver cannot be identified or reloaded."""


@dataclass
class ReloadResult:
    """Outcome of the reload of one kernel module."""

    module: str
    interfaces: List[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def service_is_running() -> bool:
    """
    Whether the Wi-Lab service is running (or starting), so its networks may be in use.

    Without systemd (a development machine) there is no service, so the answer is no.
    """
    try:
        state = execute_command(["systemctl", "is-active", SERVICE_NAME], check=False).strip()
    except CommandError:
        return False
    return state in ("active", "activating", "reloading")


def _read_module(interface: str) -> str:
    """Kernel module of an interface, from sysfs (the link /sys/class/net/<if>/device/driver/module)."""
    link = f"/sys/class/net/{interface}/device/driver/module"
    try:
        return os.path.basename(os.path.realpath(link, strict=True))
    except OSError as e:
        raise DriverError(
            f"Cannot find the driver of {interface}: is the adapter plugged in and detected? ({e})"
        ) from e


def _interface_present(interface: str) -> bool:
    return os.path.exists(f"/sys/class/net/{interface}")


def driver_module(interface: str) -> str:
    """
    Name of the kernel module that drives an interface (e.g. "rtw88_8822bu").

    Raises:
        DriverError: If the interface has no driver module (not present, or built into the kernel)
    """
    module = _read_module(interface)
    if not MODULE_NAME.match(module):
        raise DriverError(f"Unexpected driver name '{module}' for {interface}")
    return module


def _reload_module(module: str, interfaces: List[str]) -> None:
    """Unload and load a module, then wait until all the given interfaces are back."""
    logger.warning(f"Reloading driver {module} (adapters: {', '.join(interfaces)})")
    try:
        execute_command(["modprobe", "-r", module], timeout=30.0)
        execute_command(["modprobe", module], timeout=30.0)
    except CommandError as e:
        raise DriverError(f"Cannot reload driver {module}: {e}") from e

    deadline = time.monotonic() + REAPPEAR_TIMEOUT
    missing = [i for i in interfaces if not _interface_present(i)]
    while missing and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        missing = [i for i in interfaces if not _interface_present(i)]
    if missing:
        raise DriverError(
            f"Driver {module} reloaded but {', '.join(missing)} did not come back after "
            f"{REAPPEAR_TIMEOUT:.0f} s: unplug and replug the adapter, or restart the host"
        )
    logger.info(f"Driver {module} reloaded")


def reload_driver(interface: str) -> str:
    """
    Reload the driver of one interface. This resets every adapter that uses the same module.

    Returns:
        The name of the module that was reloaded

    Raises:
        DriverError: If the driver cannot be identified or reloaded, or the interface does not return
    """
    module = driver_module(interface)
    _reload_module(module, [interface])
    return module


def reload_drivers(interfaces: List[str]) -> List[ReloadResult]:
    """
    Reload the driver of every given interface, each module once even if several adapters share it.

    An interface whose driver cannot be identified, or a module that fails to reload, is reported
    in the results and does not stop the others.
    """
    by_module: Dict[str, List[str]] = {}
    results: List[ReloadResult] = []
    for interface in interfaces:
        try:
            by_module.setdefault(driver_module(interface), []).append(interface)
        except DriverError as e:
            results.append(ReloadResult(module="unknown", interfaces=[interface], error=str(e)))
    for module, module_interfaces in by_module.items():
        try:
            _reload_module(module, module_interfaces)
            results.append(ReloadResult(module, module_interfaces))
        except DriverError as e:
            results.append(ReloadResult(module, module_interfaces, error=str(e)))
    return results
