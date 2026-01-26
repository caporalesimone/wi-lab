"""TX power (transmit power) management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...models import TxPowerRequest, TxPowerInfo
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["TX Power"])


@router.get("/{net_id}/txpower", response_model=TxPowerInfo)
async def get_tx_power(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get current TX power details for an active network.

    Retrieves the current TX power level (1-4 scale) and hardware limits
    for the network's wireless interface.

    Args:
        net_id: Unique network identifier.

    Returns:
        TxPowerInfo: Current power level, hardware max (dBm), and description.

    Raises:
        HTTPException 404: net_id not found or network not active.
    """
    try:
        return manager.get_tx_power_info(net_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{net_id}/txpower", response_model=TxPowerInfo)
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
    """
    try:
        return manager.set_tx_power_level(net_id, req.level)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
