"""Health checks that run host commands, computed in the background.

`/status` used to run `ip`, `iptables` and process checks on every call: under
load, and while a driver held the kernel's network lock, a call took up to 13 s
and every polling client added host commands. A background loop now refreshes
them every CHECK_INTERVAL seconds; readers get the latest result at once. If
the loop stalls, a reader older than MAX_AGE recomputes them itself.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import heartbeat
from .network.commands import CommandError, execute_command
from .timestamps import format_utc_timestamp

if TYPE_CHECKING:
    from .wifi.manager import NetworkManager

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10.0           # seconds between background refreshes
MAX_AGE = 2 * CHECK_INTERVAL    # older results are recomputed by the reader


@dataclass(frozen=True)
class HealthResult:
    """Checks of the networks that were settled (no start/stop running) at `checked_at`."""

    checked_at: str
    taken: float                                   # time.monotonic() of the check
    settled: frozenset[str]
    internet: frozenset[str]                       # settled networks with Internet
    checks: dict[str, Any] = field(default_factory=dict)

    def for_active(self, active: set[str]) -> dict[str, Any]:
        """The checks, ignoring networks that stopped since they were taken."""
        def keep(missing: list[str]) -> list[str]:
            return [device for device in missing if device in active]

        checks = {name: dict(value) for name, value in self.checks.items()}
        for name in ("hostapd", "dnsmasq"):
            missing = keep(checks[name]["missing"])
            checks[name].update(missing=missing, running=not missing,
                                instances=len(self.settled & active) - len(missing))
        nat_missing = keep(checks["iptables_nat"]["missing"])
        checks["iptables_nat"].update(
            missing=nat_missing, configured=not nat_missing,
        )
        return checks


def _not_busy(manager: NetworkManager, device: str) -> bool:
    """True if no start, stop or restore holds the device; never waits (RACE-2)."""
    lock = manager.device_lock(device)
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


def _process_check(settled: list[str], is_running: Any) -> dict[str, Any]:
    """Every settled network has its process alive (not just a PID file, BUG-2)."""
    missing = [device for device in settled if not is_running(device)]
    return {"running": not missing, "instances": len(settled) - len(missing), "missing": missing}


def _nat_check(manager: NetworkManager, expected: list[str]) -> dict[str, Any]:
    """Wi-Lab's own NAT rule exists for every settled network with Internet (BUG-2).

    Docker's or libvirt's MASQUERADE rules do not count, and a network without
    Internet needs none.
    """
    try:
        rules = manager.firewall_status()
    except Exception as exc:  # noqa: BLE001 - reported in the check, never fails a reader
        return {"configured": not expected, "missing": expected, "errors": [str(exc)]}
    nat = rules.get("nat") or ""
    missing = [device for device in expected if f"wilab-nat-{device}" not in nat]
    return {"configured": not missing, "missing": missing, "errors": rules.get("errors", [])}


def _upstream_check(manager: NetworkManager) -> dict[str, Any]:
    """Operational state and IPv4 address of the upstream, from `ip -j` (BUG-2).

    A link with state UNKNOWN (VPN, some virtual NICs) is up when the kernel
    reports LOWER_UP.
    """
    try:
        name = manager.nat_manager.get_upstream_interface()
        links = json.loads(execute_command(["ip", "-j", "addr", "show", "dev", name]) or "[]")
    except (CommandError, RuntimeError, ValueError) as exc:
        return {"name": manager.config.upstream_interface, "reachable": False, "error": str(exc)}
    link = links[0] if links else {}
    state = link.get("operstate")
    up = state == "UP" or (state == "UNKNOWN" and "LOWER_UP" in link.get("flags", []))
    has_ip = any(a.get("family") == "inet" for a in link.get("addr_info", []))
    return {"name": name, "up": up, "has_ip": has_ip, "reachable": up and has_ip}


class HealthChecks:
    """The latest host-command checks of a NetworkManager, shared by every reader."""

    def __init__(self, manager: NetworkManager) -> None:
        self._manager = manager
        self._result: HealthResult | None = None
        self._lock = threading.Lock()          # one computation at a time

    def refresh(self) -> HealthResult:
        with self._lock:
            manager = self._manager
            # RACE-2: judge only networks with no operation in progress. A stop removes
            # DHCP and NAT before it leaves `active`.
            snapshot = manager.active.copy()
            settled = [device for device in snapshot if _not_busy(manager, device)]
            internet = [device for device in settled if snapshot[device].internet_enabled]
            result = HealthResult(
                checked_at=format_utc_timestamp(time.time()) or "",
                taken=time.monotonic(),
                settled=frozenset(settled),
                internet=frozenset(internet),
                checks={
                    "hostapd": _process_check(settled, manager.hostapd_manager.is_running),
                    "dnsmasq": _process_check(settled, manager.dhcp_server.is_running),
                    "iptables_nat": _nat_check(manager, internet),
                    "upstream_interface": _upstream_check(manager),
                },
            )
            self._result = result
            return result

    def current(self) -> HealthResult:
        """The latest result; recomputed here only when the loop is late (MAX_AGE)."""
        result = self._result
        if result is None or time.monotonic() - result.taken > MAX_AGE:
            return self.refresh()
        return result

    def loop(self, stop: threading.Event) -> None:
        """Refresh every CHECK_INTERVAL seconds until *stop* is set; survives any error."""
        last_error = ""
        while True:
            heartbeat.beat("health")
            try:
                self.refresh()
            except Exception as exc:  # noqa: BLE001 - this loop must survive anything (WD-9)
                if repr(exc) != last_error:
                    logger.exception("[health-loop] Unexpected error")
                last_error = repr(exc)
            else:
                last_error = ""
            if stop.wait(CHECK_INTERVAL):
                return
