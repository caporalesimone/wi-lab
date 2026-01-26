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
    Get complete network configuration and live status.

    Returns:
        NetworkStatus: Full details (SSID, channel, password, expiration time in both
            absolute format 'yyyy-mm-dd HH:MM:SS' and remaining seconds), active state.

    Raises:
        HTTPException 404: net_id not found.
    """
    st = manager.get_status(net_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return st


@router.get(
    "/{net_id}/status",
    responses={
        200: {"description": "Network minimal status retrieved successfully"},
        404: {"description": "net_id not found"},
    },
)
async def get_status(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get minimal network status (summary flag only).

    Returns:
        dict: Lightweight status object with net_id, interface name, active flag.

    Raises:
        HTTPException 404: net_id not found.
    """
    st = manager.get_status(net_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return {"net_id": st.net_id, "interface": st.interface, "active": st.active}


@router.get(
    "/{net_id}/summary",
    responses={
        200: {"description": "Network summary retrieved successfully"},
        404: {"description": "net_id not found"},
    },
)
async def get_summary(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get detailed network summary including DHCP info and connected clients.

    Returns:
        dict: Network summary with SSID, interface, DHCP pool, gateway, connected clients.

    Raises:
        HTTPException 404: net_id not found.
    """
    summary = manager.get_summary(net_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Unknown net_id")
    return summary
