import re
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)

from .wifi.channels import channel_layouts, is_valid_channel_for_band

# ASCII control characters (incl. CR/LF): never allowed in values written to hostapd.conf.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class NetworkCreateRequest(BaseModel):
    ssid: str = Field(description="Network name: 1 to 32 bytes in UTF-8, no control characters")
    channel: int
    password: str | None = Field(
        None,
        description="Required unless encryption is open: 8 to 63 bytes in UTF-8, no control characters",
    )
    encryption: str = Field(
        pattern=r"^(open|wpa1|wpa2|wpa3|wpa2-wpa3)$",
        description=(
            "`open`: no encryption. "
            "`wpa2`: WPA2-Personal (PSK, CCMP). "
            "`wpa3`: WPA3-Personal (SAE, PMF required). "
            "`wpa2-wpa3`: mixed mode; WPA3 clients use SAE with PMF, WPA2 clients use PSK. "
            "`wpa1`: legacy WPA (PSK, TKIP), only to test legacy clients: insecure, no 802.11n "
            "(802.11a/g, at most 54 Mbit/s, 20 MHz), some recent clients warn or refuse to "
            "connect, and only on antennas that support it (`GET /status`, "
            "`networks[].capabilities.encryptions`). "
            "`wpa` is no longer accepted (422): it created WPA2, use `wpa2`."
        ),
    )
    band: str = Field(pattern=r"^(2\.4ghz|5ghz)$")
    hidden: bool = False
    internet_enabled: bool | None = None
    captive_portal: bool = Field(
        False,
        description="Optional; omitted or false means no captive portal. When true, new clients "
        "are put behind a simulated captive portal: DNS and HTTP are redirected to a portal page "
        "on the gateway and other traffic is blocked until the client presses its sign-in button. "
        "Only that client is released.",
    )
    tx_power_level: int = Field(..., ge=1, le=4, description="TX power level (1=low, 4=max)")
    channel_width: Literal[20, 40, 80] = Field(
        20,
        description=(
            "Optional channel width in MHz, default 20. 80 only on 5 GHz and with "
            "`wifi_generation` 5 or 6. On 5 GHz a wide channel uses a fixed block "
            "(40: 36+40, 44+48, ...; 80: 36-48, 52-64, 100-112, 116-128, 132-144, 149-161, "
            "165-177); every channel of the block must be available, DFS ones included. "
            "On 2.4 GHz 40 MHz is accepted, but hostapd falls back to 20 MHz when it sees "
            "neighbouring networks (20/40 coexistence): check `reported_channel_width` in "
            "`GET .../network`. Only widths listed in `GET /status` "
            "(`networks[].capabilities.channel_widths`) are accepted."
        ),
    )
    wifi_generation: Literal[4, 5, 6] = Field(
        4,
        description=(
            "Optional Wi-Fi generation, default 4: 4 = Wi-Fi 4 (802.11n), 5 = Wi-Fi 5 "
            "(802.11ac, 5 GHz only), 6 = Wi-Fi 6 (802.11ax). Only generations listed in "
            "`GET /status` (`networks[].capabilities.wifi_generations`) are accepted."
        ),
    )

    # Swagger/OpenAPI example
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "ssid": "TestNetwork",
                    "channel": 5,
                    "password": "testpass123",
                    "encryption": "wpa2",
                    "band": "2.4ghz",
                    "tx_power_level": 4,
                    "hidden": False,
                    "internet_enabled": True,
                    "captive_portal": False,
                    "channel_width": 20,
                    "wifi_generation": 4
                }
            ]
        }
    )

    @field_validator("encryption", mode="before")
    @classmethod
    def reject_wpa(cls, v: object) -> object:
        """`wpa` used to create WPA2 silently (HAP-10): refuse it with the way out."""
        if v == "wpa":
            raise ValueError(
                "'wpa' is no longer accepted: use 'wpa2' (what 'wpa' used to create) "
                "or 'wpa1' for legacy WPA/TKIP"
            )
        return v

    @field_validator("ssid")
    @classmethod
    def validate_ssid(cls, v: str) -> str:
        """SSID: 1 to 32 bytes in UTF-8, no control characters (they would reach hostapd.conf)."""
        if _CONTROL_CHARS.search(v):
            raise ValueError("ssid must not contain control characters")
        if not 1 <= len(v.encode("utf-8")) <= 32:
            raise ValueError("ssid must be 1 to 32 bytes long in UTF-8")
        return v

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "NetworkCreateRequest":
        """Rules that compare fields.

        A field validator only sees the fields declared before it, so checks that
        involve ``band`` or ``encryption`` (declared after ``channel``/``password``)
        must run here, once every field has been parsed.
        """
        if not is_valid_channel_for_band(self.channel, self.band):
            raise ValueError(f"Channel {self.channel} is not a valid WiFi channel for band {self.band}")
        if self.password is not None and _CONTROL_CHARS.search(self.password):
            raise ValueError("password must not contain control characters")
        self._validate_mode()
        if self.encryption == "open":
            return self
        if self.password is None:
            raise ValueError(f"Password required for {self.encryption} encryption")
        length = len(self.password.encode("utf-8"))
        if not 8 <= length <= 63:
            raise ValueError(
                f"{self.encryption} requires a password of 8 to 63 bytes (got {length})"
            )
        return self

    def _validate_mode(self) -> None:
        """Channel width and Wi-Fi generation rules that need no hardware (HAP-11)."""
        if self.encryption == "wpa1" and (self.channel_width != 20 or self.wifi_generation != 4):
            raise ValueError(
                "wpa1 (TKIP) cannot use 802.11n or newer: use channel_width 20 and wifi_generation 4"
            )
        if self.band == "2.4ghz" and self.wifi_generation == 5:
            raise ValueError("wifi_generation 5 (802.11ac) is only available on 5ghz")
        if self.channel_width == 80 and self.wifi_generation == 4:
            raise ValueError("channel_width 80 needs wifi_generation 5 or 6")
        channel_layouts(self.band, self.channel, self.channel_width)


class ClientInfo(BaseModel):
    mac: str
    ip: str
    captive_authorized: bool | None = Field(
        None, description="Present only with a captive portal: true once the client has signed in",
    )

    @model_serializer(mode="wrap")
    def _omit_without_portal(self, handler):
        data = handler(self)
        if isinstance(data, dict) and data.get("captive_authorized") is None:
            data.pop("captive_authorized", None)
        return data


class NetworkTxPower(BaseModel):
    requested_level: int = Field(..., ge=1, le=4, description="Requested TX power level 1-4")
    reported_level: int | None = Field(None, ge=1, le=4, description="TX power level derived from reported_dbm")
    reported_dbm: float | None = Field(None, description="TX power currently reported by interface in dBm")

class NetworkStatus(BaseModel):
    interface: str
    active: bool
    runtime_state: str | None = Field(
        None, description=(
            "Watchdog state: restoring_ap, restoring_dhcp, dhcp_failed, or restore_failed "
            "(AP restart failed; the watchdog retries with backoff while the reservation is valid)."
        ),
    )
    ssid: str | None = None
    channel: int | None = None
    password: str | None = None
    encryption: str | None = None
    band: str | None = None
    hidden: bool | None = None
    channel_width: Literal[20, 40, 80] | None = Field(None, description="Requested channel width in MHz")
    reported_channel_width: int | None = Field(
        None, description=(
            "Channel width in MHz the radio reports now (`iw dev <if> info`); lower than "
            "`channel_width` when hostapd fell back to a narrower channel (2.4 GHz 20/40 coexistence)"
        ),
    )
    wifi_generation: Literal[4, 5, 6] | None = Field(
        None, description="Requested Wi-Fi generation: 4 (802.11n), 5 (802.11ac), 6 (802.11ax)",
    )
    subnet: str | None = None
    internet_enabled: bool = False
    captive_portal: bool = Field(False, description="True if clients are held behind the captive portal until they sign in")
    captive_portal_url: str | None = Field(
        None, description="Portal page URL, reachable from the AP clients; null without a portal",
    )
    tx_power_level: int | None = Field(None, description="Internal requested TX power level 1-4", exclude=True)
    tx_power: NetworkTxPower | None = Field(None, description="Requested and reported TX power details")
    expires_at: str | None = Field(
        None, description="Expiration timestamp in UTC (RFC 3339 with a Z suffix), null if unlimited",
        json_schema_extra={"format": "date-time", "examples": ["2026-11-19T23:00:00Z"]},
    )
    expires_in: int | None = Field(None, description="Seconds remaining until network auto-shutdown")
    dhcp: dict | None = Field(None, description="DHCP server configuration details")
    clients_connected: int | None = Field(None, description="Number of clients currently connected")
    clients: list[ClientInfo] | None = Field(None, description="List of connected clients")

# --- Network API models (API-8, first step of ARCH-3) ---
#
# The create body and the GET .../network response are grouped in sections:
# radio, wifi (with security), internet, captive_portal, plus ip and reservation
# in the response. Inside Wi-Lab the flat NetworkCreateRequest and NetworkStatus
# stay the working models: the body is converted to the first, which runs every
# cross-field check, and the response is built from the second.

def _doc(name: str) -> str | None:
    """The description of a NetworkCreateRequest field, so both models document it the same way."""
    return NetworkCreateRequest.model_fields[name].description


_ENCRYPTIONS: list[JsonValue] = ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"]
# Where each flat field lives in the body, for validation messages.
_BODY_PATHS = {
    "band": "radio.band", "channel": "radio.channel", "channel_width": "radio.channel_width",
    "wifi_generation": "radio.wifi_generation", "tx_power_level": "radio.tx_power_level",
    "ssid": "wifi.ssid", "hidden": "wifi.hidden", "encryption": "wifi.security.encryption",
    "password": "wifi.security.password", "internet_enabled": "internet.enabled",
    "captive_portal": "captive_portal.enabled",
}


class RadioSettings(BaseModel):
    band: str = Field(pattern=r"^(2\.4ghz|5ghz)$", description="`2.4ghz` or `5ghz`")
    channel: int = Field(description="Primary channel; must be valid for `band` and enabled on the antenna")
    channel_width: Literal[20, 40, 80] = Field(20, description=_doc("channel_width"))
    wifi_generation: Literal[4, 5, 6] = Field(4, description=_doc("wifi_generation"))
    tx_power_level: int = Field(..., ge=1, le=4, description="TX power level (1=low, 4=max)")


class SecuritySettings(BaseModel):
    # Checked by NetworkCreateRequest, which explains a refused `wpa`.
    encryption: str = Field(description=_doc("encryption"), json_schema_extra={"enum": _ENCRYPTIONS})
    password: str | None = Field(None, description=_doc("password"))


class WifiSettings(BaseModel):
    ssid: str = Field(description=_doc("ssid"))
    hidden: bool = Field(False, description="Hide the SSID from scans; clients must know it")
    security: SecuritySettings


class InternetSettings(BaseModel):
    enabled: bool | None = Field(
        None, description="NAT to the upstream network; omitted means the server default "
        "(`internet_enabled_by_default`)",
    )


class CaptivePortalSettings(BaseModel):
    enabled: bool = Field(False, description=_doc("captive_portal"))


class NetworkCreateBody(BaseModel):
    """Body of `POST .../network`. Only `radio` and `wifi` are required."""

    radio: RadioSettings
    wifi: WifiSettings
    internet: InternetSettings = Field(default_factory=InternetSettings)
    captive_portal: CaptivePortalSettings = Field(default_factory=CaptivePortalSettings)
    _request: NetworkCreateRequest | None = PrivateAttr(None)

    @model_validator(mode="after")
    def _check(self) -> "NetworkCreateBody":
        try:
            self._request = NetworkCreateRequest(
                **self.radio.model_dump(), ssid=self.wifi.ssid, hidden=self.wifi.hidden,
                **self.wifi.security.model_dump(), internet_enabled=self.internet.enabled,
                captive_portal=self.captive_portal.enabled,
            )
        except ValidationError as exc:
            error = exc.errors()[0]
            message = error["msg"].removeprefix("Value error, ")
            field = str(error["loc"][0]) if error["loc"] else None
            path = _BODY_PATHS.get(field) if field else None
            raise ValueError(f"{path}: {message}" if path else message) from None
        return self

    def to_request(self) -> NetworkCreateRequest:
        """The flat settings the network manager works with."""
        assert self._request is not None
        return self._request


class ChannelWidthInfo(BaseModel):
    requested: int = Field(description="Channel width in MHz asked in the create")
    reported: int | None = Field(
        None, description="Width the radio reports now (`iw dev <if> info`); lower than `requested` "
        "when hostapd fell back to a narrower channel (2.4 GHz 20/40 coexistence)",
    )


class RadioInfo(BaseModel):
    band: str
    channel: int
    channel_width: ChannelWidthInfo
    wifi_generation: int = Field(description="4 (802.11n), 5 (802.11ac), 6 (802.11ax)")
    tx_power: NetworkTxPower | None = Field(None, description="Requested and reported TX power")


class SecurityInfo(BaseModel):
    encryption: str
    password: str | None = Field(None, description="Network password; null for open networks")


class WifiInfo(BaseModel):
    ssid: str
    hidden: bool
    security: SecurityInfo


class DhcpRange(BaseModel):
    start: str
    end: str


class IpInfo(BaseModel):
    subnet: str = Field(description="AP subnet, for example 192.168.120.0/24")
    gateway: str | None = Field(None, description="Wi-Lab's address on the AP, also the clients' router")
    dhcp_range: DhcpRange | None = Field(None, description="Addresses handed out to clients")
    dns_server: str | None = Field(None, description="DNS server announced to clients by DHCP")


class InternetInfo(BaseModel):
    enabled: bool


class CaptivePortalInfo(BaseModel):
    enabled: bool
    url: str | None = Field(None, description="Portal page, reachable from the AP clients; null without a portal")


class ReservationInfo(BaseModel):
    expires_at: str | None = Field(
        None, description="Expiration timestamp in UTC (RFC 3339 with a Z suffix), null if unlimited",
        json_schema_extra={"format": "date-time", "examples": ["2026-11-19T23:00:00Z"]},
    )
    expires_in: int | None = Field(None, description="Seconds until the reservation, and the network, end")


class NetworkResponse(BaseModel):
    """`GET .../network`. Sections are null while the network is not running."""

    interface: str
    active: bool
    runtime_state: str | None = Field(None, description=NetworkStatus.model_fields["runtime_state"].description)
    reservation: ReservationInfo
    radio: RadioInfo | None = None
    wifi: WifiInfo | None = None
    ip: IpInfo | None = None
    internet: InternetInfo | None = None
    captive_portal: CaptivePortalInfo | None = None
    clients: list[ClientInfo] | None = Field(None, description="Connected clients")

    @classmethod
    def from_status(cls, st: NetworkStatus, *, dns_server: str | None = None) -> "NetworkResponse":
        reservation = ReservationInfo(expires_at=st.expires_at, expires_in=st.expires_in)
        configured = st.ssid is not None and st.band is not None and st.channel is not None
        if not (st.active and configured):
            return cls(
                interface=st.interface, active=st.active, runtime_state=st.runtime_state,
                reservation=reservation,
            )
        assert st.ssid is not None and st.band is not None and st.channel is not None
        dhcp = st.dhcp or {}
        start, _, end = str(dhcp.get("dhcp_range") or "").partition(",")
        return cls(
            interface=st.interface,
            active=st.active,
            runtime_state=st.runtime_state,
            reservation=reservation,
            radio=RadioInfo(
                band=st.band,
                channel=st.channel,
                channel_width=ChannelWidthInfo(
                    requested=st.channel_width or 20, reported=st.reported_channel_width,
                ),
                wifi_generation=st.wifi_generation or 4,
                tx_power=st.tx_power,
            ),
            wifi=WifiInfo(
                ssid=st.ssid, hidden=bool(st.hidden),
                security=SecurityInfo(encryption=st.encryption or "open", password=st.password),
            ),
            ip=IpInfo(
                subnet=st.subnet or dhcp.get("subnet", ""),
                gateway=dhcp.get("gateway"),
                dhcp_range=DhcpRange(start=start, end=end) if start and end else None,
                dns_server=dns_server,
            ),
            internet=InternetInfo(enabled=st.internet_enabled),
            captive_portal=CaptivePortalInfo(enabled=st.captive_portal, url=st.captive_portal_url),
            clients=st.clients if st.clients is not None else [],
        )


class TxPowerRequest(BaseModel):
    level: int = Field(..., description="TX power level 1 (low) to 4 (max)")

    model_config = ConfigDict(json_schema_extra={"examples": [{"level": 2}]})


class TxPowerInfo(BaseModel):
    interface: str
    max_dbm: float
    levels_dbm: dict
    tx_power: NetworkTxPower


# --- QoS Models ---

_QOS_SPEED_MIN = 1
_QOS_SPEED_MAX = 1_000_000
_QOS_QUALITY_MIN = 0
_QOS_QUALITY_MAX = 100


class DelayDistribution(str, Enum):
    """Supported netem delay distribution profiles."""
    normal = "normal"
    pareto = "pareto"
    paretonormal = "paretonormal"


class QosQualityAdvanced(BaseModel):
    """Advanced netem parameters for fine-grained link quality control.

    When provided, these values override the formula-derived parameters
    from the simple quality score.
    """

    packet_loss_percent: float | None = Field(
        None, ge=0, le=100, description="Packet loss percentage (0-100)"
    )
    delay_ms: int | None = Field(
        None, ge=0, le=5000, description="Base delay in milliseconds (0-5000)"
    )
    jitter_ms: int | None = Field(
        None, ge=0, le=1000, description="Delay jitter in milliseconds (0-1000)"
    )
    corruption_percent: float | None = Field(
        None, ge=0, le=5, description="Bit corruption percentage (0-5)"
    )
    delay_distribution: DelayDistribution = Field(
        DelayDistribution.normal, description="Delay distribution profile"
    )


class NetemParams(BaseModel):
    """Resolved netem parameters (returned in QoS status responses)."""

    packet_loss_percent: float = 0
    delay_ms: int = 0
    jitter_ms: int = 0
    corruption_percent: float = 0
    delay_distribution: str = "normal"


# --- QoS Profile Models ---


class QosProfileMode(str, Enum):
    """Playback mode for profile step execution."""
    loop = "loop"
    bounce = "bounce"
    once = "once"
    once_hold_last = "once-hold-last"


class QosProfileStep(BaseModel):
    """A single step within a QoS profile."""

    duration_sec: int = Field(..., ge=1, description="Duration of this step in seconds")
    quality: int | None = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Quality score 0-100")
    dl_speed_kbit: int | None = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Download speed cap in kbit/s")
    ul_speed_kbit: int | None = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Upload speed cap in kbit/s")
    advanced: QosQualityAdvanced | None = Field(None, description="Advanced netem override (mutually exclusive with quality)")

    @model_validator(mode="after")
    def _check_step_constraints(self) -> "QosProfileStep":
        if self.quality is not None and self.advanced is not None:
            raise ValueError("'quality' and 'advanced' are mutually exclusive within a step")
        if self.quality is None and self.advanced is None and self.dl_speed_kbit is None and self.ul_speed_kbit is None:
            raise ValueError("At least one of 'quality', 'advanced', 'dl_speed_kbit', 'ul_speed_kbit' must be set")
        return self


class QosProfile(BaseModel):
    """A named QoS profile with an ordered list of steps."""

    id: str = Field(..., min_length=1, description="Unique profile identifier")
    description: str = Field("", description="Human-readable description of the profile scenario")
    source_file: str = Field("", description="JSON filename this profile was loaded from")
    mode: QosProfileMode = Field(..., description="Playback mode")
    steps: list[QosProfileStep] = Field(..., min_length=1, description="Ordered list of steps")


class QosProfileStartRequest(BaseModel):
    """Request body for POST /interface/{reservation_id}/qos/profile.

    Either ``profile_id`` or at least one inline QoS parameter must be set, but not both.
    """

    profile_id: str | None = Field(None, description="Profile from the catalogue")
    download_speed_kbit: int | None = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Download speed cap in kbit/s")
    upload_speed_kbit: int | None = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Upload speed cap in kbit/s")
    download_quality: int | None = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Download quality 0-100")
    upload_quality: int | None = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Upload quality 0-100")
    advanced: QosQualityAdvanced | None = Field(None, description="Advanced netem override for both directions")

    @model_validator(mode="after")
    def _check_xor(self) -> "QosProfileStartRequest":
        has_profile = self.profile_id is not None
        has_inline = any([
            self.download_speed_kbit is not None,
            self.upload_speed_kbit is not None,
            self.download_quality is not None,
            self.upload_quality is not None,
            self.advanced is not None,
        ])
        if has_profile and has_inline:
            raise ValueError("Cannot specify both 'profile_id' and inline QoS parameters")
        if not has_profile and not has_inline:
            raise ValueError("Must specify either 'profile_id' or at least one QoS parameter")
        return self


class QosProfileStepState(BaseModel):
    """Current step progress within an active profile."""

    index: int = Field(..., description="Current step index (0-based)")
    elapsed_sec: int = Field(..., description="Seconds elapsed in the current step")
    duration_sec: int = Field(..., description="Total duration of the current step")


class QosProfileState(BaseModel):
    """Response model for profile status endpoints."""

    interface: str
    active: bool = Field(description="True if a profile is currently running")
    profile_id: str | None = Field(None, description="Active profile ID")
    description: str | None = Field(None, description="Active profile description")
    source_file: str | None = Field(None, description="JSON file this profile was loaded from")
    mode: QosProfileMode | None = Field(None, description="Playback mode")
    steps: int | None = Field(None, description="Total number of steps in the profile")
    current_step: QosProfileStepState | None = Field(None, description="Current step info")
    total_elapsed_sec: int | None = Field(None, description="Total seconds since profile started")
