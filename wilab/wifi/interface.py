import logging
import os

from ..network.commands import CommandError, execute_command

logger = logging.getLogger(__name__)

SYS_CLASS_NET = "/sys/class/net"


def interface_present(interface: str) -> bool:
    """True while the kernel has a network device with this name.

    A USB adapter that disconnects (unplug, firmware crash, USB reset) loses
    its netdev until it re-enumerates; commands on it fail with
    "Cannot find device". Callers use this to skip resets that have nothing to
    reset and to classify the failure as a radio fault.
    """
    return os.path.exists(os.path.join(SYS_CLASS_NET, interface))


def reset_interface(interface: str) -> None:
    """Bring a radio back to a known idle state: down, managed, no address, no shaping.

    Used when discovery adds an adapter (STAB-4): after an unclean shutdown a
    radio can keep the gateway address of the previous run, which makes the
    allocator skip its natural subnet, or a netem/HTB qdisc that would silently
    degrade the next network while QoS reports it inactive. Never raises: a
    failure is logged and the normal startup preparation runs again later.
    """
    if not interface_present(interface):
        return
    steps = (
        ["ip", "link", "set", interface, "down"],
        ["iw", "dev", interface, "set", "type", "managed"],
        ["ip", "addr", "flush", "dev", interface],
    )
    for cmd in steps:
        try:
            execute_command(cmd)
        except CommandError as exc:
            logger.warning("Could not reset %s (%s): %s", interface, " ".join(cmd[:3]), exc)
    # No qdisc is not an error: check=False.
    for kind in ("root", "ingress"):
        try:
            execute_command(["tc", "qdisc", "del", "dev", interface, kind], check=False)
        except CommandError as exc:
            logger.warning("Could not clear %s qdisc on %s: %s", kind, interface, exc)


class InterfaceError(Exception):
    """Exception raised for interface validation failures."""


def validate_interface_exists(interface: str) -> bool:
    """
    Check if network interface exists.
    
    Args:
        interface: Interface name (e.g., "wlan0")
        
    Returns:
        True if interface exists
        
    Raises:
        InterfaceError: If interface does not exist
    """
    try:
        output = execute_command(["ip", "link", "show", interface])
        return interface in output
    except CommandError:
        raise InterfaceError(f"Interface {interface} does not exist")
