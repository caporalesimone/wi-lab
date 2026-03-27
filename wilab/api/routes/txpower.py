"""TX power (transmit power) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Path

from ...models import TxPowerRequest, TxPowerInfo
from ...wifi.manager import NetworkManager, TxPowerMismatchError
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["TX Power"])
VALID_TX_POWER_LEVELS = (1, 2, 3, 4)
VALID_TX_POWER_LEVELS_TEXT = ", ".join(str(level) for level in VALID_TX_POWER_LEVELS)


@router.get(
    "/{device_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        200: {"description": "TX power info retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found or network not active"},
    },
)
async def get_tx_power(
    device_id: str = Path(..., examples=["wls16"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get current TX power details for an active network.

    Args:
        device_id: Device identifier (interface name).
    """
    try:
        return manager.get_tx_power_info(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{device_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        200: {"description": "TX power level set successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "device_id not found or network not active"},
        422: {
            "description": "Unprocessable Entity (requested power out of range or requested TX power not applied by hardware)"
        },
    },
)
async def set_tx_power(
    device_id: str,
    req: TxPowerRequest,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Set TX power level (1-4) for an active network.

    Args:
        device_id: Device identifier (interface name).
        req: Request with 'level' field (integer 1-4).
    """
    if req.level not in VALID_TX_POWER_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Requested power out of range. Valid values are {VALID_TX_POWER_LEVELS_TEXT}.",
        )

    try:
        return manager.set_tx_power_level(device_id, req.level)
    except TxPowerMismatchError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
