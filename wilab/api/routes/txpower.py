"""TX power (transmit power) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Body, Path

from ...models import TxPowerRequest, TxPowerInfo
from ...wifi.manager import NetworkManager, TxPowerMismatchError
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["TX Power"])
VALID_TX_POWER_LEVELS = (1, 2, 3, 4)
VALID_TX_POWER_LEVELS_TEXT = ", ".join(str(level) for level in VALID_TX_POWER_LEVELS)


@router.get(
    "/{net_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        200: {"description": "TX power info retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "net_id not found or network not active"},
    },
)
async def get_tx_power(
    net_id: str = Path(..., examples=["ap-01"]),
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get current TX power details for an active network.

    Retrieves requested and reported TX power values for the network interface.

    Args:
        net_id: Unique network identifier.

    Returns:
        TxPowerInfo: max_dbm, levels_dbm, and nested tx_power requested/reported values.

    Raises:
        HTTPException 404: net_id not found or network not active.
    """
    try:
        return manager.get_tx_power_info(net_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/{net_id}/txpower",
    response_model=TxPowerInfo,
    responses={
        200: {"description": "TX power level set successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "net_id not found or network not active"},
        422: {
            "description": "Unprocessable Entity (requested power out of range or requested TX power not applied by hardware)"
        },
    },
)
async def set_tx_power(
    net_id: str,
    req: TxPowerRequest,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Set TX power level (1-4) for an active network.

    Scales level 1-4 to hardware maximum dBm capability and applies via iw command.
    - Level 1: ~25% of hardware max
    - Level 2: ~50% of hardware max
    - Level 3: ~75% of hardware max
    - Level 4: 100% of hardware max

    Args:
        net_id: Unique network identifier.
        req: Request with 'level' field (integer 1-4).

    Returns:
        TxPowerInfo: Updated power level and hardware limits.

    Raises:
        HTTPException 404: net_id not found or network not active.
        HTTPException 422: requested power is out of range or cannot be applied by hardware.
    """
    if req.level not in VALID_TX_POWER_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"Requested power out of range. Valid values are {VALID_TX_POWER_LEVELS_TEXT}.",
        )

    try:
        return manager.set_tx_power_level(net_id, req.level)
    except TxPowerMismatchError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
