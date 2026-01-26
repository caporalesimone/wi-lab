"""WiFi client management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from ...models import ClientsResponse
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager

router = APIRouter(prefix="/interface", tags=["Clients"])


@router.get(
    "/{net_id}/clients",
    response_model=ClientsResponse,
    responses={
        200: {"description": "Client list retrieved successfully"},
        404: {"description": "net_id not found"},
    },
)
async def list_clients(
    net_id: str,
    manager: NetworkManager = Depends(get_manager),
    _auth: bool = Depends(require_token),
):
    """
    Get list of WiFi clients connected to a network.

    Queries hostapd and dnsmasq for active client sessions.

    Args:
        net_id: Unique network identifier.

    Returns:
        ClientsResponse: Object with net_id and array of clients (MAC, IP address, hostname).

    Raises:
        HTTPException 404: net_id not found.
    """
    clients = manager.list_clients(net_id)
    return {"net_id": net_id, "clients": clients}
