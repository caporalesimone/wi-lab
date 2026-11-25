"""System status endpoint."""

from typing import Any

from fastapi import APIRouter, Depends

from ... import health as health_module
from ... import heartbeat
from ...api.auth import maintenance_router as protected_router
from ...api.auth import require_token
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...config import AppConfig
from ...network.commands import stuck_commands
from ...reservation import ReservationManager
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
}

# /debug is a diagnostic for operators: listed only under Maintenance in Swagger,
# with token and X-Confirm-Password required by the router.
maintenance_router = protected_router()

router = APIRouter(
    tags=["System"],
    responses={503: {"description": "An expired device could not be cleaned up"}},
)


@router.get(
    "/status",
    summary="Read system and adapter status",
    responses={
        200: {
            "description": (
                "Health and allocation snapshot. `status` is `standby`, `ok` or `degraded`; "
                "`degraded` lists why in `degraded_reasons` (quarantined antenna, network "
                "being repaired, dead hostapd or dnsmasq, missing NAT rule, upstream down, "
                "stuck host command, stalled loop). The detail is in `GET /monitoring`. A "
                "reserved or quarantined adapter is not allocatable."
            ),
            "content": {"application/json": {"examples": {
                "standby": {
                    "summary": "standby - no network active, every adapter healthy",
                    "value": {
                        "version": "4.0.0", "status": "standby", "degraded_reasons": [], "active_networks": 0,
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": False,
                             "reservation_remaining_seconds": None},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": False,
                             "reservation_remaining_seconds": None},
                        ],
                        "reservation_policy": _POLICY_EXAMPLE,
                    },
                },
                "ok": {
                    "summary": "ok - networks active and healthy",
                    "value": {
                        "version": "4.0.0", "status": "ok", "degraded_reasons": [], "active_networks": 1,
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": True,
                             "reservation_remaining_seconds": 540},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": False,
                             "reservation_remaining_seconds": None},
                        ],
                        "reservation_policy": _POLICY_EXAMPLE,
                    },
                },
                "degraded_quarantine": {
                    "summary": "degraded - one adapter quarantined, another being repaired",
                    "value": {
                        "version": "4.0.0", "status": "degraded", "active_networks": 1,
                        "degraded_reasons": [
                            {"code": "antenna_quarantined", "interface": "wlan0",
                             "message": "Antenna quarantined (unavailable)"},
                            {"code": "network_being_repaired", "interface": "wlan1",
                             "message": "Network being repaired by the watchdog (restoring_ap)"},
                        ],
                        "antennas": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": False,
                             "reservation_remaining_seconds": None, "recovery_state": "unavailable"},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": True,
                             "reservation_remaining_seconds": 54, "runtime_state": "restoring_ap"},
                        ],
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
    | `standby` | No network is active and nothing is wrong. |
    | `ok` | Networks are active and nothing is wrong. |
    | `degraded` | At least one entry in `degraded_reasons`. |

    Each `degraded_reasons` entry has a stable `code`, the `interface` it
    concerns (or `null`) and a `message` for display:

    | `code` | Meaning |
    |---|---|
    | `antenna_quarantined` | The antenna has `recovery_state`: `recovering` (USB reset and probe running) or `unavailable` (re-probed every 30 s, backing off to 15 min). It may return by itself. Not allocatable, even with `reserved: false`. |
    | `network_being_repaired` | A reserved network has `runtime_state` (`restoring_ap`, `restoring_dhcp`, `dhcp_failed`, `restore_failed`). Its owner waits. |
    | `hostapd_not_running`, `dnsmasq_not_running` | The AP or DHCP process of that network is dead; the watchdog normally repairs it within seconds. |
    | `nat_rule_missing` | That network has Internet enabled but its NAT rule is missing. |
    | `upstream_unreachable` | The host uplink is down or has no IPv4 address while a network has Internet. |
    | `command_stuck` | A host command did not exit even after SIGKILL: usually a hung Wi-Fi driver; the adapter may need a reset. |
    | `loop_stalled` | A background loop has not run for 3 minutes; Wi-Lab restarts itself when idle. |

    The detail of every check is in `GET /monitoring`. Checks that run host
    commands are refreshed every 10 s in the background: this call runs no
    command and answers at once. A network with a start, stop or restore in
    progress is not judged, so a create or delete never makes the status flap.

    The former owner of a quarantined antenna is told once, by `503 / 1003` on
    the create (or `404` afterwards). What a network on each antenna can use is
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
}


def _reason(code: str, interface: str | None = None, **values: Any) -> dict[str, Any]:
    return {"code": code, "interface": interface, "message": REASON_MESSAGES[code].format(**values)}


def _assess(
    manager: NetworkManager, config: AppConfig, reservation_mgr: ReservationManager,
) -> dict[str, Any]:
    """Status, the reasons for `degraded`, the antennas and the detailed checks.

    Shared by /status (verdict and reasons), /monitoring (detail) and /debug, so
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
    for n in config.antennas:
        entry: dict[str, Any] = {"display_name": n.display_name, "interface": n.interface}
        reservation = reservations.get(n.device_id)
        entry["reserved"] = reservation is not None
        entry["reservation_remaining_seconds"] = reservation.expires_in if reservation else None
        if reservation is not None and (runtime_state := manager.watchdog.state(reservation)):
            entry["runtime_state"] = runtime_state
            reasons.append(_reason("network_being_repaired", n.interface, state=runtime_state))
        if n.device_id in recovery:
            state = "recovering" if recovery[n.device_id] else "unavailable"
            entry["recovery_state"] = state
            reasons.append(_reason("antenna_quarantined", n.interface, state=state))
        antennas.append(entry)
    for device in checks["hostapd"]["missing"]:
        reasons.append(_reason("hostapd_not_running", device))
    for device in checks["dnsmasq"]["missing"]:
        reasons.append(_reason("dnsmasq_not_running", device))
    for device in checks["iptables_nat"]["missing"]:
        reasons.append(_reason("nat_rule_missing", device))
    upstream = checks["upstream_interface"]
    if internet_needed and upstream.get("reachable") is not True:
        reasons.append(_reason("upstream_unreachable", name=upstream.get("name")))
    if checks["commands"]["stuck"]:
        reasons.append(_reason("command_stuck", count=checks["commands"]["stuck"]))
    if checks["loops"]["stale"]:
        reasons.append(_reason("loop_stalled", loops=", ".join(checks["loops"]["stale"])))

    status = "degraded" if reasons else ("ok" if snapshot else "standby")
    return {
        "status": status, "degraded_reasons": reasons, "active_networks": len(snapshot),
        "antennas": antennas, "checks": checks, "checked_at": health.checked_at,
    }


def _system_status(
    manager: NetworkManager, config: AppConfig, reservation_mgr: ReservationManager
) -> dict[str, Any]:
    view = _assess(manager, config, reservation_mgr)
    return {
        "version": __version__,
        "status": view["status"],
        "degraded_reasons": view["degraded_reasons"],
        "active_networks": view["active_networks"],
        "antennas": view["antennas"],
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
                "status": "ok", "degraded_reasons": [],
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
    config=Depends(get_config),
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
    | `upstream_interface` | Host uplink state UP (or UNKNOWN with LOWER_UP) and an IPv4 address; it counts only while a network has Internet. |

    A network with a start, stop or restore in progress is not judged.
    """
    view = _assess(manager, config, reservation_mgr)
    return {
        "status": view["status"],
        "degraded_reasons": view["degraded_reasons"],
        "checked_at": view["checked_at"],
        "check_interval_seconds": int(health_module.CHECK_INTERVAL),
        "checks": view["checks"],
    }


@maintenance_router.get(
    "/debug",
    deprecated=True,
    summary="Read internal debug information (deprecated, will be removed)",
    responses={
        200: {"description": "Debug information retrieved successfully"},
    },
)
def debug_info(
    manager: NetworkManager = Depends(get_manager),
    config=Depends(get_config),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
):
    """
    Comprehensive debug information for troubleshooting.
    
    ⚠️ DEBUG ENDPOINT - DO NOT USE IN FRONTEND WITH FREQUENT POLLING
    
    This endpoint is expensive (150-600ms) and should only be called manually for troubleshooting.
    
    Performance: 150-600ms depending on network count
    
    Returns:
        dict: Complete system debug information.
    """
    return _debug_info(manager, config, reservation_mgr)


def _debug_info(
    manager: NetworkManager, config: AppConfig, reservation_mgr: ReservationManager
) -> dict[str, Any]:
    # === DETERMINE OVERALL STATUS ===
    # Same checks and status as /status (BUG-2): no second, diverging copy.
    summary = _assess(manager, config, reservation_mgr)
    checks = summary["checks"]
    status = summary["status"]
    active_count = summary["active_networks"]
    dhcp_status = manager.dhcp_server.status()
    dhcp_running = checks["dnsmasq"]["running"]
    nat_configured = checks["iptables_nat"]["configured"]
    nat_errors = checks["iptables_nat"].get("errors", [])
    upstream = checks["upstream_interface"]
    upstream_name = upstream.get("name")
    upstream_up = upstream.get("up", False)
    upstream_has_ip = upstream.get("has_ip", False)
    upstream_reachable = upstream.get("reachable", False)
    try:
        nat_status = manager.firewall_status()
    except Exception as exc:  # noqa: BLE001 - debug output must not fail on a firewall read
        nat_status = {"errors": [str(exc)]}

    # === GET DETAILED SERVICES INFO ===
    services = manager.services_status()
    reservations = reservation_mgr.snapshot()
    
    debug_data = {
        "version": __version__,
        "status": status,
        
        "system": {
            "active_networks": active_count,
            "configured_networks": len(config.antennas),
            "upstream_interface": config.upstream_interface,
        },
        
        "services": {
            "dnsmasq": {
                "running": dhcp_running,
                "instances": len(dhcp_status.get("instances", [])),
            },
            "hostapd": {
                "running": services.get("hostapd", {}).get("running", False),
                "instances": len(services.get("hostapd", {}).get("instances", [])),
            },
            "iptables_nat": {
                "configured": nat_configured,
                "errors": nat_errors,
            },
        },
        
        "interfaces": {
            "upstream": {
                "name": upstream_name,
                "up": upstream_up,
                "has_ip": upstream_has_ip,
                "reachable": upstream_reachable,
            },
            "managed": [
                {
                    "display_name": n.display_name,
                    "interface": n.interface,
                    "reservation_id": (
                        reservations[n.device_id].reservation_id
                        if n.device_id in reservations else None
                    ),
                }
                for n in config.antennas
            ],
        },
        
        "raw_diagnostics": {
            "iptables_nat_rules": nat_status.get("nat", ""),
            "iptables_forward_rules": nat_status.get("forward", ""),
        },
    }

    return debug_data
