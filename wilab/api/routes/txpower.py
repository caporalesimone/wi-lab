"""TX power (transmit power) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...api.auth import require_token
from ...api.dependencies import (
    ReservationManagerDep,
    get_manager,
    hold_reservation,
    resolve_reservation,
)
from ...models import TxPowerInfo, TxPowerRequest
from ...reservation import Reservation
from ...wifi.manager import NetworkManager, TxPowerMismatchError
from .recovery_responses import DEVICE_BUSY_RESPONSE

router = APIRouter(
    prefix="/interface", tags=["TX Power"],
    responses={503: {"description": "Device cleanup failed; retry after resolving the error"}},
)
VALID_TX_POWER_LEVELS = (1, 2, 3, 4)
VALID_TX_POWER_LEVELS_TEXT = ", ".join(str(level) for level in VALID_TX_POWER_LEVELS)


@router.get(
    "/{reservation_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        200: {"description": "TX power info retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
    },
)
def get_tx_power(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Get current TX power details for an active network.

    Requires a valid reservation token.
    """
    with hold_reservation(reservation_mgr, reservation):
        try:
            return manager.get_tx_power_info(reservation.device_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{reservation_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        200: {"description": "TX power level set successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        422: {
            "description": "Unprocessable Entity (requested power out of range or requested TX power not applied by hardware)"
        },
    },
)
def set_tx_power(
    req: TxPowerRequest,
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Set TX power level (1-4) for an active network.

    Requires a valid reservation token.
    """
    if req.level not in VALID_TX_POWER_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Requested power out of range. Valid values are {VALID_TX_POWER_LEVELS_TEXT}.",
        )

    with hold_reservation(reservation_mgr, reservation):
        try:
            return manager.set_tx_power_level(reservation.device_id, req.level)
        except TxPowerMismatchError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
