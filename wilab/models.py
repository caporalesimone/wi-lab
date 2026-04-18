from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

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

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "download_speed_kbit": 8000,
                    "upload_speed_kbit": 3000,
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


class QosStatus(BaseModel):
    """Response model for GET/POST /interface/{reservation_id}/qos."""

    interface: str
    active: bool = Field(description="True if any QoS rule is active")
    download_speed_kbit: Optional[int] = Field(None, description="Current download speed limit in kbit/s")
    upload_speed_kbit: Optional[int] = Field(None, description="Current upload speed limit in kbit/s")
    download_quality: Optional[int] = Field(None, description="Current download link quality 0-100%")
    upload_quality: Optional[int] = Field(None, description="Current upload link quality 0-100%")
