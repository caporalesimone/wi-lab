"""System status endpoint."""

import json
from typing import Any

from fastapi import APIRouter, Depends

from ... import heartbeat
from ...api.auth import maintenance_router as protected_router
from ...api.auth import require_token
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...config import AppConfig
from ...network.commands import CommandError, execute_command, stuck_commands
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
                "`degraded` means at least one adapter is quarantined (`recovery_state`), a "
                "reserved network is being repaired or has lost DHCP (`runtime_state`), a "
                "host command is stuck in the kernel (`checks.commands.stuck`), a "
                "background loop stalled (`checks.loops.stale`), or a "
                "health check failed while networks are active. A reserved or quarantined "
                "adapter is not allocatable."
            ),
            "content": {"application/json": {"examples": {
                "standby": {
                    "summary": "standby - no network active, every adapter healthy",
                    "value": {
                        "version": "4.0.0", "status": "standby", "active_networks": 0,
                        "networks": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": False,
                             "reservation_remaining_seconds": None},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": False,
                             "reservation_remaining_seconds": None},
                        ],
                        "reservation_policy": _POLICY_EXAMPLE,
                        "checks": _CHECKS_OK_EXAMPLE,
                    },
                },
                "ok": {
                    "summary": "ok - networks active and healthy",
                    "value": {
                        "version": "4.0.0", "status": "ok", "active_networks": 1,
                        "networks": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": True,
                             "reservation_remaining_seconds": 540},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": False,
                             "reservation_remaining_seconds": None},
                        ],
                        "reservation_policy": _POLICY_EXAMPLE,
                        "checks": {**_CHECKS_OK_EXAMPLE,
                                   "hostapd": {"running": True, "instances": 1, "missing": []},
                                   "dnsmasq": {"running": True, "instances": 1, "missing": []}},
                    },
                },
                "degraded_quarantine": {
                    "summary": "degraded - one adapter quarantined, another being repaired",
                    "value": {
                        "version": "4.0.0", "status": "degraded", "active_networks": 1,
                        "networks": [
                            {"display_name": "Antenna A", "interface": "wlan0", "reserved": False,
                             "reservation_remaining_seconds": None, "recovery_state": "unavailable"},
                            {"display_name": "Antenna B", "interface": "wlan1", "reserved": True,
                             "reservation_remaining_seconds": 54, "runtime_state": "restoring_ap"},
                        ],
                        "reservation_policy": _POLICY_EXAMPLE,
                        "checks": _CHECKS_OK_EXAMPLE,
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
    Comprehensive system status including interfaces and health check.

    Overall `status`:

    | Value | Meaning |
    |---|---|
    | `standby` | No network is active and no adapter is quarantined. |
    | `ok` | Networks are active and every health check passes. |
    | `degraded` | At least one of the conditions below. |

    `degraded` is set when:

    - an adapter has `recovery_state` (quarantine): `recovering` means a USB
      reset and probe are in progress; `unavailable` means no reset is running
      and Wi-Lab re-probes it periodically (30 s, then backing off to every
      15 min). Either may return to the pool by itself;
    - a reserved network has `runtime_state`: `restoring_ap`, `restoring_dhcp`
      (the watchdog is repairing it), `dhcp_failed` (DHCP could not be
      repaired alone; the whole network is restarted on the next tick) or
      `restore_failed` (AP down after a failed restart; the watchdog retries
      with backoff);
    - a host command (`ip`, `iw`, `tc`, ...) did not exit even after SIGKILL
      (`checks.commands.stuck` > 0). It is stuck in the kernel, usually a hung
      Wi-Fi driver; Wi-Lab no longer waits for it, but the adapter may need a
      reset or the host a reboot. The count drops when the process exits;
    - a background loop (`expiry`, `discovery`, `reprobe`, `watchdog:<if>`)
      has not run for 3 minutes (`checks.loops.stale`). Wi-Lab restarts
      itself through the systemd watchdog as soon as no reservation is
      active and no USB recovery is running; until then it keeps serving;
    - networks are active and a check in `checks` fails. A network with a
      start, stop or restore in progress is not judged, so a create/delete
      never makes the status flap to `degraded`. The checks look at
      Wi-Lab's own processes and rules, per network:
      `hostapd.running` / `dnsmasq.running` (every network has its process
      alive; `missing` lists the others), `iptables_nat.configured` (every
      network with Internet has its `wilab-nat-<interface>` rule; other
      software's MASQUERADE rules do not count; `missing` lists the others)
      and `upstream_interface.reachable` (state UP, or UNKNOWN with
      LOWER_UP, and an IPv4 address; it counts only when a network has
      Internet enabled).

    A quarantined adapter is never allocatable, even with `reserved: false`.
    Clients should poll this endpoint, show `degraded` to the user together
    with the affected adapter, and not send creates for a network in
    `restoring_ap`/`restoring_dhcp`. The former owner of a quarantined adapter
    is told once, by `503 / 1003` on the create; its reservation ID then
    returns `404`. A status response is not a reservation.

    Returns:
        dict: Contains:
            - version: Software version
            - networks: List of managed interfaces
              (`runtime_state` during AP/DHCP restoration or DHCP failure).
              What a network on each antenna can use is in `GET /antennas/{interface}`
            - status: Overall health (ok|degraded|standby)
            - active_networks: Number of active networks
            - checks: Component health details
    """
    return _system_status(manager, config, reservation_mgr)


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


def _nat_check(
    manager: NetworkManager, snapshot: dict[str, Any], settled: list[str],
) -> dict[str, Any]:
    """Wi-Lab's own NAT rule exists for every settled network with Internet (BUG-2).

    Docker's or libvirt's MASQUERADE rules do not count, and a network without
    Internet needs none.
    """
    expected = [device for device in settled if snapshot[device].internet_enabled]
    try:
        rules = manager.firewall_status()
    except Exception as exc:  # noqa: BLE001 - reported in the check, never fails /status
        return {"configured": not expected, "missing": expected, "errors": [str(exc)]}
    nat = rules.get("nat") or ""
    missing = [device for device in expected if f"wilab-nat-{device}" not in nat]
    return {"configured": not missing, "missing": missing, "errors": rules.get("errors", [])}


def _upstream_check(manager: NetworkManager, config: AppConfig) -> dict[str, Any]:
    """Operational state and IPv4 address of the upstream, from `ip -j` (BUG-2).

    The old text match found "UP" in `LOWER_UP` or in the UP flag of a link
    whose state is DOWN. A link with state UNKNOWN (VPN, some virtual NICs) is
    up when the kernel reports LOWER_UP.
    """
    try:
        name = manager.nat_manager.get_upstream_interface()
        links = json.loads(execute_command(["ip", "-j", "addr", "show", "dev", name]) or "[]")
    except (CommandError, RuntimeError, ValueError) as exc:
        return {"name": config.upstream_interface, "reachable": False, "error": str(exc)}
    link = links[0] if links else {}
    state = link.get("operstate")
    up = state == "UP" or (state == "UNKNOWN" and "LOWER_UP" in link.get("flags", []))
    has_ip = any(a.get("family") == "inet" for a in link.get("addr_info", []))
    return {"name": name, "up": up, "has_ip": has_ip, "reachable": up and has_ip}


def _system_status(
    manager: NetworkManager, config: AppConfig, reservation_mgr: ReservationManager
) -> dict[str, Any]:
    status_data: dict[str, Any] = {
        "version": __version__,
        "status": "ok",
    }

    # === HEALTH CHECK ===
    health_data: dict[str, Any] = {"checks": {}}
    stuck = stuck_commands()
    health_data["checks"]["commands"] = {"stuck": stuck}
    stale_loops = heartbeat.stale_loops()
    health_data["checks"]["loops"] = {"stale": stale_loops}

    # RACE-2: one snapshot of the active networks for the whole answer, and health is
    # judged only on networks with no operation in progress. A start publishes its
    # network only when it is complete, but a stop removes DHCP and NAT before it
    # leaves `active`: judging that network would report a passing `degraded`.
    snapshot = manager.active.copy()
    settled = [device for device in snapshot if _not_busy(manager, device)]
    active_count = len(snapshot)
    checks = health_data["checks"]
    # BUG-2: each check looks at Wi-Lab's own processes and rules, per network.
    checks["hostapd"] = _process_check(settled, manager.hostapd_manager.is_running)
    checks["dnsmasq"] = _process_check(settled, manager.dhcp_server.is_running)
    checks["iptables_nat"] = _nat_check(manager, snapshot, settled)
    checks["upstream_interface"] = _upstream_check(manager, config)
    internet_needed = any(snapshot[d].internet_enabled for d in settled)

    if not active_count:
        # Standby - service is healthy but no networks are active
        status_data["status"] = "standby"
        status_data["active_networks"] = 0
    else:
        # Normal operation - check component health
        all_ok = (
            checks["hostapd"]["running"]
            and checks["dnsmasq"]["running"]
            and checks["iptables_nat"]["configured"]
            and (checks["upstream_interface"].get("reachable") is True or not internet_needed)
        )
        status_data["status"] = "ok" if all_ok or not settled else "degraded"
        status_data["active_networks"] = active_count

    # Add networks with reservation info, checks, and rest of data
    networks_info = []
    reservations = reservation_mgr.snapshot()
    recovery = reservation_mgr.recovery_snapshot()
    runtime_degraded = False
    for n in config.antennas:
        entry: dict = {"display_name": n.display_name, "interface": n.interface}
        reservation = reservations.get(n.device_id)
        entry["reserved"] = reservation is not None
        entry["reservation_remaining_seconds"] = reservation.expires_in if reservation else None
        if reservation is not None and (runtime_state := manager.watchdog.state(reservation)):
            entry["runtime_state"] = runtime_state
            runtime_degraded = True
        if n.device_id in recovery:
            entry["recovery_state"] = "recovering" if recovery[n.device_id] else "unavailable"
        networks_info.append(entry)
    status_data["networks"] = networks_info
    if recovery or runtime_degraded or stuck or stale_loops:
        status_data["status"] = "degraded"
    status_data["reservation_policy"] = {
        "min_seconds": config.min_timeout,
        "max_seconds": config.max_timeout,
        "allow_unlimited": config.allow_unlimited_reservation,
    }
    status_data.update(health_data)
    return status_data


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
    summary = _system_status(manager, config, reservation_mgr)
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
