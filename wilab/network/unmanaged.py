"""Keep host network managers away from Wi-Lab radios.

NetworkManager and systemd-networkd manage every new Wi-Fi interface by
default, bring it up and start scanning or DHCP on it. Wi-Lab writes rules
that exclude its radios to their runtime configuration directories under
``/run``. The rules also cover a radio that re-enumerates after a USB reset,
and disappear on reboot; Wi-Lab writes them again when it starts.
"""

import logging
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .commands import CommandError, execute_command

logger = logging.getLogger(__name__)

NM_RUNTIME_DIR = Path("/run/NetworkManager")
NM_RULES = NM_RUNTIME_DIR / "conf.d" / "90-wilab-unmanaged.conf"
NETWORKD_RUNTIME_DIR = Path("/run/systemd/network")
# Sorted before other .network files (including dracut's catch-all), so it matches first.
NETWORKD_RULES = NETWORKD_RUNTIME_DIR / "00-wilab-unmanaged.network"
_INTERFACE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def _replace(path: Path, content: str) -> bool:
    """Atomically write *content*; return False if it was already current."""
    try:
        if path.read_text() == content:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def _reload(cmd: list[str]) -> None:
    try:
        execute_command(cmd)
    except CommandError as exc:
        logger.warning("Cannot reload host network manager (%s): %s", cmd[0], exc)


def exclude_from_host_managers(interfaces: Iterable[str]) -> None:
    """Mark *interfaces* unmanaged in NetworkManager and systemd-networkd."""
    names = sorted({name for name in interfaces if _INTERFACE.match(name)})
    if not names:
        return
    changed = False
    if NM_RUNTIME_DIR.is_dir():
        # A [device] section: keyfile.unmanaged-devices would replace the distribution's list,
        # which keeps wired NICs such as the management interface away from NetworkManager.
        nm = (
            "[device-wilab-unmanaged]\nmatch-device="
            + ";".join(f"interface-name:{n}" for n in names) + "\nmanaged=0\n"
        )
        try:
            if _replace(NM_RULES, nm):
                changed = True
                _reload(["nmcli", "general", "reload", "conf"])
        except OSError as exc:
            logger.warning("Cannot write NetworkManager rules for Wi-Lab radios: %s", exc)
        # The section applies when a device appears (e.g. after a USB reset);
        # devices already present are released explicitly.
        for name in names:
            try:
                execute_command(["nmcli", "device", "set", name, "managed", "no"], check=False)
            except CommandError as exc:
                logger.warning("Cannot release %s from NetworkManager: %s", name, exc)
    if NETWORKD_RUNTIME_DIR.parent.is_dir():
        networkd = f"[Match]\nName={' '.join(names)}\n\n[Link]\nUnmanaged=yes\n"
        try:
            if _replace(NETWORKD_RULES, networkd):
                changed = True
                _reload(["networkctl", "reload"])
        except OSError as exc:
            logger.warning("Cannot write systemd-networkd rules for Wi-Lab radios: %s", exc)
    if changed:
        logger.info("Excluded from NetworkManager and systemd-networkd: %s", ", ".join(names))
