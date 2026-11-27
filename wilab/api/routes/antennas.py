"""Antennas: the Wi-Fi radios Wi-Lab manages and what a network on each can use.

An antenna is the physical radio; a network is the AP a reservation runs on it.
These endpoints need only the token: they describe hardware, not a reservation.
"""

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from ...api.auth import require_token
from ...api.dependencies import get_channel_manager, get_devices
from ...devices import DeviceRegistry
from ...network.commands import CommandError
from ...wifi.channels import ChannelManager, band_options
from ...wifi.discovery import detect_device

router = APIRouter(prefix="/antennas", tags=["Antennas"])

class AntennaSummary(BaseModel):
    display_name: str = Field(description="Name from `antennas` in the configuration, else the interface")
    interface: str = Field(description="Linux interface name; identifies the antenna in this API")


class AntennaList(BaseModel):
    antennas: list[AntennaSummary] = Field(description="Every managed antenna, reserved or not")


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


class AntennaDetails(AntennaSummary):
    device: DeviceDetails | None = Field(description="Where the antenna is attached; null if sysfs does not show it")
    encryptions: list[str] = Field(description="Encryptions a create can ask; `wpa1` only at 20 MHz with 802.11n")
    bands: Bands = Field(description="Options per band, keyed like `radio.band`")


_DETAILS_EXAMPLE = {
    "display_name": "antenna-1",
    "interface": "wlx7419f8176286",
    "device": {"bus": "usb", "address": "2-1", "driver": "mt7921u"},
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
    summary="List the antennas",
    responses={
        200: {"content": {"application/json": {"example": {"antennas": [
            {"display_name": "antenna-1", "interface": "wlx7419f8176286"},
            {"display_name": "antenna-2", "interface": "wlx7419f817651c"},
        ]}}}},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
    },
)
def list_antennas(
    devices: DeviceRegistry = Depends(get_devices),
    _auth: bool = Depends(require_token),
) -> AntennaList:
    """Every antenna Wi-Lab manages, reserved or not, in allocation order.

    Reservation, quarantine and repair states are in `GET /status`.
    """
    return AntennaList(antennas=[
        AntennaSummary(display_name=n.display_name, interface=n.interface) for n in devices.all()
    ])


@router.get(
    "/{interface}",
    response_model=AntennaDetails,
    summary="Read what a network on an antenna can use",
    responses={
        200: {"content": {"application/json": {"example": _DETAILS_EXAMPLE}}},
        401: {"description": "Unauthorized (missing or invalid auth token)"},
        404: {"description": "No managed antenna has this interface"},
        503: {"description": "The radio cannot be read now (e.g. unplugged or being reset); retry later"},
    },
)
def get_antenna(
    interface: str = Path(..., description="Interface name from `GET /antennas`"),
    devices: DeviceRegistry = Depends(get_devices),
    channel_mgr: ChannelManager = Depends(get_channel_manager),
    _auth: bool = Depends(require_token),
) -> AntennaDetails:
    """The options of a create on this antenna, to fill a form's lists.

    Per band: the Wi-Fi generations with the channel widths each can use, and
    the channels a create can use, each with the widths it can be the primary
    channel of. Pick band, then generation, then width, then a channel whose
    `channel_widths` contains that width: the create accepts the combination.
    `wpa1` is the exception: only 802.11n (`wifi_generation` 4) at 20 MHz.

    DFS channels (5 GHz 52-144) are listed, with `dfs: true`, only when the
    antenna has `show_dfs_channels: true` in the configuration. The data comes from the
    radio and is cached; no reservation is needed.
    """
    entry = devices.get(interface)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown antenna: {interface}")
    try:
        info = channel_mgr.get_channels(interface)
    except (CommandError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Cannot read antenna {interface}: {exc}") from exc
    device = detect_device(interface)
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
    return AntennaDetails(
        display_name=entry.display_name,
        interface=entry.interface,
        device=DeviceDetails(bus=device.bus, address=device.address, driver=device.driver) if device else None,
        encryptions=info.capabilities.encryptions(),
        bands=Bands.model_validate(bands),
    )
