"""Startup cleanup of what an unclean shutdown left behind (STAB-4).

Firewall rules and captive portal chains are removed elsewhere at startup
(`NatManager.remove_stale_rules`, `remove_stale_captive_rules`). This module
handles the rest:

- hostapd and dnsmasq processes started by a previous Wi-Lab (recognised by
  their configuration path under the Wi-Lab runtime directories). Both are
  foreground children of the service (ARCH-6): under systemd they die with
  it; when the service runs by hand and crashes they survive, reparented to
  init;
- files in the runtime directories (configurations, leases);
- `wilab-ifbN` devices created for QoS upload shaping.

Radios are reset (down, managed, no address, no traffic control) when
discovery adds them, see `wilab.wifi.interface.reset_interface`.
"""

import logging
import os
import shutil
from pathlib import Path

from .network.commands import CommandError, execute_command, stop_process
from .network.dhcp import DNSMASQ_CONFIG_DIR
from .network.qos import IFB_PREFIX
from .paths import LEGACY_RUNTIME_DIRS
from .wifi.hostapd import HOSTAPD_CONFIG_DIR

logger = logging.getLogger(__name__)

# The current directories, and those used before 4.1.0 (/tmp) for an upgrade.
RUNTIME_DIRS = (HOSTAPD_CONFIG_DIR, DNSMASQ_CONFIG_DIR, *LEGACY_RUNTIME_DIRS)
_PROGRAMS = {"hostapd", "dnsmasq"}


def _orphans(proc: Path = Path("/proc")) -> list[tuple[int, str]]:
    """hostapd/dnsmasq processes whose arguments point into a Wi-Lab runtime directory."""
    found: list[tuple[int, str]] = []
    me = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            args = [os.fsdecode(a) for a in (entry / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        if not args or Path(args[0]).name not in _PROGRAMS:
            continue
        if any(directory in arg for arg in args[1:] for directory in RUNTIME_DIRS):
            found.append((int(entry.name), Path(args[0]).name))
    return found


def _stale_ifbs() -> list[str]:
    try:
        output = execute_command(["ip", "-o", "link", "show", "type", "ifb"], check=False)
    except CommandError:
        return []
    names = []
    for line in output.splitlines():
        parts = line.split(":")
        if len(parts) > 1:
            name = parts[1].strip().split("@")[0]
            if name.startswith(IFB_PREFIX):
                names.append(name)
    return names


def cleanup_runtime() -> None:
    """Remove processes, files and devices left by a previous Wi-Lab run. Never raises."""
    for step in (_stop_orphans, _remove_files, _remove_ifbs):
        try:
            step()
        except OSError as exc:   # /proc or a runtime directory unreadable (REV-12)
            logger.error("Startup cleanup step %s failed: %s", step.__name__.lstrip("_"), exc)


def _stop_orphans() -> None:
    for pid, program in _orphans():
        try:
            stop_process(pid)
            logger.warning("Stopped orphan %s (pid %d) left by a previous run", program, pid)
        except CommandError as exc:
            logger.error("Could not stop orphan %s (pid %d): %s", program, pid, exc)


def _remove_files() -> None:
    for directory in RUNTIME_DIRS:
        path = Path(directory)
        if not path.is_dir():
            continue
        removed = 0
        for child in path.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            except OSError as exc:
                logger.error("Could not remove stale runtime file %s: %s", child, exc)
        if removed:
            logger.warning("Removed %d stale entries from %s", removed, directory)
    for legacy in LEGACY_RUNTIME_DIRS:
        shutil.rmtree(legacy, ignore_errors=True)   # emptied above; the directory goes too


def _remove_ifbs() -> None:
    for name in _stale_ifbs():
        try:
            execute_command(["ip", "link", "del", name])
            logger.warning("Removed stale QoS device %s", name)
        except CommandError as exc:
            logger.error("Could not remove stale QoS device %s: %s", name, exc)
