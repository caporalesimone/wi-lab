"""Health and system status endpoints."""

from fastapi import APIRouter, Depends

from ...wifi.manager import NetworkManager
from ...api.dependencies import get_config, get_manager
from ...network.commands import execute_command, CommandError
from ...version import __version__

router = APIRouter(tags=["System"])


@router.get("/interfaces")
async def list_interfaces(config=Depends(get_config)):
    """
    List all managed WiFi interfaces configured in the system.

    Returns:
        list[dict]: Array of objects containing net_id and interface name for each network.
    """
    return [{"net_id": n.net_id, "interface": n.interface} for n in config.networks]


@router.get("/health")
async def health_check(
    manager: NetworkManager = Depends(get_manager), config=Depends(get_config)
):
    """
    Comprehensive health check for Wi-Lab service.

    Verifies status of:
    - DHCP (dnsmasq) instances
    - NAT (iptables) configuration
    - Upstream interface reachability

    Returns:
        dict: Health status with 'ok' or 'degraded' overall status and component details.
    """
    health_data = {"status": "ok", "version": __version__, "checks": {}}

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
        # Check if interface has IP and is up
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
        health_data["status"] = "standby"
        health_data["active_networks"] = 0
    else:
        # Normal operation - check component health
        all_ok = all(
            [
                health_data["checks"]["dnsmasq"].get("running") is not False,
                health_data["checks"]["iptables_nat"].get("configured") is not False,
                health_data["checks"]["upstream_interface"].get("reachable") is not False,
            ]
        )
        health_data["status"] = "ok" if all_ok else "degraded"
        health_data["active_networks"] = len(manager.active)

    return health_data


@router.get("/debug")
async def debug_info(
    manager: NetworkManager = Depends(get_manager), config=Depends(get_config)
):
    """
    Comprehensive debug information for troubleshooting.
    
    ⚠️ DEBUG ENDPOINT - DO NOT USE IN FRONTEND WITH FREQUENT POLLING
    
    This endpoint is expensive (150-600ms) and should only be called manually for troubleshooting.
    
    Performance: 150-600ms depending on network count
    
    Returns:
        dict: Complete system debug information.
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
    except CommandError as e:
        upstream_reachable = False
        upstream_name = config.upstream_interface
        upstream_up = False
        upstream_has_ip = False
    except Exception as e:
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
                {"net_id": n.net_id, "interface": n.interface}
                for n in config.networks
            ],
        },
        
        "raw_diagnostics": {
            "iptables_nat_rules": nat_status.get("nat", "") if 'nat_status' in locals() else "",
            "iptables_forward_rules": nat_status.get("forward", "") if 'nat_status' in locals() else "",
        },
    }

    return debug_data
