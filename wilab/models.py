from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

from .wifi.channels import is_valid_channel_for_band


class NetworkCreateRequest(BaseModel):
    ssid: str
    channel: int
    password: Optional[str] = None
    encryption: str = Field(pattern=r"^(open|wpa|wpa2|wpa3|wpa2-wpa3)$")
    band: str = Field(pattern=r"^(2\.4ghz|5ghz|dual)$")
    hidden: bool = False
    internet_enabled: Optional[bool] = None
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
                    "tx_power_level": 4
                }
            ]
        }
    )

    @field_validator('channel')
    @classmethod
    def validate_channel_for_band(cls, v: int, info) -> int:
        """Validate channel is appropriate for the band."""
        if 'band' not in info.data:
            return v
        band = info.data['band']
        if not is_valid_channel_for_band(v, band):
            raise ValueError(f"Channel {v} is not a valid WiFi channel for band {band}")
        return v

    @field_validator('password')
    @classmethod
    def validate_password_length(cls, v: Optional[str], info) -> Optional[str]:
        """Validate password length for WPA/WPA2/WPA3."""
        if v is None:
            return v
        
        if 'encryption' not in info.data:
            return v
        
        encryption = info.data['encryption']
        
        # WPA/WPA2/WPA3 require minimum 8 characters
        if encryption in ['wpa', 'wpa2', 'wpa3', 'wpa2-wpa3']:
            if len(v) < 8:
                raise ValueError(f"{encryption} requires password of at least 8 characters (got {len(v)})")
            if len(v) > 63:
                raise ValueError(f"Password too long (max 63 characters, got {len(v)})")
        
        return v
    
    @field_validator('encryption')
    @classmethod
    def validate_password_required(cls, v: str, info) -> str:
        """Check that password is provided for encrypted networks."""
        if v != 'open' and info.data.get('password') is None:
            raise ValueError(f"Password required for {v} encryption")
        return v

class ClientInfo(BaseModel):
    mac: str
    ip: str


class NetworkTxPower(BaseModel):
    requested_level: int = Field(..., ge=1, le=4, description="Requested TX power level 1-4")
    reported_level: Optional[int] = Field(None, ge=1, le=4, description="TX power level derived from reported_dbm")
    reported_dbm: Optional[float] = Field(None, description="TX power currently reported by interface in dBm")

class NetworkStatus(BaseModel):
    interface: str
    active: bool
    ssid: Optional[str] = None
    channel: Optional[int] = None
    password: Optional[str] = None
    encryption: Optional[str] = None
    band: Optional[str] = None
    hidden: Optional[bool] = None
    subnet: Optional[str] = None
    internet_enabled: bool = False
    tx_power_level: Optional[int] = Field(None, description="Internal requested TX power level 1-4", exclude=True)
    tx_power: Optional[NetworkTxPower] = Field(None, description="Requested and reported TX power details")
    expires_at: Optional[str] = Field(None, description="Network expiration date and time in format: yyyy-mm-dd HH:MM:SS")
    expires_in: Optional[int] = Field(None, description="Seconds remaining until network auto-shutdown")
    dhcp: Optional[dict] = Field(None, description="DHCP server configuration details")
    clients_connected: Optional[int] = Field(None, description="Number of clients currently connected")
    clients: Optional[List[ClientInfo]] = Field(None, description="List of connected clients")

class InterfaceStatus(BaseModel):
    interface: str
    active: bool

class TxPowerRequest(BaseModel):
    level: int = Field(..., description="TX power level 1 (low) to 4 (max)")


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

    packet_loss_percent: Optional[float] = Field(
        None, ge=0, le=100, description="Packet loss percentage (0-100)"
    )
    delay_ms: Optional[int] = Field(
        None, ge=0, le=5000, description="Base delay in milliseconds (0-5000)"
    )
    jitter_ms: Optional[int] = Field(
        None, ge=0, le=1000, description="Delay jitter in milliseconds (0-1000)"
    )
    corruption_percent: Optional[float] = Field(
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


class QosRequest(BaseModel):
    """Request body for POST /interface/{reservation_id}/qos.

    All fields are optional. Omitting a field preserves its current value.
    Sending ``null`` resets the setting to unlimited / inactive.
    """

    download_speed_kbit: Optional[int] = Field(
        None,
        description="Download speed limit in kbit/s (1-1000000), or null to reset",
    )
    upload_speed_kbit: Optional[int] = Field(
        None,
        description="Upload speed limit in kbit/s (1-1000000), or null to reset",
    )
    download_quality: Optional[int] = Field(
        None,
        description="Download link quality 0-100% (100=perfect), or null to reset",
    )
    upload_quality: Optional[int] = Field(
        None,
        description="Upload link quality 0-100% (100=perfect), or null to reset",
    )
    download_quality_advanced: Optional[QosQualityAdvanced] = Field(
        None,
        description="Advanced download netem params (overrides quality score)",
    )
    upload_quality_advanced: Optional[QosQualityAdvanced] = Field(
        None,
        description="Advanced upload netem params (overrides quality score)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "download_speed_kbit": 8000,
                    "upload_speed_kbit": 3000,
                    "download_quality": 80,
                    "upload_quality": 65,
                }
            ]
        }
    )

    @field_validator("download_speed_kbit", "upload_speed_kbit", mode="before")
    @classmethod
    def _validate_speed_range(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, int):
            raise ValueError("must be an integer or null")
        if v < _QOS_SPEED_MIN or v > _QOS_SPEED_MAX:
            raise ValueError(f"must be between {_QOS_SPEED_MIN} and {_QOS_SPEED_MAX}")
        return v

    @field_validator("download_quality", "upload_quality", mode="before")
    @classmethod
    def _validate_quality_range(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, int):
            raise ValueError("must be an integer or null")
        if v < _QOS_QUALITY_MIN or v > _QOS_QUALITY_MAX:
            raise ValueError(f"must be between {_QOS_QUALITY_MIN} and {_QOS_QUALITY_MAX}")
        return v


class QosStatus(BaseModel):
    """Response model for GET/POST /interface/{reservation_id}/qos."""

    interface: str
    active: bool = Field(description="True if any QoS rule is active")
    download_speed_kbit: Optional[int] = Field(None, description="Current download speed limit in kbit/s")
    upload_speed_kbit: Optional[int] = Field(None, description="Current upload speed limit in kbit/s")
    download_quality: Optional[int] = Field(None, description="Current download link quality 0-100%")
    upload_quality: Optional[int] = Field(None, description="Current upload link quality 0-100%")
    download_netem_params: Optional[NetemParams] = Field(None, description="Resolved download netem parameters")
    upload_netem_params: Optional[NetemParams] = Field(None, description="Resolved upload netem parameters")


# --- QoS Profile Models ---


class QosProfileMode(str, Enum):
    """Playback mode for profile step execution."""
    loop = "loop"
    bounce = "bounce"
    once = "once"
    hold = "hold"


class QosProfileStep(BaseModel):
    """A single step within a QoS profile."""

    duration_sec: int = Field(..., ge=1, description="Duration of this step in seconds")
    quality: Optional[int] = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Quality score 0-100")
    dl_speed_kbit: Optional[int] = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Download speed cap in kbit/s")
    ul_speed_kbit: Optional[int] = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Upload speed cap in kbit/s")
    advanced: Optional[QosQualityAdvanced] = Field(None, description="Advanced netem override (mutually exclusive with quality)")

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
    mode: QosProfileMode = Field(..., description="Playback mode")
    steps: List[QosProfileStep] = Field(..., min_length=1, description="Ordered list of steps")


class QosProfileStartRequest(BaseModel):
    """Request body for POST /interface/{reservation_id}/qos/profile.

    Either ``profile_id`` or at least one inline QoS parameter must be set, but not both.
    """

    profile_id: Optional[str] = Field(None, description="Profile from the catalogue")
    download_speed_kbit: Optional[int] = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Download speed cap in kbit/s")
    upload_speed_kbit: Optional[int] = Field(None, ge=_QOS_SPEED_MIN, le=_QOS_SPEED_MAX, description="Upload speed cap in kbit/s")
    download_quality: Optional[int] = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Download quality 0-100")
    upload_quality: Optional[int] = Field(None, ge=_QOS_QUALITY_MIN, le=_QOS_QUALITY_MAX, description="Upload quality 0-100")
    advanced: Optional[QosQualityAdvanced] = Field(None, description="Advanced netem override for both directions")

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
    profile_id: Optional[str] = Field(None, description="Active profile ID")
    description: Optional[str] = Field(None, description="Active profile description")
    mode: Optional[QosProfileMode] = Field(None, description="Playback mode")
    current_step: Optional[QosProfileStepState] = Field(None, description="Current step info")
    total_elapsed_sec: Optional[int] = Field(None, description="Total seconds since profile started")
