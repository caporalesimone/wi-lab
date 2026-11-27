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
from .recovery_responses import (
    DEVICE_BUSY_RESPONSE,
    ACCESS_POINT_NOT_ACTIVE_RESPONSE,
    require_stop_complete,
)

router = APIRouter(
    prefix="/access-point", tags=["Access point"],
    responses={503: {"description": "Adapter busy (1006): repeat after Retry-After"}},
)


@router.post(
    "/{reservation_id}/internet/enable",
    summary="Enable Internet access on the access point",
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: ACCESS_POINT_NOT_ACTIVE_RESPONSE,
        200: {
            "description": "Internet access enabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Internet enabled on the access point on wls16"}
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
        require_stop_complete(manager, device_id)
        try:
            manager.enable_internet(device_id)
            return {"detail": f"Internet enabled on the access point on {device_id}"}
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            # The reservation is valid: a 404 would tell the client it ended (REV-11).
            # Reaching this is a server-side inconsistency.
            raise HTTPException(status_code=500, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{reservation_id}/internet/disable",
    summary="Disable Internet access on the access point",
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: ACCESS_POINT_NOT_ACTIVE_RESPONSE,
        200: {
            "description": "Internet access disabled successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Internet disabled on the access point on wls16"}
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
        require_stop_complete(manager, device_id)
        try:
            manager.disable_internet(device_id)
            return {"detail": f"Internet disabled on the access point on {device_id}"}
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            # The reservation is valid: a 404 would tell the client it ended (REV-11).
            # Reaching this is a server-side inconsistency.
            raise HTTPException(status_code=500, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
