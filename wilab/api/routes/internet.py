"""Internet connectivity (NAT) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Internet"])


@router.post("/{net_id}/internet/enable")
async def internet_enable(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Enable Internet access for connected WiFi clients via NAT forwarding.

    Configures iptables MASQUERADE rules to forward traffic from the WiFi
    network to the upstream interface, allowing clients to reach external networks.

    Args:
        net_id: Unique network identifier.

    Returns:
        dict: Confirmation with net_id and internet_enabled=True.

    Raises:
        HTTPException 404: net_id not found or network not active.
        HTTPException 500: NAT configuration failed.
    """
    try:
        manager.enable_internet(net_id)
        return {"net_id": net_id, "internet_enabled": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{net_id}/internet/disable")
async def internet_disable(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Disable Internet access for connected WiFi clients (remove NAT forwarding).

    Removes iptables MASQUERADE rules; clients remain connected to WiFi but
    cannot reach external networks; only communication with the AP is allowed.

    Args:
        net_id: Unique network identifier.

    Returns:
        dict: Confirmation with net_id and internet_enabled=False.

    Raises:
        HTTPException 404: net_id not found or network not active.
    """
    try:
        manager.disable_internet(net_id)
        return {"net_id": net_id, "internet_enabled": False}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
