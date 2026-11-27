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
from ...wifi.manager import NetworkManager, NetworkNotActive
from ...wifi.txpower import TxPowerMismatchError
from .recovery_responses import (
    DEVICE_BUSY_RESPONSE,
    NETWORK_NOT_ACTIVE_RESPONSE,
    require_stop_complete,
)

router = APIRouter(
    prefix="/reservations", tags=["TX Power"],
    responses={503: {"description": "Adapter busy (1006): repeat after Retry-After"}},
)
VALID_TX_POWER_LEVELS = (1, 2, 3, 4)
VALID_TX_POWER_LEVELS_TEXT = ", ".join(str(level) for level in VALID_TX_POWER_LEVELS)

_TX_POWER_EXAMPLE = {
    "interface": "wlx7419f8176286",
    "max_dbm": 20.0,
    "levels_dbm": {"1": 5.0, "2": 10.0, "3": 15.0, "4": 20.0},
    "tx_power": {"requested_level": 2, "reported_level": 2, "reported_dbm": 10.0},
}


def _validation_example(message: str) -> dict:
    return {"value": {"detail": {"code": 422, "reason": "validation_error", "message": message}}}


@router.get(
    "/{reservation_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: NETWORK_NOT_ACTIVE_RESPONSE,
        200: {
            "description": "TX power info retrieved successfully",
            "content": {"application/json": {"example": _TX_POWER_EXAMPLE}},
        },
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
        require_stop_complete(manager, reservation.device_id)
        try:
            return manager.get_tx_power_info(reservation.device_id)
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            # The reservation is valid: a 404 would tell the client it ended (REV-11).
            # Reaching this is a server-side inconsistency.
            raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/{reservation_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        409: NETWORK_NOT_ACTIVE_RESPONSE,
        200: {
            "description": "TX power level set successfully",
            "content": {"application/json": {"example": _TX_POWER_EXAMPLE}},
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        422: {
            "description": "Unprocessable Entity (requested power out of range or requested TX power not applied by hardware)",
            "content": {"application/json": {"examples": {
                "out_of_range": {
                    "summary": "Requested level is outside 1-4",
                    **_validation_example(
                        f"Requested power out of range. Valid values are {VALID_TX_POWER_LEVELS_TEXT}.",
                    ),
                },
                "hardware_mismatch": {
                    "summary": "Hardware does not apply requested TX power",
                    **_validation_example("Interface does not support dynamic power change."),
                },
            }}},
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
    if req.tx_power_level not in VALID_TX_POWER_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Requested power out of range. Valid values are {VALID_TX_POWER_LEVELS_TEXT}.",
        )

    with hold_reservation(reservation_mgr, reservation):
        require_stop_complete(manager, reservation.device_id)
        try:
            return manager.set_tx_power_level(reservation.device_id, req.tx_power_level)
        except TxPowerMismatchError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except NetworkNotActive:
            raise  # 409 / 1007 (API-2)
        except ValueError as e:
            # The driver refused the setting (e.g. not supported): not a missing
            # reservation, which is the only meaning of 404.
            raise HTTPException(status_code=422, detail=str(e))
