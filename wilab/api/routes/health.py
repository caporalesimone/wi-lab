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
        # Standby mode - service is healthy but no networks are active
        health_data["status"] = "standby"
        health_data["mode"] = "standby"
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
        health_data["mode"] = "active"
        health_data["active_networks"] = len(manager.active)

    return health_data


@router.get("/status/services")
async def services_status(
    manager: NetworkManager = Depends(get_manager),
):
    """
    Get status of system services (dnsmasq, hostapd, iptables).

    Returns:
        dict: Detailed status of each service managing the WiFi AP infrastructure.
    """
    return manager.services_status()
