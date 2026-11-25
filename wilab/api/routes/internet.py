"""Internet connectivity (NAT) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...api.auth import require_token
from ...api.dependencies import (
    ReservationManagerDep,
    get_manager,
    hold_reservation,
    resolve_reservation,
)
from ...reservation import Reservation
from ...wifi.manager import NetworkManager, NetworkNotActive
from .recovery_responses import DEVICE_BUSY_RESPONSE, NETWORK_NOT_ACTIVE_RESPONSE

router = APIRouter(
    prefix="/reservations", tags=["Internet"],
    responses={503: {"description": "Device cleanup failed; retry after resolving the error"}},
)


@router.post(
    "/{reservation_id}/internet/enable",
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: NETWORK_NOT_ACTIVE_RESPONSE,
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
def internet_enable(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Enable Internet access for connected WiFi clients via NAT forwarding.

    Requires a valid reservation token.
    """
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        try:
            manager.enable_internet(device_id)
            return {"detail": f"Network {device_id} internet enabled successfully"}
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{reservation_id}/internet/disable",
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: NETWORK_NOT_ACTIVE_RESPONSE,
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
        500: {"description": "Internet access could not be disabled"},
    },
)
def internet_disable(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Disable Internet access for connected WiFi clients, including existing flows.

    Requires a valid reservation token.
    """
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        try:
            manager.disable_internet(device_id)
            return {"detail": f"Network {device_id} internet disabled successfully"}
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
