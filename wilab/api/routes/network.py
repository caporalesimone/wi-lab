"""WiFi network lifecycle endpoints (create, delete, query)."""

from math import ceil
from time import monotonic

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from ...api.auth import require_token
from ...api.dependencies import (
    ReservationManagerDep,
    get_channel_manager,
    get_manager,
    hold_reservation,
    resolve_reservation,
)
from ...models import NetworkCreateRequest, NetworkStatus
from ...reservation import Reservation
from ...timestamps import format_utc_timestamp
from ...wifi.channels import ChannelManager
from ...wifi.manager import NetworkManager, StartupFailure
from .recovery_responses import (
    RETRY_AFTER_HEADER,
    RecoveryCode,
    recovery_error,
    recovery_example,
)

CREATE_RETRY_DELAYS = (5, 10)

router = APIRouter(
    prefix="/interface", tags=["Network"],
    responses={503: {"description": "Device cleanup failed; retry after resolving the error"}},
)


@router.post(
    "/{reservation_id}/network",
    summary="Create a network on a reserved adapter",
    responses={
        200: {
            "description": "Network created and started successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Network wls16 created successfully"}
                }
            },
        },
        401: {"description": "Unauthorized", "content": {"application/json": {
            "example": {"detail": "Invalid token"},
        }}},
        404: {"description": "Reservation not found, expired or invalidated", "content": {
            "application/json": {"example": {"detail": "Reservation not found or expired"}},
        }},
        409: {
            "description": "Network already active, watchdog restoration, or radio cooldown (1001). Retry only for 1001.",
            "headers": RETRY_AFTER_HEADER,
            "content": {"application/json": {"examples": {
                "active_network": {"value": {"detail": "Network is already active"}},
                "restoration_in_progress": {"value": {"detail": "Network restoration is in progress"}},
                "retry_later": recovery_example(RecoveryCode.RETRY_LATER),
            }}},
        },
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
        500: {
            "description": (
                "**Generic `500 / 500`:** `detail.message` explains the error. Keep the reservation ID; "
                "release it if no longer needed. Do not retry creation automatically.\n\n"
                "**`500 / 1003`:** the adapter is quarantined and the reservation is "
                "invalidated. Discard the ID; do not retry creation or release it. "
                "Request a new reservation if needed.\n\n"
                "Neither response includes `Retry-After`."
            ),
            "content": {"application/json": {
                "schema": {
                    "type": "object",
                    "required": ["detail"],
                    "properties": {"detail": {"oneOf": [
                        {
                            "type": "object", "title": "Startup error; reservation retained",
                            "required": ["code", "reason", "message"],
                            "properties": {
                                "code": {"type": "integer", "enum": [500]},
                                "reason": {"type": "string", "enum": ["internal_server_error"]},
                                "message": {"type": "string"},
                            },
                        },
                        {
                            "type": "object",
                            "title": "Adapter quarantined; reservation invalidated",
                            "required": ["code", "reason", "reservation_invalidated"],
                            "properties": {
                                "code": {"type": "integer", "enum": [RecoveryCode.DEVICE_UNAVAILABLE.value]},
                                "reason": {"type": "string", "enum": ["device_unavailable"]},
                                "reservation_invalidated": {"type": "boolean", "enum": [True]},
                            },
                        },
                    ]}},
                },
                "examples": {
                    "startup_failure": {
                        "summary": "500 - Startup failed; reservation still valid",
                        "value": {"detail": "Failed to start AP: hostapd exited with code 1"},
                    },
                    "device_unavailable": {
                        "summary": "500 / 1003 - Adapter quarantined; discard the reservation ID",
                        **recovery_example(RecoveryCode.DEVICE_UNAVAILABLE, invalidated=True),
                    },
                },
            }},
        },
        503: {
            "description": "Device cleanup failed while resolving an expired reservation.",
            "content": {"application/json": {
                "example": {"detail": "Failed to clean up device wlan0"},
            }},
        },
    },
)
def start_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    req: NetworkCreateRequest = Body(
        ...,
        openapi_examples={
            "wpa2_network": {"summary": "2.4 GHz WPA2 network", "value": {
                "ssid": "TestNetwork",
                "channel": 5,
                "password": "testpass123",
                "encryption": "wpa2",
                "band": "2.4ghz",
                "internet_enabled": True,
                "captive_portal": False,
                "tx_power_level": 4,
            }},
            "captive_portal_network": {
                "summary": "Network behind a simulated captive portal",
                "description": "Clients are redirected to the portal page until they press Sign in. "
                "Only the client that signs in is released; with internet_enabled it then reaches "
                "the Internet.",
                "value": {
                    "ssid": "CaptiveTest",
                    "channel": 6,
                    "password": "testpass123",
                    "encryption": "wpa2",
                    "band": "2.4ghz",
                    "internet_enabled": True,
                    "captive_portal": True,
                    "tx_power_level": 4,
                },
            },
        },
    ),
    manager: NetworkManager = Depends(get_manager),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
):
    """
    Create and start a WiFi network in AP (access point) mode.

    Requires a valid reservation token. The network lifetime is bounded
    by the reservation expiry.

    If starting the AP fails because of the radio (hostapd crash, beacon setup
    failure, radio or readiness timeout), the server starts it again in the same
    request after successful cleanup, on either band: up to 3 starts, 1 s apart,
    within 15 s. A normal start takes about 0.5 s; with retries the response can
    take up to about 15 s outside DFS channels. Clients do not need to resubmit
    the request to trigger these retries.

    After the first and second requests whose internal starts all failed, **409 / 1001**
    retains the reservation. Retry the same POST and ID only after the
    `Retry-After` header (5 and 10 seconds, respectively). Calls during cooldown
    do not consume a startup attempt. Reservation expiry is not extended.

    A third classified failure, or unsafe cleanup during startup, returns **500 / 1003** and
    invalidates the ID. Do not retry creation or release that ID. A new
    reservation request can return **503 / 1002** while recovery is running.
    No USB reset runs in the creation request.
    A network being restored by the watchdog returns an ordinary HTTP 409.

    **Captive portal** (optional `captive_portal`, default `false`; omitted means
    no portal): each client that joins is held behind a simple portal page on the
    gateway (`http://<gateway>/`, reported as `captive_portal_url`). Until it
    presses **Sign in**, its DNS queries resolve to the gateway, its HTTP requests
    are redirected to the portal and other forwarded traffic, including HTTPS, is
    rejected. Sign-in releases only that client (MAC and IP); there is no API to
    sign a client in. Afterwards the network's `internet_enabled` setting applies.
    Sign-ins are cleared when the AP stops or is restored by the watchdog. A
    portal startup failure is rolled back like any other startup error (`500`).
    """
    if manager.watchdog.state(reservation) in ("restoring_ap", "restoring_dhcp"):
        raise HTTPException(status_code=409, detail="Network restoration is in progress")
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        remaining = ceil(reservation.retry_at - monotonic())
        if remaining > 0:
            raise recovery_error(RecoveryCode.RETRY_LATER, retry_after=remaining)
        try:
            channel_mgr.validate_channel(device_id, req.channel, req.band)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        try:
            manager.start_network(
                device_id, req, expires_at_timestamp=reservation.expires_at,
                allow_internal_retry=reservation.radio_failures == 0,
            )
            reservation.radio_failures = 0
            reservation.retry_at = 0
            return {"detail": f"Network {device_id} created successfully"}
        except StartupFailure as e:
            if not (e.radio or e.cleanup_failed):
                raise HTTPException(status_code=500, detail=str(e)) from e
            reservation.radio_failures += 1
            if not e.cleanup_failed and reservation.radio_failures <= len(CREATE_RETRY_DELAYS):
                delay = CREATE_RETRY_DELAYS[reservation.radio_failures - 1]
                reservation.retry_at = monotonic() + delay
                raise recovery_error(RecoveryCode.RETRY_LATER, retry_after=delay) from e
            manager.quarantine_radio(
                reservation_mgr, reservation, radio_fault=e.radio, band=req.band, channel=req.channel,
            )
            raise recovery_error(RecoveryCode.DEVICE_UNAVAILABLE, invalidated=True) from e
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
def stop_network(
    reservation_mgr: ReservationManagerDep,
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
    with hold_reservation(reservation_mgr, reservation):
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
        200: {
            "description": "Network status, or a watchdog snapshot while restoration is in progress.",
            "content": {"application/json": {"examples": {
                "restoring_ap": {"value": {
                    "interface": "wlan0", "active": False, "runtime_state": "restoring_ap",
                    "expires_in": 54,
                }},
                "restoring_dhcp": {"value": {
                    "interface": "wlan0", "active": True, "runtime_state": "restoring_dhcp",
                    "expires_in": 53,
                }},
                "dhcp_failed": {"value": {
                    "interface": "wlan0", "active": True, "runtime_state": "dhcp_failed",
                    "expires_in": 51,
                }},
                "captive_portal": {
                    "summary": "Active network with a captive portal",
                    "value": {
                        "interface": "wlan0", "active": True, "ssid": "CaptiveTest", "channel": 6,
                        "band": "2.4ghz", "encryption": "wpa2", "subnet": "192.168.120.0/24",
                        "internet_enabled": True, "captive_portal": True,
                        "captive_portal_url": "http://192.168.120.1/", "expires_in": 3540,
                        "clients_connected": 2,
                        "clients": [
                            {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.23", "captive_authorized": True},
                            {"mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.120.57", "captive_authorized": False},
                        ],
                    },
                },
            }}},
        },
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "Reservation not found or expired"},
    },
)
def get_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    manager: NetworkManager = Depends(get_manager),
):
    """
    Get complete network configuration, status, DHCP info, and connected clients.

    Requires a valid reservation token.
    During runtime restoration, returns the current `runtime_state` without
    waiting for the radio. A quarantined network's former ID returns 404.

    Returns:
        NetworkStatus: Full details including SSID, channel, password, expiration time,
            DHCP configuration, and list of connected clients.
    """
    runtime_state = manager.watchdog.state(reservation)
    if runtime_state in ("restoring_ap", "restoring_dhcp"):
        return NetworkStatus(
            interface=reservation.device_id, active=runtime_state == "restoring_dhcp",
            runtime_state=runtime_state, expires_in=reservation.expires_in,
            expires_at=format_utc_timestamp(reservation.expires_at),
        )
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        st = manager.get_status(device_id)
        if not st:
            raise HTTPException(status_code=404, detail="Unknown device_id")
        st.expires_at = format_utc_timestamp(reservation.expires_at)
        st.expires_in = reservation.expires_in
        return st.model_copy(update={"runtime_state": manager.watchdog.state(reservation)})


# ---- Response models for available channels ----

class ChannelDetail(BaseModel):
    channel: int = Field(description="WiFi channel number")
    frequency_mhz: int = Field(description="Center frequency in MHz")
    max_power_dbm: float = Field(
        description="Maximum allowed TX power in dBm. "
        "Disabled channels report 0.0 dBm by convention."
    )
    disabled: bool = Field(description="True if regulatory restrictions or Wi-Lab's DFS policy block this channel")


class AvailableChannelsResponse(BaseModel):
    interface: str = Field(description="Physical interface name")
    channels_24ghz: list[ChannelDetail] = Field(description="2.4 GHz band channels")
    channels_5ghz: list[ChannelDetail] = Field(description="5 GHz band channels")


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
def get_available_channels(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
):
    """
    List all WiFi channels supported by the reserved device, split by band.

    Results are cached in memory after the first query per interface.
    Disabled channels are included with ``max_power_dbm = 0.0`` and
    ``disabled = true`` so clients can display them as unavailable. This includes
    channels flagged for radar detection when ``allow_dfs_channels`` is false.
    """
    with hold_reservation(reservation_mgr, reservation):
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
