import re
import os
from typing import List, Optional
from ipaddress import IPv4Network
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

NET_ID_REGEX = re.compile(r"^[a-z0-9-]{1,16}$")
CIDR_REGEX = re.compile(r"^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$")


class NetworkEntry(BaseModel):
    net_id: str
    interface: str

    @field_validator('net_id')
    @classmethod
    def validate_net_id(cls, v: str) -> str:
        if not NET_ID_REGEX.match(v):
            raise ValueError("net_id must match ^[a-z0-9-]{1,16}$")
        return v

class AppConfig(BaseModel):
    auth_token: str
    api_port: int = 8080
    default_timeout: int = 3600
    max_timeout: int = 86400   # 24 hours default upper bound
    min_timeout: int = 60      # 60 seconds default lower bound
    dhcp_base_network: str
    upstream_interface: str = "auto"
    dns_server: str = "192.168.10.21"
    internet_enabled_by_default: bool = True
    networks: List[NetworkEntry]

    @field_validator('upstream_interface')
    @classmethod
    def validate_upstream_interface(cls, v: str) -> str:
        # allow 'auto' or a device name
        if v != 'auto' and not v:
            raise ValueError("upstream_interface must be 'auto' or a non-empty device name")
        return v

    @field_validator('dhcp_base_network')
    @classmethod
    def validate_dhcp_base_network(cls, v: str) -> str:
        # Require valid IPv4 CIDR and /24 prefix for sequential allocation
        try:
            net = IPv4Network(v, strict=False)
        except ValueError as e:
            raise ValueError(f"Invalid dhcp_base_network: {e}") from e
        if net.prefixlen != 24:
            raise ValueError("dhcp_base_network must be a /24 network")
        return str(net)

    @field_validator('networks')
    @classmethod
    def validate_network_count(cls, v: List[NetworkEntry], info) -> List[NetworkEntry]:
        # Check that dhcp_base_network + len(networks) doesn't overflow third octet
        if 'dhcp_base_network' not in info.data:
            return v
        
        base_net = IPv4Network(info.data['dhcp_base_network'], strict=False)
        base_third_octet = int(str(base_net.network_address).split('.')[2])
        
        # Calculate max third octet for last network
        max_third = base_third_octet + len(v) - 1
        
        if max_third > 255:
            raise ValueError(
                f"Too many networks ({len(v)}) for dhcp_base_network {info.data['dhcp_base_network']}: "
                f"third octet would overflow (max: {max_third})"
            )
        
        return v


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg_path = path or os.environ.get('CONFIG_PATH') or os.path.join(os.getcwd(), 'config.yaml')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
        config = AppConfig(**raw)
        
        # Validate interfaces at config load time
        from .wifi.interface import validate_interface, InterfaceError
        import logging
        logger = logging.getLogger(__name__)
        
        for net in config.networks:
            try:
                validate_interface(net.interface)
            except InterfaceError as e:
                logger.error(f"Interface validation failed for {net.net_id}: {e}")
                raise SystemExit(f"Configuration error for {net.net_id}: {e}")
        
        return config
        
    except FileNotFoundError as e:
        raise SystemExit(f"Configuration file not found: {cfg_path}") from e
    except ValidationError as e:
        # Provide descriptive errors with field paths
        msgs = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        raise SystemExit("Configuration validation failed:\n" + "\n".join(msgs))

