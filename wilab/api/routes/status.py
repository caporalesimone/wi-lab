"""System status endpoint."""

from typing import Any

from fastapi import APIRouter, Depends

from ...config import CAPABILITY_REGISTRY
from ...wifi.manager import NetworkManager
from ...reservation import ReservationManager
from ...api.dependencies import get_config, get_manager, get_reservation_manager
from ...api.auth import require_token
from ...network.commands import execute_command, CommandError
from ...version import __version__

router = APIRouter(tags=["System"])


_STATUS_EXAMPLE = {
    "version": "4.0.0",
    "status": "ok",
    "active_networks": 1,
    "networks": [
        {
            "display_name": "bench-antenna-1",
            "interface": "wlxbc071dc527d6",
            "capabilities": ["2.4ghz", "5ghz"],
            "reserved": True,
            "reservation_remaining_seconds": 842,
        },
        {
            "display_name": "bench-antenna-2",
            "interface": "wlx7820512451b4",
            "capabilities": ["2.4ghz"],
            "reserved": False,
            "reservation_remaining_seconds": None,
        },
    ],
    "capabilities_catalogue": [
        {"id": "2.4ghz", "label": "2.4 GHz", "kind": "radio",
         "total_devices": 2, "available_devices": 1},
        {"id": "5ghz", "label": "5 GHz", "kind": "radio",
         "total_devices": 1, "available_devices": 0},
    ],
    "reservation_policy": {"min_seconds": 60, "max_seconds": 86400, "allow_unlimited": False},
    "checks": {
        "dnsmasq": {"running": True, "instances": 1},
        "iptables_nat": {"configured": True, "errors": []},
        "upstream_interface": {"name": "eth0", "up": True, "has_ip": True, "reachable": True},
    },
}


@router.get(
    "/status",
    summary="System status",
    responses={
        200: {
            "description": "System status retrieved successfully",
            "content": {"application/json": {"example": _STATUS_EXAMPLE}},
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
async def system_status(
    manager: NetworkManager = Depends(get_manager), 
    config=Depends(get_config),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    _: bool = Depends(require_token)
):
    """
    Comprehensive system status including interfaces and health check.

    Returns:
        dict: Contains:
            - version: Software version
            - status: Overall health (ok|degraded|standby)
            - active_networks: Number of active networks
            - networks: One entry per managed device: `display_name`, `interface`,
              `capabilities` (enabled ones, sorted), `reserved` and
              `reservation_remaining_seconds` (null when free or unlimited)
            - capabilities_catalogue: What the lab can offer, one entry per capability
              that at least one device has: `id`, `label`, `kind`, `total_devices`,
              `available_devices` (free right now). Build your requests from this list
              rather than hard-coding ids
            - reservation_policy: `min_seconds`, `max_seconds`, `allow_unlimited`
            - checks: Component health details
    """
    status_data: dict[str, Any] = {
        "version": __version__,
        "status": "ok",
    }

    # === HEALTH CHECK ===
    health_data: dict[str, Any] = {"checks": {}}

    # Check dnsmasq instances
    dhcp_status = manager.dhcp_server.status()
    health_data["checks"]["dnsmasq"] = {
        "running": dhcp_status.get("running", False),
        "instances": len(dhcp_status.get("instances", [])),
    }

    # Check iptables NAT configuration
    try:
        nat_status = manager.nat_manager.status()
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

    # Determine overall status
    has_active_networks = len(manager.active) > 0
    
    if not has_active_networks:
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
        status_data["active_networks"] = len(manager.active)

    # Add networks with reservation info, checks, and rest of data
    networks_info = []
    # Counts for the capability catalogue, accumulated in the same pass: both come from
    # data already in hand, so the catalogue costs this endpoint no extra lookups.
    total_by_cap: dict[str, int] = {cap.value: 0 for cap in CAPABILITY_REGISTRY}
    free_by_cap: dict[str, int] = {cap.value: 0 for cap in CAPABILITY_REGISTRY}

    for n in config.networks:
        entry: dict = {"display_name": n.display_name, "interface": n.interface}
        reserved = reservation_mgr.is_device_reserved(n.device_id)
        if reserved:
            entry["reserved"] = True
            # Find the reservation for this device to report remaining time
            for r in reservation_mgr.all_active():
                if r.device_id == n.device_id:
                    entry["reservation_remaining_seconds"] = r.expires_in  # None for unlimited
                    break
        else:
            entry["reserved"] = False
            entry["reservation_remaining_seconds"] = None

        # Enabled ids only, sorted: the wire carries facts, not the administrator's
        # `false` entries, and sorting keeps responses byte-stable and diffable.
        caps = config.capabilities_for(n.device_id)
        entry["capabilities"] = caps
        for cap_id in caps:
            total_by_cap[cap_id] += 1
            if not reserved:
                free_by_cap[cap_id] += 1
        networks_info.append(entry)
    status_data["networks"] = networks_info

    # Iterating the registry (not the union of device sets) keeps the order stable and
    # label ownership in one place, so a new capability reaches the UI with no frontend
    # release. A capability no device enables is omitted: offering a filter that can
    # never match is worse than not offering it, and requesting it anyway yields the
    # more precise 422.
    status_data["capabilities_catalogue"] = [
        {
            "id": cap.value,
            "label": definition.label,
            "kind": definition.kind.value,
            "total_devices": total_by_cap[cap.value],
            "available_devices": free_by_cap[cap.value],
        }
        for cap, definition in CAPABILITY_REGISTRY.items()
        if total_by_cap[cap.value] > 0
    ]
    status_data["reservation_policy"] = {
        "min_seconds": config.min_timeout,
        "max_seconds": config.max_timeout,
        "allow_unlimited": config.allow_unlimited_reservation,
    }
    status_data.update(health_data)
    return status_data


@router.get(
    "/debug",
    summary="Debug information",
    responses={
        200: {"description": "Debug information retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
async def debug_info(
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
        dict: Complete system debug information. Each managed interface includes its
        `capabilities` and the `reservation_id` currently holding it, if any.
    """
    # === DETERMINE OVERALL STATUS ===
    has_active_networks = len(manager.active) > 0
    
    # Check dnsmasq
    dhcp_status = manager.dhcp_server.status()
    dhcp_running = dhcp_status.get("running", False)
    
    # Check iptables NAT
    try:
        nat_status = manager.nat_manager.status()
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
    if not has_active_networks:
        status = "standby"
    else:
        all_ok = dhcp_running and nat_configured and upstream_reachable
        status = "ok" if all_ok else "degraded"
    
    # === GET DETAILED SERVICES INFO ===
    services = manager.services_status()
    
    debug_data = {
        "version": __version__,
        "status": status,
        
        "system": {
            "active_networks": len(manager.active),
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
                    "capabilities": config.capabilities_for(n.device_id),
                    "reservation_id": next(
                        (r.reservation_id for r in reservation_mgr.all_active()
                         if r.device_id == n.device_id),
                        None,
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
