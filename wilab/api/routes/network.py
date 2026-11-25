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
from ...models import NetworkCreateBody, NetworkResponse, ReservationInfo
from ...reservation import Reservation
from ...timestamps import format_utc_timestamp
from ...wifi.channels import ChannelManager
from ...wifi.manager import NetworkManager, StartupFailure
from .recovery_responses import (
    DEVICE_BUSY_RESPONSE,
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


def _error(code: int, reason: str, message: str) -> dict:
    """An error `detail` object as the API returns it."""
    return {"code": code, "reason": reason, "message": message}


@router.post(
    "/{reservation_id}/network",
    summary="Create a network on a reserved adapter",
    responses={
        200: {
            "description": "Network created and started successfully",
            "content": {"application/json": {
                "example": {"detail": "Network wlx7419f8176286 created successfully"},
            }},
        },
        401: {"description": "Unauthorized", "content": {"application/json": {
            "example": {"detail": _error(401, "unauthorized", "Invalid token")},
        }}},
        404: {"description": "Reservation not found, expired or invalidated", "content": {
            "application/json": {"example": {"detail": _error(404, "not_found", "Reservation not found or expired")}},
        }},
        409: {
            "description": "Network already active, watchdog restoration, or radio cooldown (1001). Retry only for 1001.",
            "headers": RETRY_AFTER_HEADER,
            "content": {"application/json": {"examples": {
                "active_network": {"value": {"detail": _error(409, "conflict", "Network is already active")}},
                "restoration_in_progress": {
                    "value": {"detail": _error(409, "conflict", "Network restoration is in progress")},
                },
                "retry_later": recovery_example(RecoveryCode.RETRY_LATER),
            }}},
        },
        422: {
            "description": (
                "Validation failed: body, unsupported or disabled channel, `encryption: wpa` "
                "(no longer accepted), or an encryption, channel width or Wi-Fi generation the "
                "antenna does not support"
            ),
            "content": {"application/json": {"examples": {
                "wpa_removed": {
                    "summary": "encryption wpa is no longer accepted",
                    "value": {"detail": _error(
                        422, "validation_error",
                        "Value error, wifi.security.encryption: 'wpa' is no longer accepted: use "
                        "'wpa2' (what 'wpa' used to create) or 'wpa1' for legacy WPA/TKIP",
                    )},
                },
                "wpa1_unsupported": {
                    "summary": "wpa1 on an antenna without TKIP",
                    "value": {"detail": _error(
                        422, "validation_error", "wpa1 is not supported on this antenna",
                    )},
                },
                "width_unavailable": {
                    "summary": "Channel cannot be used at the requested width",
                    "value": {"detail": _error(
                        422, "validation_error",
                        "80 MHz on channel 165 is not available: Channel 169 is disabled on wlan0 "
                        "for band 5ghz (regulatory domain restriction)",
                    )},
                },
                "generation_unsupported": {
                    "summary": "Wi-Fi generation not supported by the antenna",
                    "value": {"detail": _error(
                        422, "validation_error",
                        "wifi_generation 6 is not supported on this antenna for band 5ghz",
                    )},
                },
                "body_validation": {
                    "summary": "Invalid request body",
                    "value": {"detail": _error(
                        422, "validation_error",
                        "Value error, Channel 99 is not a valid WiFi channel for band 5ghz",
                    )},
                },
                "unsupported_channel": {
                    "summary": "Channel not supported by hardware",
                    "value": {"detail": _error(
                        422, "validation_error", "Channel 173 is not supported on wlan0 for band 5ghz",
                    )},
                },
                "disabled_channel": {
                    "summary": "Channel disabled by regulatory domain",
                    "value": {"detail": _error(
                        422, "validation_error",
                        "Channel 14 is disabled on wlan0 for band 2.4ghz (regulatory domain restriction)",
                    )},
                },
            }}},
        },
        500: {
            "description": (
                "**Generic `500 / 500`:** `detail.message` explains the error. Keep the reservation ID; "
                "release it if no longer needed. Do not retry creation automatically. "
                "No `Retry-After`."
            ),
            "content": {"application/json": {"examples": {
                "startup_failure": {
                    "summary": "500 - Startup failed; reservation still valid",
                    "value": {"detail": _error(
                        500, "internal_server_error", "Failed to start AP: hostapd exited with code 1",
                    )},
                },
            }}},
        },
        503: {
            "description": (
                "**`503 / 1003`:** the adapter is quarantined and the reservation is invalidated "
                "(`reservation_invalidated: true`). Discard the ID; do not retry creation or release "
                "it. Request a new reservation if needed. No `Retry-After`.\n\n"
                "**`503 / 1004`:** a device cleanup failed while resolving an expired reservation."
            ),
            "content": {"application/json": {"examples": {
                "device_unavailable": {
                    "summary": "503 / 1003 - Adapter quarantined; discard the reservation ID",
                    **recovery_example(RecoveryCode.DEVICE_UNAVAILABLE, invalidated=True),
                },
                "cleanup_failed": {
                    "summary": "503 / 1004 - Cleanup failed",
                    "value": {"detail": _error(1004, "cleanup_failed", "Failed to clean up device wlan0")},
                },
            }}},
        },
    },
)
def start_network(
    reservation_mgr: ReservationManagerDep,
    _auth: bool = Depends(require_token),
    reservation: Reservation = Depends(resolve_reservation),
    body: NetworkCreateBody = Body(
        ...,
        openapi_examples={
            "wpa2_network": {
                "summary": "2.4 GHz WPA2 network, every optional field at its default",
                "description": "Required: radio.band, radio.channel, radio.tx_power_level, "
                "wifi.ssid, wifi.security.encryption, and wifi.security.password unless the "
                "encryption is open. Optional, shown with their defaults: radio.channel_width, "
                "radio.wifi_generation, wifi.hidden, internet.enabled (default from the server "
                "configuration), captive_portal.enabled.",
                "value": {
                "radio": {
                    "band": "2.4ghz", "channel": 5, "channel_width": 20,
                    "wifi_generation": 4, "tx_power_level": 4,
                },
                "wifi": {
                    "ssid": "TestNetwork", "hidden": False,
                    "security": {"encryption": "wpa2", "password": "testpass123"},
                },
                "internet": {"enabled": True},
                "captive_portal": {"enabled": False},
            },
            },
            "wifi5_80mhz": {
                "summary": "5 GHz Wi-Fi 5 network at 80 MHz",
                "description": "Channels 36-48 as one 80 MHz channel, 802.11ac. Needs an antenna "
                "that lists 80 and 5 for 5ghz in GET /status (networks[].capabilities).",
                "value": {
                "radio": {
                    "band": "5ghz", "channel": 36, "channel_width": 80,
                    "wifi_generation": 5, "tx_power_level": 4,
                },
                "wifi": {
                    "ssid": "Wifi5Test", "hidden": False,
                    "security": {"encryption": "wpa2-wpa3", "password": "testpass123"},
                },
                "internet": {"enabled": True},
                "captive_portal": {"enabled": False},
            },
            },
            "wpa1_legacy": {
                "summary": "Legacy WPA (TKIP) network for old clients",
                "description": "Insecure, 802.11a/g only (20 MHz, at most 54 Mbit/s). Accepted "
                "only on antennas that list wpa1 in GET /status (networks[].capabilities.encryptions).",
                "value": {
                "radio": {
                    "band": "2.4ghz", "channel": 6, "channel_width": 20,
                    "wifi_generation": 4, "tx_power_level": 4,
                },
                "wifi": {
                    "ssid": "LegacyWpa", "hidden": False,
                    "security": {"encryption": "wpa1", "password": "testpass123"},
                },
                "internet": {"enabled": True},
                "captive_portal": {"enabled": False},
            },
            },
            "captive_portal_network": {
                "summary": "Network behind a simulated captive portal",
                "description": "Clients are redirected to the portal page until they press Sign in. "
                "Only the client that signs in is released; with internet.enabled it then reaches "
                "the Internet.",
                "value": {
                "radio": {
                    "band": "2.4ghz", "channel": 6, "channel_width": 20,
                    "wifi_generation": 4, "tx_power_level": 4,
                },
                "wifi": {
                    "ssid": "CaptiveTest", "hidden": False,
                    "security": {"encryption": "wpa2", "password": "testpass123"},
                },
                "internet": {"enabled": True},
                "captive_portal": {"enabled": True},
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
    within 20 s, each retry with at least 4 s left. A normal start takes about
    0.5 s; with retries the response can take up to about 20 s outside DFS
    channels. Clients do not need to resubmit
    the request to trigger these retries.

    After the first and second requests whose internal starts all failed, **409 / 1001**
    retains the reservation. Retry the same POST and ID only after the
    `Retry-After` header (5 and 10 seconds, respectively). Calls during cooldown
    do not consume a startup attempt. Reservation expiry is not extended.

    A third classified failure, or unsafe cleanup during startup, returns **503 / 1003** and
    invalidates the ID. Do not retry creation or release that ID. A new
    reservation request can return **503 / 1002** while recovery is running.
    No USB reset runs in the creation request.
    A network being restored by the watchdog returns an ordinary HTTP 409.

    **Body:** settings are grouped in `radio`, `wifi` (with `security`),
    `internet` and `captive_portal`, the same sections as `GET .../network`.
    Only `radio` and `wifi` are required.

    **Captive portal** (optional `captive_portal.enabled`, default `false`; omitted means
    no portal): each client that joins is held behind a simple portal page on the
    gateway (`http://<gateway>/`, reported as `captive_portal_url`). Until it
    presses **Sign in**, its DNS queries resolve to the gateway, its HTTP requests
    are redirected to the portal and other forwarded traffic, including HTTPS, is
    rejected. Sign-in releases only that client (MAC and IP); there is no API to
    sign a client in. Afterwards the network's `internet.enabled` setting applies.
    Sign-ins are cleared when the AP stops or is restored by the watchdog. A
    portal startup failure is rolled back like any other startup error (`500`).

    **Encryption, channel width and Wi-Fi generation:** `wifi.security.encryption` is one of
    `open`, `wpa2`, `wpa3`, `wpa2-wpa3` or `wpa1` (legacy WPA/TKIP, only on antennas
    that support it). `wpa` is no longer accepted and returns `422`: use `wpa2`.
    Optional `radio.channel_width` (20, 40, 80 MHz; default 20) and `radio.wifi_generation`
    (4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax; default 4) select the radio mode;
    the defaults keep the previous behaviour. `GET /status` lists, per antenna,
    what it supports (`networks[].capabilities`); anything else returns `422`.
    40 MHz on 2.4 GHz may fall back to 20 MHz when neighbouring networks are
    present: `GET .../network` reports the actual `radio.channel_width.reported`.
    """
    req = body.to_request()
    if manager.watchdog.state(reservation) in ("restoring_ap", "restoring_dhcp"):
        raise HTTPException(status_code=409, detail="Network restoration is in progress")
    # A create waits for the adapter instead of answering 1006: one create at a
    # time per reservation is the client contract, and the wait is bounded.
    with hold_reservation(reservation_mgr, reservation, wait=True):
        device_id = reservation.device_id
        remaining = ceil(reservation.retry_at - monotonic())
        if remaining > 0:
            raise recovery_error(RecoveryCode.RETRY_LATER, retry_after=remaining)
        try:
            channel_mgr.validate_network(
                device_id, req.band, req.channel, req.channel_width, req.wifi_generation,
                req.encryption,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # A new network replaces one the watchdog failed to restore (WD-2).
        manager.watchdog.forget(device_id)
        try:
            manager.start_network(
                device_id, req, expires_at_timestamp=reservation.expires_at,
                allow_internal_retry=reservation.radio_failures == 0,
            )
            reservation.radio_failures = 0
            reservation.retry_at = 0
            return {"detail": f"Network {device_id} created successfully"}
        except StartupFailure as e:
            # The next attempt reads the channel list again (BUG-4).
            channel_mgr.invalidate(device_id)
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
        503: DEVICE_BUSY_RESPONSE,
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
    With `runtime_state: restore_failed` (the watchdog could not restart the AP
    and keeps retrying), this stops the retries and returns 200; the
    reservation stays valid.

    Returns:
        dict: Confirmation with stopped device_id.
    """
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        st = manager.get_status(device_id)
        if not st:
            raise HTTPException(status_code=404, detail="Unknown device_id")
        if not st.active:
            if manager.watchdog.forget(device_id):
                # The client gives up a network the watchdog failed to restore (WD-2).
                return {"detail": f"Network {device_id} stopped successfully"}
            raise HTTPException(status_code=409, detail=f"Network {device_id} is already inactive")

        manager.stop_network(device_id)
        return {"detail": f"Network {device_id} stopped successfully"}


@router.get(
    "/{reservation_id}/network",
    response_model=NetworkResponse,
    responses={
        503: DEVICE_BUSY_RESPONSE,
        200: {
            "description": (
                "Network status in sections: `reservation`, `radio`, `wifi`, `ip`, `internet`, "
                "`captive_portal` and `clients`. While the network is not running, or while the "
                "watchdog restores it, only `interface`, `active`, `runtime_state` and "
                "`reservation` are set and the sections are null."
            ),
            "content": {"application/json": {"examples": {
                "active": {
                    "summary": "Active 5 GHz network at 80 MHz with Internet and two clients",
                    "value": {
                        "interface": "wlx7419f8176286", "active": True, "runtime_state": None,
                        "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3471},
                        "radio": {
                            "band": "5ghz", "channel": 36,
                            "channel_width": {"requested": 80, "reported": 80},
                            "wifi_generation": 5,
                            "tx_power": {"requested_level": 4, "reported_level": 4, "reported_dbm": 20.0},
                        },
                        "wifi": {
                            "ssid": "test-network-ap-01", "hidden": False,
                            "security": {"encryption": "wpa2", "password": "12345678"},
                        },
                        "ip": {
                            "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
                            "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"},
                            "dns_server": "192.168.10.21",
                        },
                        "internet": {"enabled": True},
                        "captive_portal": {"enabled": False, "url": None},
                        "clients": [
                            {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.10"},
                            {"mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.120.11"},
                        ],
                    },
                },
                "restoring_ap": {"value": {
                    "interface": "wlan0", "active": False, "runtime_state": "restoring_ap",
                    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 54},
                }},
                "restoring_dhcp": {"value": {
                    "interface": "wlan0", "active": True, "runtime_state": "restoring_dhcp",
                    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 53},
                }},
                "dhcp_failed": {"value": {
                    "interface": "wlan0", "active": True, "runtime_state": "dhcp_failed",
                    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 51},
                }},
                "restore_failed": {
                    "summary": "AP restart failed; the watchdog retries with backoff",
                    "value": {
                    "interface": "wlan0", "active": False, "runtime_state": "restore_failed",
                    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3300},
                },
                },
                "captive_portal": {
                    "summary": "Active network with a captive portal",
                    "value": {
                        "interface": "wlan0", "active": True, "runtime_state": None,
                        "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3540},
                        "radio": {
                            "band": "2.4ghz", "channel": 6,
                            "channel_width": {"requested": 20, "reported": 20},
                            "wifi_generation": 4,
                            "tx_power": {"requested_level": 4, "reported_level": 4, "reported_dbm": 20.0},
                        },
                        "wifi": {
                            "ssid": "CaptiveTest", "hidden": False,
                            "security": {"encryption": "wpa2", "password": "testpass123"},
                        },
                        "ip": {
                            "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
                            "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"},
                            "dns_server": "192.168.10.21",
                        },
                        "internet": {"enabled": True},
                        "captive_portal": {"enabled": True, "url": "http://192.168.120.1/"},
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

    The answer is grouped in sections (`reservation`, `radio`, `wifi`, `ip`,
    `internet`, `captive_portal`, `clients`); they are null while the network
    is not running. `wifi.security.password` is returned so that test devices
    can be connected.
    """
    runtime_state = manager.watchdog.state(reservation)
    if runtime_state in ("restoring_ap", "restoring_dhcp"):
        return NetworkResponse(
            interface=reservation.device_id, active=runtime_state == "restoring_dhcp",
            runtime_state=runtime_state,
            reservation=ReservationInfo(
                expires_at=format_utc_timestamp(reservation.expires_at),
                expires_in=reservation.expires_in,
            ),
        )
    with hold_reservation(reservation_mgr, reservation):
        device_id = reservation.device_id
        st = manager.get_status(device_id)
        if not st:
            raise HTTPException(status_code=404, detail="Unknown device_id")
        st.expires_at = format_utc_timestamp(reservation.expires_at)
        st.expires_in = reservation.expires_in
        st = st.model_copy(update={"runtime_state": manager.watchdog.state(reservation)})
        return NetworkResponse.from_status(st, dns_server=manager.config.dns_server)


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
        503: DEVICE_BUSY_RESPONSE,
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
