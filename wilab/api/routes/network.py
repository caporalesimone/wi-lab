"""WiFi network lifecycle endpoints (create, delete, query)."""

from fastapi import APIRouter, Depends, HTTPException, Body

from ...models import NetworkCreateRequest, NetworkStatus
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Network"])


@router.post(
    "/{net_id}/network",
    response_model=NetworkStatus,
    responses={
        200: {"description": "Network created and started successfully"},
        404: {"description": "net_id not found in configuration"},
        409: {"description": "Network already active; stop it first"},
    },
)
async def start_network(
    net_id: str,
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
                    "internet_enabled": True,
                },
            }
        },
    ),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Create and start a WiFi network in AP (access point) mode.

    Validates network parameters, allocates a unique DHCP subnet, and starts:
    - hostapd (WiFi access point)
    - dnsmasq (DHCP server)
    - iptables rules (isolation + optional NAT)

    Args:
        net_id: Unique network identifier from config.
        req: Network configuration (SSID, channel, password, band, timeout, etc).

    Returns:
        NetworkStatus: Complete network state including password hash, active flag,
            and expiration time (expires_at, expires_in).

    Raises:
        HTTPException 404: net_id not found in configuration.
        HTTPException 409: Network already active; stop it first.
    """
    try:
        return manager.start_network(net_id, req)
    except ValueError as e:
        error_msg = str(e)
        if "already active" in error_msg.lower():
            raise HTTPException(status_code=409, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)


@router.delete(
    "/{net_id}/network",
    responses={
        200: {"description": "Network stopped successfully"},
        404: {"description": "net_id not found"},
    },
)
async def stop_network(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Stop an active WiFi network and clean up all resources.

    Stops hostapd, dnsmasq, and removes iptables rules; disconnects all clients.

    Args:
        net_id: Unique network identifier.

    Returns:
        dict: Confirmation with stopped net_id.

    Raises:
        HTTPException 404: net_id not found.
    """
    manager.stop_network(net_id)
    return {"net_id": net_id}


@router.get(
    "/{net_id}/network",
    response_model=NetworkStatus,
    responses={
        200: {"description": "Network status retrieved successfully"},
        404: {"description": "net_id not found"},
    },
)
async def get_network(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get complete network configuration, status, DHCP info, and connected clients.

    Returns:
        NetworkStatus: Full details including SSID, channel, password, expiration time,
            DHCP configuration, and list of connected clients.

    Raises:
        HTTPException 404: net_id not found.
    """
    st = manager.get_status(net_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return st
