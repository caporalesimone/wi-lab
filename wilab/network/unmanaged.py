"""Keep host network managers away from Wi-Lab radios.

NetworkManager and systemd-networkd manage every new Wi-Fi interface by
default, bring it up and start scanning or DHCP on it.

- NetworkManager: each radio is released with ``nmcli device set ... managed no``,
  which NetworkManager forgets when it restarts. A runtime file under
  ``/run/NetworkManager/conf.d`` marks the same radios unmanaged (``managed=0`` in
  a device section) and is read when NetworkManager starts (STAB-9). Wi-Lab never
  reloads NetworkManager's configuration, which would re-read the settings of
  every interface, including the management one.
- systemd-networkd: a rule under ``/run`` matching only the radios' names marks
  them unmanaged, also after a USB re-enumeration. ``networkctl reload`` only
  reconfigures links whose matching configuration changed. The rule disappears
  on reboot; Wi-Lab writes it again when it starts.

The recovery worker releases and brings down a re-enumerated radio itself.
"""

import logging
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .commands import CommandError, execute_command

logger = logging.getLogger(__name__)

NETWORKD_RUNTIME_DIR = Path("/run/systemd/network")
# Sorted before other .network files (including dracut's catch-all), so it matches first.
NETWORKD_RULES = NETWORKD_RUNTIME_DIR / "00-wilab-unmanaged.network"
NM_RUNTIME_DIR = Path("/run/NetworkManager/conf.d")
# A device section, not keyfile.unmanaged-devices: distributions ship
# "unmanaged-devices=*,except:type:wifi", whose except would win over the radios.
NM_RULES = NM_RUNTIME_DIR / "00-wilab-unmanaged.conf"
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
    """Release *interfaces* from NetworkManager and mark them unmanaged in systemd-networkd."""
    names = sorted({name for name in interfaces if _INTERFACE.match(name)})
    if not names:
        return
    for name in names:
        try:
            execute_command(["nmcli", "device", "set", name, "managed", "no"], check=False)
        except CommandError as exc:
            logger.debug("Cannot release %s from NetworkManager: %s", name, exc)
    if NM_RUNTIME_DIR.parent.is_dir():
        devices = ";".join(f"interface-name:={name}" for name in names)
        try:
            # Read only when NetworkManager starts: never reloaded on purpose.
            if _replace(NM_RULES, f"[device-wilab-unmanaged]\nmatch-device={devices}\nmanaged=0\n"):
                logger.info("NetworkManager keeps Wi-Lab radios unmanaged after a restart: %s", ", ".join(names))
        except OSError as exc:
            logger.warning("Cannot write NetworkManager rules for Wi-Lab radios: %s", exc)
    changed = False
    if NETWORKD_RUNTIME_DIR.parent.is_dir():
        networkd = f"[Match]\nName={' '.join(names)}\n\n[Link]\nUnmanaged=yes\n"
        try:
            if _replace(NETWORKD_RULES, networkd):
                changed = True
                _reload(["networkctl", "reload"])
        except OSError as exc:
            logger.warning("Cannot write systemd-networkd rules for Wi-Lab radios: %s", exc)
    if changed:
        logger.info("Excluded from systemd-networkd: %s", ", ".join(names))
