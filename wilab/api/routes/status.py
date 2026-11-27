"""System status endpoint."""

from math import ceil
from typing import Any

from fastapi import APIRouter, Depends

from ... import health as health_module
from ... import heartbeat
from ...api.auth import require_token
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...config import AppConfig
from ...network.commands import stuck_commands
from ...reservation import ReservationManager
from ...timestamps import format_utc_timestamp
from ...version import __version__
from ...wifi.manager import NetworkManager

_POLICY_EXAMPLE = {"min_seconds": 60, "max_seconds": 86400, "allow_unlimited": False}
_CHECKS_OK_EXAMPLE = {
    "commands": {"stuck": 0},
    "loops": {"stale": []},
    "hostapd": {"running": True, "instances": 0, "missing": []},
    "dnsmasq": {"running": True, "instances": 0, "missing": []},
    "iptables_nat": {"configured": True, "missing": [], "errors": []},
    "upstream_interface": {"name": "eth0", "up": True, "has_ip": True, "reachable": True},
    "updates": {"service_restart_required": False, "replaced_libraries": [],
                "system_reboot_required": False, "reboot_packages": [], "since": None},
}

RESTART_MESSAGES = {
    (True, False): "Security updates were installed on the host: restart Wi-Lab "
                   "(systemctl restart wi-lab) when no network is in use",
    (False, True): "Security updates were installed on the host: reboot it when no network is in use",
    (True, True): "Security updates were installed on the host: reboot it when no network is in use",
}


router = APIRouter(
    tags=["System"],
)


@router.get(
    "/status",
    summary="Read system and adapter status",
    responses={
        200: {
            "description": (
                "Health and allocation snapshot. `status` is `standby`, `in_use` or `degraded`; "
                "`degraded` lists why in `degraded_reasons` (quarantined antenna, network "
                "being repaired, dead hostapd or dnsmasq, missing NAT rule, upstream down, "
                "stuck host command, stalled loop). The detail is in `GET /monitoring`. A "
                "reserved or quarantined adapter is not allocatable."
            ),
            "content": {"application/json": {"examples": {
                "standby": {
                    "summary": "standby - no antenna reserved, every adapter healthy",
                    "value": {
                        "version": "4.1.0", "status": "standby", "degraded_reasons": [], "active_networks": 0,
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reservation": None,
                             "network_active": False},
                            {"display_name": "Antenna B", "interface": "wlan1", "reservation": None,
                             "network_active": False},
                        ],
                        "restart_required": None,
                        "reservation_policy": _POLICY_EXAMPLE,
                    },
                },
                "in_use": {
                    "summary": "in_use - an antenna reserved, everything healthy",
                    "value": {
                        "version": "4.1.0", "status": "in_use", "degraded_reasons": [], "active_networks": 1,
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 540},
                             "network_active": True},
                            {"display_name": "Antenna B", "interface": "wlan1", "reservation": None,
                             "network_active": False},
                        ],
                        "restart_required": None,
                        "reservation_policy": _POLICY_EXAMPLE,
                    },
                },
                "degraded_quarantine": {
                    "summary": "degraded - one adapter quarantined, another being repaired",
                    "value": {
                        "version": "4.1.0", "status": "degraded", "active_networks": 1,
                        "degraded_reasons": [
                            {"code": "antenna_quarantined", "interface": "wlan0",
                             "message": "Antenna quarantined (unavailable)"},
                            {"code": "network_being_repaired", "interface": "wlan1",
                             "message": "Network being repaired by the watchdog (restoring_ap)"},
                        ],
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reservation": None,
                             "network_active": False, "recovery_state": "unavailable"},
                            {"display_name": "Antenna B", "interface": "wlan1", "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 54},
                             "network_active": False, "runtime_state": "restoring_ap"},
                        ],
                        "restart_required": {
                            "service": True, "system": False, "since": "2026-11-27T06:39:50Z",
                            "message": RESTART_MESSAGES[(True, False)],
                        },
                        "reservation_policy": _POLICY_EXAMPLE,
                    },
                },
            }}},
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
def system_status(
    manager: NetworkManager = Depends(get_manager), 
    config=Depends(get_config),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    _: bool = Depends(require_token)
):
    """
    Service health, antennas and reservation policy: the call clients poll.

    Overall `status`:

    | Value | Meaning |
    |---|---|
    | `standby` | No antenna is reserved and nothing is wrong. |
    | `in_use` | At least one antenna is reserved (with or without a network) and nothing is wrong. |
    | `degraded` | At least one entry in `degraded_reasons`, whatever the reservations. |

    How many networks run is `active_networks`.

    Each `degraded_reasons` entry has a stable `code`, the `interface` it
    concerns (or `null`) and a `message` for display:

    | `code` | Meaning |
    |---|---|
    | `antenna_quarantined` | The antenna has `recovery_state`: `recovering` (USB reset and probe running) or `unavailable` (re-probed every 30 s, backing off to 15 min). It may return by itself. Not allocatable, even with `reservation: null`. |
    | `network_being_repaired` | A reserved network has `runtime_state` (`restoring_ap`, `restoring_dhcp`, `dhcp_failed`, `restore_failed`). Its owner waits. |
    | `network_stop_incomplete` | A `DELETE .../network` answered `503 / 1012`: the network is half stopped (`runtime_state: stop_failed`) until its owner repeats the DELETE. |
    | `hostapd_not_running`, `dnsmasq_not_running` | The AP or DHCP process of that network is dead; the watchdog normally repairs it within seconds. |
    | `nat_rule_missing` | That network has Internet enabled but its NAT rule is missing. |
    | `upstream_unreachable` | The host uplink is down or has no IPv4 address while a network has Internet. |
    | `command_stuck` | A host command did not exit even after SIGKILL: usually a hung Wi-Fi driver; the adapter may need a reset. |
    | `loop_stalled` | A background loop has not run for 3 minutes; Wi-Lab restarts itself when idle. |
    | `cleanup_failed` | The cleanup after a release or expiry failed; the antenna is held, not allocatable, and the cleanup is repeated (5 s, 15 s, 60 s, then every 5 min). |

    `restart_required` is `null`, or says that security updates were installed on
    the host and need a restart, which Wi-Lab never does by itself (it is excluded
    from needrestart, so an unattended upgrade cannot drop the networks): `service`
    when a library Wi-Lab loaded was replaced (`systemctl restart wi-lab`), `system`
    when an update asks for a reboot (`/run/reboot-required`, or a kernel newer than
    the running one is installed); `since` is when it was first seen, `message` a
    sentence for display (the web UI shows it as a red bar). It does not make the
    status `degraded`; the replaced libraries and packages are in `GET /monitoring`.

    The detail of every check is in `GET /monitoring`. Checks that run host
    commands are refreshed every 10 s in the background: this call runs no
    command and answers at once. A network with a start, stop or restore in
    progress is not judged, so a create or delete never makes the status flap.

    The former owner of a quarantined antenna is told by `404` with
    `reason: reservation_invalidated` on every call with its ID. What a network on each antenna can use is
    in `GET /antennas/{interface}`.
    """
    return _system_status(manager, config, reservation_mgr)


# Stable codes of `degraded_reasons`.
REASON_MESSAGES = {
    "antenna_quarantined": "Antenna quarantined ({state})",
    "network_being_repaired": "Network being repaired by the watchdog ({state})",
    "hostapd_not_running": "hostapd is not running",
    "dnsmasq_not_running": "dnsmasq (DHCP) is not running",
    "nat_rule_missing": "NAT rule missing: no Internet access",
    "upstream_unreachable": "Upstream interface {name} is down or has no IPv4 address",
    "command_stuck": "{count} host command(s) stuck in the kernel; the adapter may need a reset",
    "loop_stalled": "Background loop stalled: {loops}",
    "network_stop_incomplete": "A stop did not complete (hostapd stuck in the kernel); the owner repeats DELETE .../network",
    "cleanup_failed": "Cleanup failed {count} time(s) in a row; the antenna stays held, next attempt in {wait} s",
}


def _reason(code: str, interface: str | None = None, **values: Any) -> dict[str, Any]:
    return {"code": code, "interface": interface, "message": REASON_MESSAGES[code].format(**values)}


def _assess(manager: NetworkManager, reservation_mgr: ReservationManager) -> dict[str, Any]:
    """Status, the reasons for `degraded`, the antennas and the detailed checks.

    Shared by /status (verdict and reasons) and /monitoring (detail), so
    they never disagree (BUG-2). Host-command checks come from the background
    loop (wilab.health); nothing here runs a command.
    """
    health = manager.health.current()
    snapshot = manager.active.copy()
    checks: dict[str, Any] = {
        "commands": {"stuck": stuck_commands()},
        "loops": {"stale": heartbeat.stale_loops()},
        # Networks stopped since the check are ignored; networks started since
        # then are judged at the next check (RACE-2).
        **health.for_active(set(snapshot)),
    }
    settled = [device for device in snapshot if device in health.settled]
    internet_needed = any(device in health.internet for device in settled)

    reasons: list[dict[str, Any]] = []
    antennas = []
    reservations = reservation_mgr.snapshot()
    recovery = reservation_mgr.recovery_snapshot()
    cleanup_failures = manager.cleanup_failures()
    for n in manager.devices.all():
        entry: dict[str, Any] = {"display_name": n.display_name, "interface": n.interface}
        reservation = reservations.get(n.device_id)
        # API-1: the same reservation object as the reservation and network answers.
        entry["reservation"] = None if reservation is None else {
            "expires_at": format_utc_timestamp(reservation.expires_at),
            "expires_in": reservation.expires_in,
        }
        entry["network_active"] = n.device_id in snapshot
        if reservation is not None and (runtime_state := manager.watchdog.state(reservation)):
            entry["runtime_state"] = runtime_state
            reasons.append(_reason("network_being_repaired", n.interface, state=runtime_state))
        elif reservation is not None and (job := manager.start_job(reservation)) is not None:
            entry["runtime_state"] = job.state  # starting or start_failed: not a fault
        elif manager.stop_failed(n.device_id):
            # Same state as GET .../network; its half-stopped processes are not
            # reported again as hostapd/dnsmasq/NAT problems below.
            entry["runtime_state"] = "stop_failed"
            reasons.append(_reason("network_stop_incomplete", n.interface))
        if n.device_id in recovery:
            state = "recovering" if recovery[n.device_id] else "unavailable"
            entry["recovery_state"] = state
            reasons.append(_reason("antenna_quarantined", n.interface, state=state))
        if count := cleanup_failures.get(n.device_id):
            # The release answered 200; the background sweep repeats the cleanup (WD-6).
            reasons.append(_reason(
                "cleanup_failed", n.interface, count=count, wait=ceil(manager.cleanup_wait(n.device_id)),
            ))
        antennas.append(entry)
    for check, code in (
        ("hostapd", "hostapd_not_running"), ("dnsmasq", "dnsmasq_not_running"),
        ("iptables_nat", "nat_rule_missing"),
    ):
        for device in checks[check]["missing"]:
            if not manager.stop_failed(device):
                reasons.append(_reason(code, device))
    upstream = checks["upstream_interface"]
    if internet_needed and upstream.get("reachable") is not True:
        reasons.append(_reason("upstream_unreachable", name=upstream.get("name")))
    if checks["commands"]["stuck"]:
        reasons.append(_reason("command_stuck", count=checks["commands"]["stuck"]))
    if checks["loops"]["stale"]:
        reasons.append(_reason("loop_stalled", loops=", ".join(checks["loops"]["stale"])))

    # in_use: someone holds an antenna, with or without a network (not only active networks).
    status = "degraded" if reasons else ("in_use" if reservations else "standby")
    return {
        "restart_required": _restart_required(checks.get("updates") or {}),
        "status": status, "degraded_reasons": reasons, "active_networks": len(snapshot),
        "antennas": antennas, "checks": checks, "checked_at": health.checked_at,
    }


def _restart_required(pending: dict[str, Any]) -> dict[str, Any] | None:
    """`restart_required` of /status: None, or what needs a restart since when (never automatic)."""
    service = bool(pending.get("service_restart_required"))
    system = bool(pending.get("system_reboot_required"))
    if not service and not system:
        return None
    return {
        "service": service, "system": system, "since": pending.get("since"),
        "message": RESTART_MESSAGES[(service, system)],
    }


def _system_status(
    manager: NetworkManager, config: AppConfig, reservation_mgr: ReservationManager
) -> dict[str, Any]:
    view = _assess(manager, reservation_mgr)
    return {
        "version": __version__,
        "status": view["status"],
        "degraded_reasons": view["degraded_reasons"],
        "active_networks": view["active_networks"],
        "antennas": view["antennas"],
        "restart_required": view["restart_required"],
        "reservation_policy": {
            "min_seconds": config.min_timeout,
            "max_seconds": config.max_timeout,
            "allow_unlimited": config.allow_unlimited_reservation,
        },
    }


@router.get(
    "/monitoring",
    summary="Read the detailed health checks",
    responses={
        200: {
            "description": "The detail behind `status` and `degraded_reasons` of `GET /status`.",
            "content": {"application/json": {"example": {
                "status": "in_use", "degraded_reasons": [],
                "checked_at": "2026-11-25T18:30:00Z", "check_interval_seconds": 10,
                "checks": {**_CHECKS_OK_EXAMPLE,
                           "hostapd": {"running": True, "instances": 1, "missing": []},
                           "dnsmasq": {"running": True, "instances": 1, "missing": []}},
            }}},
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
def monitoring(
    manager: NetworkManager = Depends(get_manager),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    _: bool = Depends(require_token),
):
    """Detailed health checks, for operators and a monitoring view.

    `GET /status` gives the verdict and its reasons; this call gives the detail
    of every check. Checks that run host commands are refreshed every
    `check_interval_seconds` in the background (`checked_at` is the last run);
    `commands` and `loops` are read live.

    | Check | Meaning |
    |---|---|
    | `commands.stuck` | Host commands that did not exit even after SIGKILL (hung driver). |
    | `loops.stale` | Background loops that have not run for 3 minutes. |
    | `hostapd`, `dnsmasq` | Every settled network has its process alive; `missing` lists the others. |
    | `iptables_nat` | Every settled network with Internet has its `wilab-nat-<interface>` rule; `missing` lists the others, `errors` the failures reading the rules. |
    | `updates` | Security updates that need a restart: libraries this process loaded that an update replaced (`service_restart_required`, `replaced_libraries`), and a reboot asked by an update or a newer installed kernel (`system_reboot_required`, `reboot_packages`); `since` is when first seen. |
    | `upstream_interface` | Host uplink state UP (or UNKNOWN with LOWER_UP) and an IPv4 address; it counts only while a network has Internet. |

    A network with a start, stop or restore in progress is not judged.
    """
    view = _assess(manager, reservation_mgr)
    return {
        "status": view["status"],
        "degraded_reasons": view["degraded_reasons"],
        "checked_at": view["checked_at"],
        "check_interval_seconds": int(health_module.CHECK_INTERVAL),
        "checks": view["checks"],
    }
