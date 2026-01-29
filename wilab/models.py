from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

class NetworkCreateRequest(BaseModel):
    ssid: str
    channel: int
    password: Optional[str] = None
    encryption: str = Field(pattern=r"^(open|wpa|wpa2|wpa3|wpa2-wpa3)$")
    band: str = Field(pattern=r"^(2\.4ghz|5ghz|dual)$")
    hidden: bool = False
    timeout: Optional[int] = None
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
                    "timeout": 3600,
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
        
        # 2.4GHz: channels 1-14
        if band == '2.4ghz':
            if not (1 <= v <= 14):
                raise ValueError(f"Channel {v} invalid for 2.4GHz band (must be 1-14)")
        
        # 5GHz: channels 36-165 (common UNII bands)
        elif band == '5ghz':
            valid_5ghz = list(range(36, 65, 4)) + list(range(100, 145, 4)) + list(range(149, 166, 4))
            if v not in valid_5ghz:
                raise ValueError(
                    f"Channel {v} invalid for 5GHz band (typical: 36-64, 100-144, 149-165 in steps of 4)"
                )
        
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

class NetworkStatus(BaseModel):
    net_id: str
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
    tx_power_level: Optional[int] = Field(None, description="TX power level 1-4 (4 = max)")
    expires_at: Optional[str] = Field(None, description="Network expiration date and time in format: yyyy-mm-dd HH:MM:SS")
    expires_in: Optional[int] = Field(None, description="Seconds remaining until network auto-shutdown")
    dhcp: Optional[dict] = Field(None, description="DHCP server configuration details")
    clients_connected: Optional[int] = Field(None, description="Number of clients currently connected")
    clients: Optional[List[ClientInfo]] = Field(None, description="List of connected clients")

class InterfaceStatus(BaseModel):
    net_id: str
    interface: str
    active: bool

class TxPowerRequest(BaseModel):
    level: int = Field(..., ge=1, le=4, description="TX power level 1 (low) to 4 (max)")


class TxPowerInfo(BaseModel):
    net_id: str
    interface: str
    channel: int
    frequency_mhz: int
    max_dbm: float
    levels_dbm: dict
    current_level: int
    current_dbm: float
    reported_dbm: Optional[float] = Field(None, description="TX power reported by interface (may differ from current_dbm if driver doesn't support dynamic changes)")
    warning: Optional[str] = Field(None, description="Warning message if power change not supported")
