"""Startup discovery of AP-capable Wi-Fi interfaces."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from time import sleep

from ..network.commands import CommandError, execute_command, execute_iw

logger = logging.getLogger(__name__)

SYS_CLASS_NET = Path("/sys/class/net")
USB_PORT_PATTERN = re.compile(r"^\d+-\d+(\.\d+)*$")
NAME_CHECK_ATTEMPTS = 5
NAME_CHECK_INTERVAL = 0.25
# Scans (calls of discover_radios) an interface may keep a name other than the one
# udev suggests before it is used as it is (BUG-5): on hosts where a custom udev
# rule or naming policy keeps another name, the rename never comes.
RENAME_GRACE_SCANS = 3
# Consecutive scans each interface has waited for a rename that did not come.
_rename_waits: dict[str, int] = {}


@dataclass(frozen=True)
class DiscoveredRadio:
    interface: str
    phy: str
    usb_port: str | None


def _list_wifi_interfaces() -> list[tuple[str, str]]:
    """Return (phy, interface) pairs reported by `iw dev`."""
    pairs: list[tuple[str, str]] = []
    phy: str | None = None
    for raw in execute_iw(["dev"]).splitlines():
        line = raw.strip()
        if line.startswith("phy#"):
            phy = "phy" + line[4:]
        elif line.startswith("Interface ") and phy is not None:
            pairs.append((phy, line.split(None, 1)[1].strip()))
    return pairs


def _supports_ap_mode(phy: str) -> bool:
    in_modes = False
    for raw in execute_iw(["phy", phy, "info"]).splitlines():
        line = raw.strip()
        if line.startswith("Supported interface modes:"):
            in_modes = True
        elif in_modes:
            if not line.startswith("* "):
                return False
            if line[2:].strip() == "AP":
                return True
    return False


def detect_usb_port(interface: str) -> str | None:
    """Return the Linux USB topology port (e.g. ``2-1``) for a USB adapter, else None."""
    device = SYS_CLASS_NET / interface / "device"
    try:
        function = device.resolve(strict=True)
        subsystem = (device / "subsystem").resolve(strict=True).name
    except OSError:
        return None
    port = function.parent.name
    if subsystem != "usb" or not function.name.startswith(f"{port}:"):
        return None
    return port if USB_PORT_PATTERN.match(port) else None


@dataclass(frozen=True)
class DeviceInfo:
    """Where an antenna is attached, from sysfs: USB, PCI (also built-in cards) or SDIO."""
    bus: str        # sysfs subsystem: usb, pci, sdio, ...
    address: str    # USB port (2-1.3), PCI address (0000:02:00.0) or bus device name
    driver: str | None


def detect_device(interface: str) -> DeviceInfo | None:
    """Bus, address and driver of *interface*; None when sysfs does not show it."""
    device = SYS_CLASS_NET / interface / "device"
    try:
        function = device.resolve(strict=True)
        bus = (device / "subsystem").resolve(strict=True).name
    except OSError:
        return None
    try:
        driver: str | None = (device / "driver").resolve(strict=True).name
    except OSError:
        driver = None
    # A USB network device is an interface (2-1:1.0) of the device on port 2-1.
    port = function.parent.name
    address = port if bus == "usb" and function.name.startswith(f"{port}:") else function.name
    return DeviceInfo(bus=bus, address=address, driver=driver)


def default_route_interfaces() -> set[str]:
    """Interfaces carrying an IPv4 or IPv6 default route."""
    devices: set[str] = set()
    for cmd in (["ip", "route", "show", "default"], ["ip", "-6", "route", "show", "default"]):
        try:
            output = execute_command(cmd, check=False)
        except CommandError:
            continue
        for line in output.splitlines():
            parts = line.split()
            if "dev" in parts and parts.index("dev") + 1 < len(parts):
                devices.add(parts[parts.index("dev") + 1])
    return devices


@dataclass(frozen=True)
class _Renaming:
    """An interface that is ready except for its name: udev suggests `suggested`."""

    phy: str
    suggested: str


def _ready_radio(
    phy: str, interface: str, *, trust_name: bool = False,
) -> DiscoveredRadio | _Renaming | None:
    path = SYS_CLASS_NET / interface
    try:
        ifindex = (path / "ifindex").read_text().strip()
        output = execute_command(
            ["udevadm", "info", "--query=property", "--path", str(path)],
            timeout=1.0, exact_timeout=True,
        )
        props = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if (
            not props.get("USEC_INITIALIZED")
            or props.get("INTERFACE") != interface
            or props.get("IFINDEX") != ifindex
        ):
            return None
        if not trust_name and props.get("ID_NET_NAME", interface) != interface:
            return _Renaming(phy, props["ID_NET_NAME"])
        port = detect_usb_port(interface)
        if (path / "ifindex").read_text().strip() == ifindex:
            return DiscoveredRadio(interface, phy, port)
    except (OSError, CommandError):
        logger.debug("Cannot confirm readiness of Wi-Fi interface %s", interface)
    return None


def discover_radios(*, quiet: bool = False) -> list[DiscoveredRadio]:
    """List AP-capable interfaces after udev has finished naming them.

    `quiet` logs problems at debug level, for periodic scans.
    """
    for attempt in range(NAME_CHECK_ATTEMPTS):
        radios, pending, renaming = _discover_snapshot(quiet)
        if not (pending or renaming) or attempt == NAME_CHECK_ATTEMPTS - 1:
            radios += _accept_unrenamed(renaming)
            waiting = pending + [name for name in renaming if name not in {r.interface for r in radios}]
            if waiting:
                (logger.debug if quiet else logger.info)(
                    "Skipping Wi-Fi interfaces not yet initialized by udev: %s", ", ".join(waiting),
                )
            return radios
        # A rename invalidates the old name; enumerate again rather than retrying it.
        sleep(NAME_CHECK_INTERVAL)
    return []


def _accept_unrenamed(renaming: dict[str, _Renaming]) -> list[DiscoveredRadio]:
    """Interfaces that kept their name for RENAME_GRACE_SCANS scans, accepted as they are."""
    for name in [name for name in _rename_waits if name not in renaming]:
        del _rename_waits[name]
    accepted: list[DiscoveredRadio] = []
    for interface, wait in renaming.items():
        waits = _rename_waits[interface] = _rename_waits.get(interface, 0) + 1
        if waits <= RENAME_GRACE_SCANS:
            continue
        radio = _ready_radio(wait.phy, interface, trust_name=True)
        if not isinstance(radio, DiscoveredRadio):
            continue
        if waits == RENAME_GRACE_SCANS + 1:
            logger.warning(
                "Using Wi-Fi interface %s although udev suggests the name %s: it was not renamed "
                "in %d scans", interface, wait.suggested, RENAME_GRACE_SCANS,
            )
        accepted.append(radio)
    return accepted


def _discover_snapshot(
    quiet: bool,
) -> tuple[list[DiscoveredRadio], list[str], dict[str, _Renaming]]:
    info = logger.debug if quiet else logger.info
    warning = logger.debug if quiet else logger.warning
    error = logger.debug if quiet else logger.error
    try:
        pairs = _list_wifi_interfaces()
    except CommandError as e:
        error("Wi-Fi discovery failed: %s", e)
        return [], [], {}
    ap_capable: dict[str, bool] = {}
    radios: list[DiscoveredRadio] = []
    pending: list[str] = []
    renaming: dict[str, _Renaming] = {}
    for phy, interface in pairs:
        if phy not in ap_capable:
            try:
                ap_capable[phy] = _supports_ap_mode(phy)
            except CommandError as e:
                warning("Cannot read capabilities of %s: %s", phy, e)
                ap_capable[phy] = False
        if not ap_capable[phy]:
            info("Skipping %s: %s does not support AP mode", interface, phy)
            continue
        radio = _ready_radio(phy, interface)
        if isinstance(radio, _Renaming):
            renaming[interface] = radio
        elif radio is None:
            pending.append(interface)
        else:
            radios.append(radio)
    return radios, pending, renaming
