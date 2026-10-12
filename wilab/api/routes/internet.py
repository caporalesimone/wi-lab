"""Internet connectivity (NAT) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...reservation import Reservation
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager, resolve_reservation

router = APIRouter(prefix="/interface", tags=["Internet"])


@router.post(
    "/{reservation_id}/internet/enable",
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
        404: {"description": "Reservation not found or expired"},
        500: {"description": "NAT configuration failed"},
    },
)
async def internet_enable(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Enable Internet access for connected WiFi clients via NAT forwarding.

    Requires a valid reservation token.
    """
    device_id = reservation.device_id
    try:
        manager.enable_internet(device_id)
        return {"detail": f"Network {device_id} internet enabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{reservation_id}/internet/disable",
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
        404: {"description": "Reservation not found or expired"},
        500: {
            "description": "The block rules could not be applied: Internet access was not disabled",
            "content": {
                "application/json": {
                    "example": {"detail": "Cannot disable Internet: Cannot block Internet: iptables failed"}
                }
            },
        },
    },
)
async def internet_disable(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Disable Internet access for the WiFi clients of this network.

    The cut is immediate and also applies to connections already open (a download in
    progress fails instead of running to the end). Only this network is affected: the
    clients of other networks keep their access and their connections.

    Requires a valid reservation token.
    """
    device_id = reservation.device_id
    try:
        manager.disable_internet(device_id)
        return {"detail": f"Network {device_id} internet disabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
