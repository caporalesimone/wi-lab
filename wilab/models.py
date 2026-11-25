import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from .wifi.channels import is_valid_channel_for_band

# ASCII control characters (incl. CR/LF): never allowed in values written to hostapd.conf.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class NetworkCreateRequest(BaseModel):
    ssid: str = Field(description="Network name: 1 to 32 bytes in UTF-8, no control characters")
    channel: int
    password: str | None = Field(
        None,
        description="Required unless encryption is open: 8 to 63 bytes in UTF-8, no control characters",
    )
    encryption: str = Field(pattern=r"^(open|wpa|wpa2|wpa3|wpa2-wpa3)$")
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
                    "internet_enabled": True,
                    "captive_portal": False,
                    "tx_power_level": 4
                }
            ]
        }
    )

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
