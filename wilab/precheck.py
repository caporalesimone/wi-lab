"""Startup prechecks (NM-1): what the host must offer before Wi-Lab starts.

A ``fatal`` finding stops the service with exit code 78 (EX_CONFIG); the unit
has ``RestartPreventExitStatus=78``, so systemd leaves it ``failed`` with the
reason in the journal instead of restarting it every 10 s. A ``warning`` is
logged and the service starts anyway.
"""

import logging
import os
import shutil
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .network.commands import CommandError, execute_command
from .network.safety import list_wilab_rules

logger = logging.getLogger(__name__)

EXIT_PRECHECK_FAILED = 78

# Every command the service runs. Keep aligned with REQUIRED_CMDS of
# install/01-preconditions/04-tools.sh (which also has python3 and systemctl).
REQUIRED_COMMANDS = (
    "hostapd", "hostapd_cli", "dnsmasq", "iw", "ip", "tc", "iptables", "ip6tables",
    "udevadm", "usbreset", "modprobe", "networkctl",
)

# wpa_supplicant creates a control socket here for each interface it manages.
WPA_SUPPLICANT_RUN_DIR = Path("/run/wpa_supplicant")

_DISABLE = "sudo systemctl disable --now {unit} && sudo systemctl mask {unit}"


@dataclass(frozen=True)
class Finding:
    check: str                              # stable name, e.g. "network_manager"
    level: Literal["fatal", "warning"]
    message: str                            # what is wrong and what to do


def _check_root() -> list[Finding]:
    if os.geteuid() == 0:
        return []
    return [Finding("root", "fatal", "Wi-Lab must run as root: no network command can work otherwise")]


def _check_commands() -> list[Finding]:
    missing = [cmd for cmd in REQUIRED_COMMANDS if shutil.which(cmd) is None]
    if not missing:
        return []
    return [Finding(
        "commands", "fatal",
        f"Missing commands: {', '.join(missing)}. Run the installer again (sudo bash install.sh)",
    )]


def _check_network_manager() -> list[Finding]:
    try:
        state = execute_command(["systemctl", "is-active", "NetworkManager"], check=False, quiet=True)
    except (CommandError, OSError):
        # No systemctl, or it failed in another way: nothing to say about NetworkManager.
        return []
    if state.strip() != "active":
        return []
    return [Finding(
        "network_manager", "warning",
        "NetworkManager is active: it can take Wi-Fi adapters back and bring APs down. "
        "Wi-Lab requires it disabled: " + _DISABLE.format(unit="NetworkManager")
        + " (first check that it manages no interface: nmcli device status)",
    )]


def _check_leftover_rules() -> list[Finding]:
    rules = list_wilab_rules()
    count = len(rules["nat"]) + len(rules["forward"])
    if not count:
        return []
    # The service removes them itself while it starts (REV-17): this only reports them.
    return [Finding(
        "leftover_rules", "warning",
        f"Found {count} Wi-Lab iptables rules from a previous run; startup cleanup removes them",
    )]


def run_prechecks() -> list[Finding]:
    """Run every startup check. Never raises."""
    findings: list[Finding] = []
    for check in (_check_root, _check_commands, _check_network_manager, _check_leftover_rules):
        try:
            findings.extend(check())
        except Exception as exc:  # noqa: BLE001 - a broken check must not stop the service
            logger.warning("Startup precheck %s could not run: %s", check.__name__, exc)
    return findings


def log_findings(findings: Iterable[Finding]) -> bool:
    """Log *findings*; return True if one of them is fatal."""
    fatal = False
    any_finding = False
    for finding in findings:
        any_finding = True
        if finding.level == "fatal":
            fatal = True
            logger.critical("Startup precheck %s: %s", finding.check, finding.message)
        else:
            logger.warning("Startup precheck %s: %s", finding.check, finding.message)
    if not any_finding:
        logger.info("Startup prechecks passed")
    return fatal


_wpa_warned: set[str] = set()
_wpa_lock = threading.Lock()


def _wpa_supplicant_finding(radio: str) -> Finding:
    return Finding(
        "wpa_supplicant", "warning",
        f"wpa_supplicant manages {radio}: it competes with hostapd. Disable it: "
        + _DISABLE.format(unit="wpa_supplicant"),
    )


def wpa_supplicant_findings(radios: Iterable[str], run_dir: Path = WPA_SUPPLICANT_RUN_DIR) -> list[Finding]:
    """A warning for each radio that wpa_supplicant manages.

    Radios are found by discovery after startup, so this runs when discovery
    adds them, not in run_prechecks. The mere presence of the service is no
    warning: it matters only when it holds a Wi-Lab radio.
    """
    return [_wpa_supplicant_finding(r) for r in sorted(set(radios)) if (run_dir / r).exists()]


def warn_wpa_supplicant(radios: Iterable[str], run_dir: Path = WPA_SUPPLICANT_RUN_DIR) -> None:
    """Log the wpa_supplicant warning once per radio. Never raises."""
    try:
        for radio in sorted(set(radios)):
            if not (run_dir / radio).exists():
                continue
            with _wpa_lock:
                if radio in _wpa_warned:
                    continue
                _wpa_warned.add(radio)
            finding = _wpa_supplicant_finding(radio)
            logger.warning("Startup precheck %s: %s", finding.check, finding.message)
    except OSError as exc:
        logger.warning("Cannot check wpa_supplicant: %s", exc)
