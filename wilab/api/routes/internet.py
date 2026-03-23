"""Internet connectivity (NAT) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Path

from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Internet"])


@router.post(
    "/{net_id}/internet/enable",
    responses={
        200: {
            "description": "Internet access enabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network ap-01 internet enabled successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "net_id not found or network not active"},
        500: {"description": "NAT configuration failed"},
    },
)
async def internet_enable(
    net_id: str = Path(..., examples=["ap-01"]),
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
        dict: Confirmation message with enabled status.

    Raises:
        HTTPException 404: net_id not found or network not active.
        HTTPException 500: NAT configuration failed.
    """
    try:
        manager.enable_internet(net_id)
        return {"detail": f"Network {net_id} internet enabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{net_id}/internet/disable",
    responses={
        200: {
            "description": "Internet access disabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network ap-01 internet disabled successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "net_id not found or network not active"},
    },
)
async def internet_disable(
    net_id: str = Path(..., examples=["ap-01"]),
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
        dict: Confirmation message with disabled status.

    Raises:
        HTTPException 404: net_id not found or network not active.
    """
    try:
        manager.disable_internet(net_id)
        return {"detail": f"Network {net_id} internet disabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
