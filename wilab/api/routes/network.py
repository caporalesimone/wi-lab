"""WiFi network lifecycle endpoints (create, delete, query)."""

from fastapi import APIRouter, Depends, HTTPException, Body, Path

from ...models import NetworkCreateRequest, NetworkStatus
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Network"])


@router.post(
    "/{device_id}/network",
    responses={
        200: {
            "description": "Network created and started successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 created successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found in configuration"},
        409: {"description": "Network already active; stop it first"},
        422: {"description": "Request body validation failed"},
        500: {"description": "Failed to start network due to runtime error"},
    },
)
async def start_network(
    device_id: str = Path(..., examples=["wls16"]),
    req: NetworkCreateRequest = Body(
        ...,
        examples={
            "default": {
                "summary": "Typical network configuration",
                "description": "2.4GHz WPA2 network with 1-hour timeout and Internet enabled.",
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
        device_id: Device identifier (interface name from config).
        req: Network configuration (SSID, channel, password, band, timeout, etc).

    Returns:
        dict: Simple confirmation message. Use GET /interface/{device_id}/network
            to retrieve full network details.
    """
    try:
        manager.start_network(device_id, req)
        return {"detail": f"Network {device_id} created successfully"}
    except ValueError as e:
        error_msg = str(e)
        error_msg_lower = error_msg.lower()
        if "already active" in error_msg_lower:
            raise HTTPException(status_code=409, detail=error_msg)
        if "unknown device_id" in error_msg_lower:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.delete(
    "/{device_id}/network",
    responses={
        200: {
            "description": "Network stopped successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 stopped successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found"},
        409: {"description": "Network already inactive"},
    },
)
async def stop_network(
    device_id: str = Path(..., examples=["wls16"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Stop an active WiFi network and clean up all resources.

    Stops hostapd, dnsmasq, and removes iptables rules; disconnects all clients.

    Args:
        device_id: Device identifier (interface name).

    Returns:
        dict: Confirmation with stopped device_id.
    """
    st = manager.get_status(device_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    if not st.active:
        raise HTTPException(status_code=409, detail=f"Network {device_id} is already inactive")

    manager.stop_network(device_id)
    return {"detail": f"Network {device_id} stopped successfully"}


@router.get(
    "/{device_id}/network",
    response_model=NetworkStatus,
    responses={
        200: {"description": "Network status retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found"},
    },
)
async def get_network(
    device_id: str = Path(..., examples=["wls16"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get complete network configuration, status, DHCP info, and connected clients.

    Returns:
        NetworkStatus: Full details including SSID, channel, password, expiration time,
            DHCP configuration, and list of connected clients.
    """
    st = manager.get_status(device_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    return st
