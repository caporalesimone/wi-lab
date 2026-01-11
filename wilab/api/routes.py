from fastapi import APIRouter, Depends, HTTPException, Body
from ..models import NetworkCreateRequest, NetworkStatus, ClientsResponse, TxPowerRequest, TxPowerInfo
from ..api.auth import require_token
from ..api.dependencies import get_config, get_manager
from ..wifi.manager import NetworkManager

router = APIRouter(prefix="/api/v1", tags=["Wi-Lab API"])

@router.get("/interfaces")
async def list_interfaces(config = Depends(get_config)):
    """List all managed WiFi interfaces configured in the system."""
    return [{"net_id": n.net_id, "interface": n.interface} for n in config.networks]

@router.get("/health")
async def health(manager: NetworkManager = Depends(get_manager),
                 config = Depends(get_config)):
    """Comprehensive health check for Wi-Lab service."""
    health_data = {
        "status": "ok",
        "version": None,
        "checks": {}
    }
    
    # Check dnsmasq instances
    dhcp_status = manager.dhcp_server.status()
    health_data["checks"]["dnsmasq"] = {
        "running": dhcp_status.get("running", False),
        "instances": len(dhcp_status.get("instances", []))
    }
    
    # Check iptables NAT configuration
    try:
        nat_status = manager.nat_manager.status()
        has_nat_rules = bool(nat_status.get("nat") and "MASQUERADE" in nat_status.get("nat", ""))
        health_data["checks"]["iptables_nat"] = {
            "configured": has_nat_rules,
            "errors": nat_status.get("errors", [])
        }
    except Exception as e:
        health_data["checks"]["iptables_nat"] = {"configured": False, "error": str(e)}
    
    # Check upstream interface reachability
    try:
        upstream = manager.nat_manager.get_upstream_interface()
        from ..network.commands import execute_command, CommandError
        # Check if interface has IP and is up
        ip_output = execute_command(["ip", "addr", "show", upstream])
        has_ip = "inet " in ip_output
        is_up = "state UP" in ip_output or "UP" in ip_output
        health_data["checks"]["upstream_interface"] = {
            "name": upstream,
            "up": is_up,
            "has_ip": has_ip,
            "reachable": is_up and has_ip
        }
    except CommandError as e:
        health_data["checks"]["upstream_interface"] = {
            "name": config.upstream_interface,
            "reachable": False,
            "error": str(e)
        }
    except Exception as e:
        health_data["checks"]["upstream_interface"] = {"reachable": False, "error": str(e)}
    
    # Determine overall status
    all_ok = all([
        health_data["checks"]["dnsmasq"].get("running") is not False,
        health_data["checks"]["iptables_nat"].get("configured") is not False,
        health_data["checks"]["upstream_interface"].get("reachable") is not False
    ])
    
    health_data["status"] = "ok" if all_ok else "degraded"
    
    return health_data

@router.get("/status/services")
async def services_status(manager: NetworkManager = Depends(get_manager),
                          _auth: bool = Depends(require_token)):
    """Get status of system services (dnsmasq, hostapd, iptables)."""
    return manager.services_status()

@router.post("/interface/{net_id}/network", response_model=NetworkStatus)
async def start_network(net_id: str,
                        req: NetworkCreateRequest = Body(
                            ..., 
                            examples={
                                "default": {
                                    "summary": "Typical network configuration",
                                    "description": "2.4GHz WPA2 network with 1-hour timeout and Internet enabled. Returns expires_at in yyyy-mm-dd HH:MM:SS format.",
                                    "value": {
                                        "ssid": "TestNetwork",
                                        "channel": 5,
                                        "password": "testpass123",
                                        "encryption": "wpa2",
                                        "band": "2.4ghz",
                                        "timeout": 3600,
                                        "internet_enabled": True
                                    }
                                }
                            }
                        ),
                        manager: NetworkManager = Depends(get_manager),
                        _auth: bool = Depends(require_token)):
    """
    Create and start a WiFi network in AP mode.
    
    Returns:
        NetworkStatus: Complete network configuration including password and expiration time.
    
    Raises:
        HTTPException 404: Unknown net_id
        HTTPException 409: Network already active (stop it first)

    Example request body:
    {
        "ssid": "TestNetwork",
        "channel": 5,
        "password": "testpass123",
        "encryption": "wpa2",
        "band": "2.4ghz",
        "timeout": 3600,
        "internet_enabled": true
    }
    """
    try:
        return manager.start_network(net_id, req)
    except ValueError as e:
        error_msg = str(e)
        # Return 409 Conflict if network is already active, 404 for unknown net_id
        if "already active" in error_msg.lower():
            raise HTTPException(status_code=409, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)

@router.delete("/interface/{net_id}/network")
async def stop_network(net_id: str,
                       manager: NetworkManager = Depends(get_manager),
                       _auth: bool = Depends(require_token)):
    """
    Stop an active WiFi network.
    
    Returns:
        dict: Confirmation with net_id of stopped network.
    """
    manager.stop_network(net_id)
    return {"net_id": net_id}

@router.get("/interface/{net_id}/network", response_model=NetworkStatus)
async def get_network(net_id: str,
                      manager: NetworkManager = Depends(get_manager),
                      _auth: bool = Depends(require_token)):
    """
    Get complete network configuration and status.
    
    Returns:
        NetworkStatus: Full network details including password, expiration time (expires_at in yyyy-mm-dd HH:MM:SS format, expires_in in seconds remaining), and all configuration.
    """
    st = manager.get_status(net_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return st

@router.get("/interface/{net_id}/status")
async def get_status(net_id: str,
                     manager: NetworkManager = Depends(get_manager),
                     _auth: bool = Depends(require_token)):
    """Get minimal network status (net_id, interface, active flag only)."""
    st = manager.get_status(net_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return {"net_id": st.net_id, "interface": st.interface, "active": st.active}

@router.get("/interface/{net_id}/summary")
async def get_summary(net_id: str,
                      manager: NetworkManager = Depends(get_manager),
                      _auth: bool = Depends(require_token)):
    """Get detailed network summary including DHCP info and connected clients."""
    summary = manager.get_summary(net_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return summary

@router.post("/interface/{net_id}/internet/enable")
async def internet_enable(net_id: str,
                          manager: NetworkManager = Depends(get_manager),
                          _auth: bool = Depends(require_token)):
    """
    Enable Internet access for connected clients (NAT forwarding).
    
    Returns:
        dict: Confirmation with net_id and internet_enabled status.
    """
    try:
        manager.enable_internet(net_id)
        return {"net_id": net_id, "internet_enabled": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/interface/{net_id}/internet/disable")
async def internet_disable(net_id: str,
                           manager: NetworkManager = Depends(get_manager),
                           _auth: bool = Depends(require_token)):
    """
    Disable Internet access for connected clients (remove NAT forwarding).
    
    Returns:
        dict: Confirmation with net_id and internet_enabled status.
    """
    try:
        manager.disable_internet(net_id)
        return {"net_id": net_id, "internet_enabled": False}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/interface/{net_id}/clients", response_model=ClientsResponse)
async def list_clients(net_id: str,
                       manager: NetworkManager = Depends(get_manager),
                       _auth: bool = Depends(require_token)):
    """Get list of connected WiFi clients with their MAC and IP addresses."""
    clients = manager.list_clients(net_id)
    return {"net_id": net_id, "clients": clients}


@router.get("/interface/{net_id}/txpower", response_model=TxPowerInfo)
async def get_tx_power(net_id: str,
                       manager: NetworkManager = Depends(get_manager),
                       _auth: bool = Depends(require_token)):
    """Get current TX power details for an active network."""
    try:
        return manager.get_tx_power_info(net_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/interface/{net_id}/txpower", response_model=TxPowerInfo)
async def set_tx_power(net_id: str,
                       req: TxPowerRequest,
                       manager: NetworkManager = Depends(get_manager),
                       _auth: bool = Depends(require_token)):
    """Set TX power level (1-4) for an active network."""
    try:
        return manager.set_tx_power_level(net_id, req.level)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
