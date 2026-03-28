"""WiFi network lifecycle endpoints (create, delete, query)."""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from ...models import NetworkCreateRequest, NetworkStatus
from ...reservation import Reservation
from ...wifi.manager import NetworkManager
from ...wifi.channels import ChannelManager
from ...api.auth import require_token
from ...api.dependencies import get_manager, get_channel_manager, resolve_reservation

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
        422: {
            "description": "Validation failed (body, unsupported channel, or disabled channel)",
            "content": {
                "application/json": {
                    "examples": {
                        "body_validation": {
                            "summary": "Invalid request body",
                            "value": {"detail": "Channel 99 is not a valid WiFi channel for band 5ghz"},
                        },
                        "unsupported_channel": {
                            "summary": "Channel not supported by hardware",
                            "value": {"detail": "Channel 173 is not supported on wls16 for band 5ghz"},
                        },
                        "disabled_channel": {
                            "summary": "Channel disabled by regulatory domain",
                            "value": {"detail": "Channel 14 is disabled on wls16 for band 2.4ghz (regulatory domain restriction)"},
                        },
                    }
                }
            },
        },
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
    channel_mgr: ChannelManager = Depends(get_channel_manager),
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

    # Validate channel against real hardware capabilities
    try:
        channel_mgr.validate_channel(device_id, req.channel, req.band)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

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


# ---- Response models for available channels ----

class ChannelDetail(BaseModel):
    channel: int = Field(description="WiFi channel number")
    frequency_mhz: int = Field(description="Center frequency in MHz")
    max_power_dbm: float = Field(
        description="Maximum allowed TX power in dBm. "
        "Disabled channels report 0.0 dBm by convention."
    )
    disabled: bool = Field(description="True if the regulatory domain disables this channel")


class AvailableChannelsResponse(BaseModel):
    interface: str = Field(description="Physical interface name")
    channels_24ghz: List[ChannelDetail] = Field(description="2.4 GHz band channels")
    channels_5ghz: List[ChannelDetail] = Field(description="5 GHz band channels")


@router.get(
    "/{reservation_id}/network/available-channels",
    response_model=AvailableChannelsResponse,
    responses={
        200: {"description": "Available WiFi channels for the reserved device"},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
        500: {"description": "Failed to query interface capabilities"},
    },
)
async def get_available_channels(
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
):
    """
    List all WiFi channels supported by the reserved device, split by band.

    Results are cached in memory after the first query per interface.
    Disabled channels are included with ``max_power_dbm = 0.0`` and
    ``disabled = true`` so clients can display them as unavailable.
    """
    device_id = reservation.device_id
    try:
        info = channel_mgr.get_channels(device_id)
    except (ValueError, Exception) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query channels for {device_id}: {exc}",
        )

    return AvailableChannelsResponse(
        interface=info.interface,
        channels_24ghz=[
            ChannelDetail(
                channel=ch.channel,
                frequency_mhz=ch.frequency_mhz,
                max_power_dbm=ch.max_power_dbm,
                disabled=ch.disabled,
            )
            for ch in info.channels_24ghz
        ],
        channels_5ghz=[
            ChannelDetail(
                channel=ch.channel,
                frequency_mhz=ch.frequency_mhz,
                max_power_dbm=ch.max_power_dbm,
                disabled=ch.disabled,
            )
            for ch in info.channels_5ghz
        ],
    )
