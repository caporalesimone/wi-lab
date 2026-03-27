"""WiFi network lifecycle endpoints (create, delete, query)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Body

from ...models import NetworkCreateRequest, NetworkStatus
from ...reservation import Reservation
from ...wifi.manager import NetworkManager
from ...api.auth import require_token
from ...api.dependencies import get_manager, resolve_reservation

router = APIRouter(prefix="/interface", tags=["Network"])


@router.post(
    "/{reservation_id}/network",
    responses={
        200: {
            "description": "Network created and started successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 created successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        409: {"description": "Network already active; stop it first"},
        422: {"description": "Request body validation failed"},
        500: {"description": "Failed to start network due to runtime error"},
    },
)
async def start_network(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    req: NetworkCreateRequest = Body(
        ...,
        examples=[
            {
                "ssid": "TestNetwork",
                "channel": 5,
                "password": "testpass123",
                "encryption": "wpa2",
                "band": "2.4ghz",
                "internet_enabled": True,
            },
        ],
    ),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Create and start a WiFi network in AP (access point) mode.

    Requires a valid reservation token. The network lifetime is bounded
    by the reservation expiry.

    Args:
        reservation: Active reservation (resolved from path token).
        req: Network configuration (SSID, channel, password, band, etc).

    Returns:
        dict: Simple confirmation message.
    """
    device_id = reservation.device_id
    try:
        manager.start_network(device_id, req, expires_at_timestamp=reservation.expires_at)
        return {"detail": f"Network {device_id} created successfully"}
    except ValueError as e:
        error_msg = str(e)
        error_msg_lower = error_msg.lower()
        if "already active" in error_msg_lower:
            raise HTTPException(status_code=409, detail=error_msg)
        if "unknown device_id" in error_msg_lower:
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@router.delete(
    "/{reservation_id}/network",
    responses={
        200: {
            "description": "Network stopped successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 stopped successfully"}
                }
            },
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        409: {"description": "Network already inactive"},
    },
)
async def stop_network(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Stop an active WiFi network and clean up all resources.

    Requires a valid reservation token.

    Returns:
        dict: Confirmation with stopped device_id.
    """
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    if not st.active:
        raise HTTPException(status_code=409, detail=f"Network {device_id} is already inactive")

    manager.stop_network(device_id)
    return {"detail": f"Network {device_id} stopped successfully"}


@router.get(
    "/{reservation_id}/network",
    response_model=NetworkStatus,
    responses={
        200: {"description": "Network status retrieved successfully"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
    },
)
async def get_network(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Get complete network configuration, status, DHCP info, and connected clients.

    Requires a valid reservation token.

    Returns:
        NetworkStatus: Full details including SSID, channel, password, expiration time,
            DHCP configuration, and list of connected clients.
    """
    device_id = reservation.device_id
    st = manager.get_status(device_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown device_id")
    # Always inject reservation-derived expiry so clients see countdown
    # even when the network is off.
    st.expires_at = datetime.fromtimestamp(reservation.expires_at, tz=timezone.utc).isoformat()
    st.expires_in = reservation.expires_in
    return st
