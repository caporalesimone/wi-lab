"""Antennas: the Wi-Fi radios Wi-Lab manages, how each is now, and what a network on it can use.

An antenna is the physical radio; a network is the AP a reservation runs on it.
`GET /antennas` lists them with how many are free and the reservation limits;
`GET /antennas/{interface}` is one antenna now (attachment, state, health);
`GET /antennas/{interface}/capabilities` what a create on it can ask, which does
not change while the adapter stays the same. Both need only the token.
`interface` is the first field of every antenna object.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from ...api.auth import require_token
from ...api.dependencies import get_channel_manager, get_config, get_devices, get_manager, get_reservation_manager
from ...config import AppConfig
from ...devices import Device, DeviceRegistry
from ...models import ReservationInfo
from ...reservation import ReservationManager
from ...network.commands import CommandError
from ...timestamps import format_utc_timestamp
from ...wifi.channels import ChannelManager, band_options
from ...wifi.discovery import detect_device
from ...wifi.manager import NetworkManager
from .status import antenna_state, assess

router = APIRouter(prefix="/antennas", tags=["Antennas"])

class AntennaState(BaseModel):
    interface: str = Field(..., description="Linux interface name; identifies the antenna in this API")
    display_name: str
    reservation: ReservationInfo | None = Field(..., description="null when the antenna is not reserved")
    network_active: bool
    recovery_state: Literal["recovering", "unavailable"] | None = Field(
        None, description="Present only while the antenna is quarantined",
    )
    runtime_state: str | None = Field(
        None, description="Present only while a start, a repair or a half-done stop is in progress",
    )


class ReservationPolicy(BaseModel):
    min_seconds: int
    max_seconds: int
    allow_unlimited: bool


class AntennaList(BaseModel):
    free_antennas: int = Field(description=(
        "Antennas a reservation would get now: not reserved, not quarantined, not held by a "
        "failed cleanup. The same value as `service.free_antennas` of `GET /status`"
    ))
    reservation_policy: ReservationPolicy = Field(description="Limits of `duration_seconds` in `POST /reservations`")
    antennas: list[AntennaState]


_POLICY_EXAMPLE = {"min_seconds": 60, "max_seconds": 86400, "allow_unlimited": False}
_LIST_EXAMPLES = {
    "all_free": {
        "summary": "Both antennas free",
        "value": {
            "free_antennas": 2,
            "reservation_policy": _POLICY_EXAMPLE,
            "antennas": [
                {"interface": "wlx7419f8176286", "display_name": "antenna-1", "reservation": None,
                 "network_active": False},
                {"interface": "wlx7419f817651c", "display_name": "antenna-2", "reservation": None,
                 "network_active": False},
            ],
        },
    },
    "one_reserved": {
        "summary": "One antenna reserved with a network, one free",
        "value": {
            "free_antennas": 1,
            "reservation_policy": _POLICY_EXAMPLE,
            "antennas": [
                {"interface": "wlx7419f8176286", "display_name": "antenna-1",
                 "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 540}, "network_active": True},
                {"interface": "wlx7419f817651c", "display_name": "antenna-2", "reservation": None,
                 "network_active": False},
            ],
        },
    },
    "quarantine_and_repair": {
        "summary": "One antenna quarantined, the other's network being repaired",
        "value": {
            "free_antennas": 0,
            "reservation_policy": _POLICY_EXAMPLE,
            "antennas": [
                {"interface": "wlx7419f8176286", "display_name": "antenna-1", "reservation": None,
                 "network_active": False, "recovery_state": "unavailable"},
                {"interface": "wlx7419f817651c", "display_name": "antenna-2",
                 "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 54},
                 "network_active": False, "runtime_state": "restoring_ap"},
            ],
        },
    },
}


class DeviceDetails(BaseModel):
    bus: str = Field(description="`usb`, `pci` (also cards built into the motherboard) or `sdio`")
    address: str = Field(description="USB port (`2-1.3`), PCI address (`0000:02:00.0`) or SDIO device")
    driver: str | None = Field(description="Kernel driver, e.g. `mt7921u`")


class GenerationOption(BaseModel):
    wifi_generation: int = Field(description="4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax")
    channel_widths: list[int] = Field(description="Widths in MHz this generation can use on the band")


class ChannelOption(BaseModel):
    channel: int
    frequency_mhz: int
    max_power_dbm: float
    dfs: bool = Field(description="Radar detection: the AP listens about 60 s before starting")
    channel_widths: list[int] = Field(description="Widths in MHz this channel can be the primary of")


class BandOptions(BaseModel):
    wifi_generations: list[GenerationOption]
    channels: list[ChannelOption] = Field(
        description="Only channels a create can use: disabled ones, and DFS ones when "
        "`show_dfs_channels` is false, are not listed",
    )


class Bands(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    band_24ghz: BandOptions = Field(alias="2.4ghz", description="`radio.band: 2.4ghz`")
    band_5ghz: BandOptions = Field(alias="5ghz", description="`radio.band: 5ghz`")


class RepairBudgetUse(BaseModel):
    used: int = Field(description="Repairs in the current window")
    limit: int = Field(description="Repairs allowed in any window; the next failure after them quarantines the antenna")
    window_minutes: int = Field(description="Length of the sliding window")
    frees_at: str | None = Field(None, description=(
        "When the oldest repair in the window leaves it and frees one (UTC, RFC 3339); null when none is used"
    ))


class QuarantineInfo(BaseModel):
    count: int = Field(description="Quarantines since the service started")
    last_at: str | None = Field(None, description="UTC time of the last one; null if none")
    last_usb_recovery: bool | None = Field(None, description=(
        "The last one started a USB reset (radio fault on a USB adapter); false: only re-probed; null if none"
    ))


class AntennaHealth(BaseModel):
    """How the watchdog sees this antenna over time; the state right now is in `GET /antennas`."""

    ap_restores: RepairBudgetUse = Field(description="Restarts of the whole network by the watchdog")
    dhcp_restarts: RepairBudgetUse = Field(description="Restarts of DHCP alone by the watchdog")
    quarantines: QuarantineInfo
    last_usb_reset_at: str | None = Field(None, description="UTC time of the last USB reset; null if none since the service started")


class AntennaDetails(BaseModel):
    interface: str = Field(description="Linux interface name; identifies the antenna in this API")
    display_name: str = Field(description="Name from `antennas` in the configuration, else the interface")
    device: DeviceDetails | None = Field(description="Where the antenna is attached; null if sysfs does not show it")
    reservation: ReservationInfo | None = Field(description="null when the antenna is not reserved")
    network_active: bool
    recovery_state: Literal["recovering", "unavailable"] | None = Field(
        None, description="Present only while the antenna is quarantined",
    )
    runtime_state: str | None = Field(
        None, description="Present only while a start, a repair or a half-done stop is in progress",
    )
    health: AntennaHealth = Field(description=(
        "Repair budgets of the watchdog (by the antenna's driver, `watchdog` in config.yaml), "
        "quarantines and USB resets. Counted since the service started."
    ))


class AntennaCapabilities(BaseModel):
    interface: str = Field(description="Linux interface name; identifies the antenna in this API")
    encryptions: list[str] = Field(description="Encryptions a create can ask; `wpa1` only at 20 MHz with 802.11n")
    bands: Bands = Field(description="Options per band, keyed like `radio.band`")


_DETAILS_EXAMPLES = {
    "reserved": {
        "summary": "Reserved, network running, one AP restore in the window",
        "value": {
            "interface": "wlx7419f8176286",
            "display_name": "antenna-1",
            "device": {"bus": "usb", "address": "2-1", "driver": "mt7921u"},
            "reservation": {"expires_at": "2026-11-27T19:11:57Z", "expires_in": 3298},
            "network_active": True,
            "health": {
                "ap_restores": {"used": 1, "limit": 5, "window_minutes": 60, "frees_at": "2026-11-27T18:42:10Z"},
                "dhcp_restarts": {"used": 0, "limit": 3, "window_minutes": 60, "frees_at": None},
                "quarantines": {"count": 0, "last_at": None, "last_usb_recovery": None},
                "last_usb_reset_at": None,
            },
        },
    },
    "quarantined": {
        "summary": "Free but quarantined after a radio fault",
        "value": {
            "interface": "wlx7419f817651c",
            "display_name": "antenna-2",
            "device": {"bus": "usb", "address": "2-2", "driver": "mt7921u"},
            "reservation": None,
            "network_active": False,
            "recovery_state": "unavailable",
            "health": {
                "ap_restores": {"used": 5, "limit": 5, "window_minutes": 60, "frees_at": "2026-11-27T18:55:02Z"},
                "dhcp_restarts": {"used": 0, "limit": 3, "window_minutes": 60, "frees_at": None},
                "quarantines": {"count": 1, "last_at": "2026-11-27T18:20:31Z", "last_usb_recovery": True},
                "last_usb_reset_at": "2026-11-27T18:20:33Z",
            },
        },
    },
}

_CAPABILITIES_EXAMPLE = {
    "interface": "wlx7419f8176286",
    "encryptions": ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"],
    "bands": {
        "2.4ghz": {
            "wifi_generations": [
                {"wifi_generation": 4, "channel_widths": [20, 40]},
                {"wifi_generation": 6, "channel_widths": [20, 40]},
            ],
            "channels": [
                {"channel": 1, "frequency_mhz": 2412, "max_power_dbm": 20.0, "dfs": False,
                 "channel_widths": [20, 40]},
                {"channel": 13, "frequency_mhz": 2472, "max_power_dbm": 20.0, "dfs": False,
                 "channel_widths": [20, 40]},
            ],
        },
        "5ghz": {
            "wifi_generations": [
                {"wifi_generation": 4, "channel_widths": [20, 40]},
                {"wifi_generation": 5, "channel_widths": [20, 40, 80]},
                {"wifi_generation": 6, "channel_widths": [20, 40, 80]},
            ],
            "channels": [
                {"channel": 36, "frequency_mhz": 5180, "max_power_dbm": 23.0, "dfs": False,
                 "channel_widths": [20, 40, 80]},
                {"channel": 100, "frequency_mhz": 5500, "max_power_dbm": 23.0, "dfs": True,
                 "channel_widths": [20, 40, 80]},
                {"channel": 165, "frequency_mhz": 5825, "max_power_dbm": 13.0, "dfs": False,
                 "channel_widths": [20]},
            ],
        },
    },
}


@router.get(
    "",
    response_model=AntennaList,
    # Fields not computed are left out (recovery_state, runtime_state); null is kept.
    response_model_exclude_unset=True,
    summary="List the antennas, how many are free and the reservation limits",
    responses={
        200: {"content": {"application/json": {"examples": _LIST_EXAMPLES}}},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
def list_antennas(
    manager: NetworkManager = Depends(get_manager),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    config: AppConfig = Depends(get_config),
    _auth: bool = Depends(require_token),
) -> dict:
    """The managed antennas and what a reserve can ask.

    `free_antennas` is what a reservation would get now, the same value as
    `service.free_antennas` of `GET /status`. A reserve is the only sure way to
    get an antenna: another client may take the last free one in between.

    Each entry of `antennas` has `reservation` (`null` when free; both fields
    `null` for an unlimited one) and `network_active`. Two fields appear only
    when they apply:

    - `recovery_state`: `recovering` (USB reset and probe running) or
      `unavailable` (re-probed every 30 s, backing off to 15 min). The antenna is
      quarantined and not allocatable, even with `reservation: null`; it may
      return by itself.
    - `runtime_state`: a start (`starting`, `start_failed`), a repair by the
      watchdog (`restoring_ap`, `restoring_dhcp`, `dhcp_failed`, `restore_failed`)
      or a half-done stop (`stop_failed`) of the reservation's network.

    `reservation_policy` gives the limits of `duration_seconds` in
    `POST /reservations` (`0` only with `allow_unlimited: true`).

    One antenna with its health is `GET /antennas/{interface}`; what a network on
    it can use, `GET /antennas/{interface}/capabilities`.
    """
    view = assess(manager, reservation_mgr)
    return {
        "free_antennas": view["service"]["free_antennas"],
        "reservation_policy": {
            "min_seconds": config.min_timeout,
            "max_seconds": config.max_timeout,
            "allow_unlimited": config.allow_unlimited_reservation,
        },
        "antennas": view["antennas"],
    }


def _known(devices: DeviceRegistry, interface: str) -> Device:
    entry = devices.get(interface)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown antenna: {interface}")
    return entry


@router.get(
    "/{interface}",
    response_model=AntennaDetails,
    response_model_exclude_unset=True,
    summary="Read an antenna now: attachment, state and health",
    responses={
        200: {"content": {"application/json": {"examples": _DETAILS_EXAMPLES}}},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "No managed antenna has this interface"},
    },
)
def get_antenna(
    interface: str = Path(..., description="Interface name from `antennas[]` of `GET /antennas`"),
    devices: DeviceRegistry = Depends(get_devices),
    manager: NetworkManager = Depends(get_manager),
    reservation_mgr: ReservationManager = Depends(get_reservation_manager),
    _auth: bool = Depends(require_token),
) -> AntennaDetails:
    """The antenna as it is now.

    `reservation`, `network_active` and, when they apply, `recovery_state` and
    `runtime_state` are the antenna's entry of `antennas[]` in `GET /antennas`.
    `device` is where it is attached (bus, port, kernel driver).

    `health` tells how close the antenna is to a quarantine: the watchdog's
    repairs in its sliding window against the limit (from the antenna's driver,
    `watchdog` in config.yaml), when the oldest one frees, past quarantines and
    USB resets.

    What a network on it can use is in `GET /antennas/{interface}/capabilities`.
    """
    entry = _known(devices, interface)
    state, _ = antenna_state(
        manager, entry, reservation_mgr.snapshot(), reservation_mgr.recovery_snapshot(), manager.active.copy(),
    )
    device = detect_device(interface)
    return AntennaDetails(
        **state,
        device=DeviceDetails(bus=device.bus, address=device.address, driver=device.driver) if device else None,
        health=_health(manager, interface),
    )


@router.get(
    "/{interface}/capabilities",
    response_model=AntennaCapabilities,
    summary="Read what a network on an antenna can use",
    responses={
        200: {"content": {"application/json": {"example": _CAPABILITIES_EXAMPLE}}},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "No managed antenna has this interface"},
        503: {"description": "The radio cannot be read now (e.g. unplugged or being reset); retry later"},
    },
)
def get_capabilities(
    interface: str = Path(..., description="Interface name from `antennas[]` of `GET /antennas`"),
    devices: DeviceRegistry = Depends(get_devices),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
    _auth: bool = Depends(require_token),
) -> AntennaCapabilities:
    """The options of a create on this antenna, to fill a form's lists.

    Per band: the Wi-Fi generations with the channel widths each can use, and
    the channels a create can use, each with the widths it can be the primary
    channel of. Pick band, then generation, then width, then a channel whose
    `channel_widths` contains that width: the create accepts the combination.
    `wpa1` is the exception: only 802.11n (`wifi_generation` 4) at 20 MHz.

    DFS channels (5 GHz 52-144) are listed, with `dfs: true`, only when the
    antenna has `show_dfs_channels: true` in the configuration. The data comes from the
    radio and is cached; it does not change while the adapter stays the same,
    so a client can read it once per antenna. No reservation is needed.
    """
    _known(devices, interface)
    try:
        info = channel_mgr.get_channels(interface)
    except (CommandError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Cannot read antenna {interface}: {exc}") from exc
    bands: dict[str, BandOptions] = {}
    for band in ("2.4ghz", "5ghz"):
        options = band_options(info, band)
        bands[band] = BandOptions(
            wifi_generations=[
                GenerationOption(wifi_generation=g, channel_widths=w)
                for g, w in options.wifi_generations.items()
            ],
            channels=[
                ChannelOption(
                    channel=c.info.channel, frequency_mhz=c.info.frequency_mhz,
                    max_power_dbm=c.info.max_power_dbm, dfs=c.info.requires_dfs,
                    channel_widths=list(c.channel_widths),
                )
                for c in options.channels
            ],
        )
    return AntennaCapabilities(
        interface=interface, encryptions=info.capabilities.encryptions(), bands=Bands.model_validate(bands),
    )


def _health(manager: NetworkManager, interface: str) -> AntennaHealth:
    def use(kind: str) -> RepairBudgetUse:
        used, limit, window, frees_at = manager.watchdog.budget_use(interface, kind)
        return RepairBudgetUse(
            used=used, limit=limit, window_minutes=window, frees_at=format_utc_timestamp(frees_at),
        )

    count, last_at, usb = manager.quarantines.get(interface, (0, None, None))
    reset_at = manager.recovery.last_usb_reset.get(interface)
    return AntennaHealth(
        ap_restores=use("ap_restores"), dhcp_restarts=use("dhcp_restarts"),
        quarantines=QuarantineInfo(
            count=count, last_at=format_utc_timestamp(last_at), last_usb_recovery=usb,
        ),
        last_usb_reset_at=format_utc_timestamp(reset_at),
    )
