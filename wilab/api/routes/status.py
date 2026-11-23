"""System status endpoint."""

from typing import Any

from fastapi import APIRouter, Depends

from ... import heartbeat
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
    "dnsmasq": {"running": False, "instances": 0},
    "iptables_nat": {"configured": True, "errors": []},
    "upstream_interface": {"name": "eth0", "up": True, "has_ip": True, "reachable": True},
}

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
                        "checks": {**_CHECKS_OK_EXAMPLE, "dnsmasq": {"running": True, "instances": 1}},
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
                        "checks": {**_CHECKS_OK_EXAMPLE, "dnsmasq": {"running": False, "instances": 0}},
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
    - networks are active and a check in `checks` fails (`dnsmasq.running`,
      `iptables_nat.configured` or `upstream_interface.reachable` is false).

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
              (`runtime_state` during AP/DHCP restoration or DHCP failure)
            - status: Overall health (ok|degraded|standby)
            - active_networks: Number of active networks
            - checks: Component health details
    """
    return _system_status(manager, config, reservation_mgr)


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

    # Check dnsmasq instances
    dhcp_status = manager.dhcp_server.status()
    health_data["checks"]["dnsmasq"] = {
        "running": dhcp_status.get("running", False),
        "instances": len(dhcp_status.get("instances", [])),
    }

    # Check iptables NAT configuration
    try:
        nat_status = manager.firewall_status()
        has_nat_rules = bool(
            nat_status.get("nat") and "MASQUERADE" in nat_status.get("nat", "")
        )
        health_data["checks"]["iptables_nat"] = {
            "configured": has_nat_rules,
            "errors": nat_status.get("errors", []),
        }
    except Exception as e:
        health_data["checks"]["iptables_nat"] = {"configured": False, "error": str(e)}

    # Check upstream interface reachability
    try:
        upstream = manager.nat_manager.get_upstream_interface()
        ip_output = execute_command(["ip", "addr", "show", upstream])
        has_ip = "inet " in ip_output
        is_up = "state UP" in ip_output or "UP" in ip_output
        health_data["checks"]["upstream_interface"] = {
            "name": upstream,
            "up": is_up,
            "has_ip": has_ip,
            "reachable": is_up and has_ip,
        }
    except CommandError as e:
        health_data["checks"]["upstream_interface"] = {
            "name": config.upstream_interface,
            "reachable": False,
            "error": str(e),
        }
    except Exception as e:
        health_data["checks"]["upstream_interface"] = {
            "reachable": False,
            "error": str(e),
        }

    active_count = len(manager.active)
    
    if not active_count:
        # Standby - service is healthy but no networks are active
        status_data["status"] = "standby"
        status_data["active_networks"] = 0
    else:
        # Normal operation - check component health
        all_ok = all(
            [
                health_data["checks"]["dnsmasq"].get("running") is not False,
                health_data["checks"]["iptables_nat"].get("configured") is not False,
                health_data["checks"]["upstream_interface"].get("reachable") is not False,
            ]
        )
        status_data["status"] = "ok" if all_ok else "degraded"
        status_data["active_networks"] = active_count

    # Add networks with reservation info, checks, and rest of data
    networks_info = []
    reservations = reservation_mgr.snapshot()
    recovery = reservation_mgr.recovery_snapshot()
    runtime_degraded = False
    for n in config.networks:
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


@router.get(
    "/debug",
    responses={
        200: {"description": "Debug information retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
def debug_info(
    manager: NetworkManager = Depends(get_manager),
    config=Depends(get_config),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    _: bool = Depends(require_token),
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
    active_count = len(manager.active)
    
    # Check dnsmasq
    dhcp_status = manager.dhcp_server.status()
    dhcp_running = dhcp_status.get("running", False)
    
    # Check iptables NAT
    try:
        nat_status = manager.firewall_status()
        nat_configured = bool(
            nat_status.get("nat") and "MASQUERADE" in nat_status.get("nat", "")
        )
        nat_errors = nat_status.get("errors", [])
    except Exception as e:
        nat_configured = False
        nat_errors = [str(e)]
    
    # Check upstream interface
    try:
        upstream = manager.nat_manager.get_upstream_interface()
        ip_output = execute_command(["ip", "addr", "show", upstream])
        upstream_up = "state UP" in ip_output or "UP" in ip_output
        upstream_has_ip = "inet " in ip_output
        upstream_reachable = upstream_up and upstream_has_ip
        upstream_name = upstream
    except CommandError:
        upstream_reachable = False
        upstream_name = config.upstream_interface
        upstream_up = False
        upstream_has_ip = False
    except Exception:
        upstream_reachable = False
        upstream_name = None
        upstream_up = False
        upstream_has_ip = False
    
    # Determine overall status
    if not active_count:
        status = "standby"
    else:
        all_ok = dhcp_running and nat_configured and upstream_reachable
        status = "ok" if all_ok else "degraded"
    
    # === GET DETAILED SERVICES INFO ===
    services = manager.services_status()
    reservations = reservation_mgr.snapshot()
    
    debug_data = {
        "version": __version__,
        "status": status,
        
        "system": {
            "active_networks": active_count,
            "configured_networks": len(config.networks),
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
                for n in config.networks
            ],
        },
        
        "raw_diagnostics": {
            "iptables_nat_rules": nat_status.get("nat", "") if 'nat_status' in locals() else "",
            "iptables_forward_rules": nat_status.get("forward", "") if 'nat_status' in locals() else "",
        },
    }

    return debug_data
