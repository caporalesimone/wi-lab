"""Internet connectivity (NAT) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Path

from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Internet"])


@router.post(
    "/{device_id}/internet/enable",
    responses={
        200: {
            "description": "Internet access enabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 internet enabled successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found or network not active"},
        500: {"description": "NAT configuration failed"},
    },
)
async def internet_enable(
    device_id: str = Path(..., examples=["wls16"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Enable Internet access for connected WiFi clients via NAT forwarding.

    Args:
        device_id: Device identifier (interface name).
    """
    try:
        manager.enable_internet(device_id)
        return {"detail": f"Network {device_id} internet enabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{device_id}/internet/disable",
    responses={
        200: {
            "description": "Internet access disabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 internet disabled successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found or network not active"},
    },
)
async def internet_disable(
    device_id: str = Path(..., examples=["wls16"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Disable Internet access for connected WiFi clients (remove NAT forwarding).

    Args:
        device_id: Device identifier (interface name).
    """
    try:
        manager.disable_internet(device_id)
        return {"detail": f"Network {device_id} internet disabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
