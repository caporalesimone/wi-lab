import logging
import os
import re
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .devices import Device

logger = logging.getLogger(__name__)


class NetworkEntry(BaseModel):
    """The label of an antenna in config.yaml; the managed devices are in DeviceRegistry."""

    interface: str
    display_name: str
    # Exclude this radio from discovery and allocation.
    disable: bool = False
    # DFS channels (5 GHz 52-144, radar detection) are listed and accepted only
    # when true. Required in config.yaml; radios not listed there get true.
    show_dfs_channels: bool = True

    @property
    def device_id(self) -> str:
        """Stable internal identifier derived from interface name."""
        return self.interface

class AppConfig(BaseModel):
    # Every rule lives here, so `--validate-config` and the service startup give
    # the same verdict (BUG-3). Messages never repeat the configured values.
    # Every setting is required, so whoever writes config.yaml chooses it: only
    # hostapd_debug_dir and the antennas section may be left out.
    # protected_commands_password and cors_origins may be null (feature off).
    auth_token: str
    api_port: int = Field(..., ge=1, le=65535)
    # Port of the captive portal pages on each gateway (NET-10). Clients still
    # browse to port 80: a DNAT rule sends them here. Not 80, so Wi-Lab itself
    # can listen on port 80 of every address.
    captive_portal_port: int = Field(..., ge=1, le=65535)
    max_timeout: int
    min_timeout: int
    allow_unlimited_reservation: bool
    dhcp_base_network: str
    upstream_interface: str
    country_code: str
    protected_commands_password: str | None
    # Diagnostics: save the `hostapd -d` output and configuration of every failed
    # hostapd start in this directory (None: off).
    hostapd_debug_dir: str | None = None
    # Required (NET-8): the DNS server handed to Wi-Fi clients. No default: any
    # address chosen here would be wrong on some network.
    dns_server: str
    internet_enabled_by_default: bool
    # Optional display names and settings of the discovered radios (`antennas:`),
    # as read from config.yaml; never changed at runtime (ARCH-4).
    antennas: list[NetworkEntry] = Field(default_factory=list)
    cors_origins: list[str] | None = Field(
        ...,
        description="CORS allowed origins. If None or empty, CORS is disabled (secure for production). "
                    "For development, add frontend URLs like ['http://localhost:4200', 'http://192.168.1.100:4200']"
    )

    @field_validator('country_code')
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        if value.strip().upper() in {"EU", "ETSI", "FCC"}:
            raise ValueError("Use a country code such as IT or US, not a regulatory region")
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("country_code must be two uppercase ASCII letters")
        return value

    @field_validator('auth_token')
    @classmethod
    def validate_auth_token(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("auth_token must not be empty")
        return value

    @field_validator('dns_server')
    @classmethod
    def validate_dns_server(cls, value: str) -> str:
        try:
            return str(IPv4Address(value))
        except ValueError:
            raise ValueError("dns_server must be a valid IPv4 address") from None

    @model_validator(mode="after")
    def validate_timeouts(self) -> "AppConfig":
        if self.max_timeout <= 0 or self.max_timeout < self.min_timeout:
            raise ValueError("max_timeout must be positive and at least min_timeout")
        if self.captive_portal_port in (self.api_port, 53, 67):
            # The API listens on every address; DNS and DHCP run on the gateway.
            raise ValueError("captive_portal_port must differ from api_port, 53 (DNS) and 67 (DHCP)")
        return self

    @field_validator('protected_commands_password')
    @classmethod
    def disable_blank_protected_password(cls, value: str | None) -> str | None:
        return value if value and value.strip() else None

    @field_validator('min_timeout')
    @classmethod
    def validate_min_timeout(cls, v: int) -> int:
        if v < 10:
            raise ValueError("min_timeout must be at least 10 seconds (hardcoded floor)")
        return v

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

    @field_validator('antennas', mode='before')
    @classmethod
    def require_show_dfs_channels(cls, value: Any) -> Any:
        """Every `antennas` entry states `show_dfs_channels`: there is no silent default."""
        if isinstance(value, list):
            for index, entry in enumerate(value):
                if isinstance(entry, dict) and "show_dfs" in entry:
                    # Renamed in 4.1.0 without an alias: say so instead of "required".
                    raise ValueError(f"antennas[{index}].show_dfs was renamed show_dfs_channels")
                if isinstance(entry, dict) and "show_dfs_channels" not in entry:
                    raise ValueError(f"antennas[{index}].show_dfs_channels is required (true or false)")
        return value

    @field_validator('antennas')
    @classmethod
    def validate_network_count(cls, v: list[NetworkEntry], info) -> list[NetworkEntry]:
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
        
        # Check for duplicate interfaces
        interfaces = [n.interface for n in v]
        if len(interfaces) != len(set(interfaces)):
            raise ValueError("Duplicate interface names in antennas configuration")
        
        return v


def resolve_networks(
    labels: list[NetworkEntry], radios: list[Any], excluded: set[str], *, quiet: bool = False,
) -> list[Device]:
    """Build managed devices from discovered radios, naming them from configured labels.

    Configured interfaces keep their configured order (stable DHCP subnets); other
    radios follow sorted by name. Only one interface per physical radio is managed,
    and a disabled interface excludes its whole radio. `quiet` logs skips at debug
    level for repeated background scans.
    """
    info = logger.debug if quiet else logger.info
    warning = logger.debug if quiet else logger.warning
    disabled = {label.interface for label in labels if label.disable}
    labels = [label for label in labels if not label.disable]
    disabled_phys = {r.phy for r in radios if r.interface in disabled}
    for interface in sorted(disabled):
        info("Skipping %s: disabled in configuration", interface)
    radios = [r for r in radios if r.phy not in disabled_phys]
    names = {label.interface: label.display_name for label in labels}
    show_dfs_channels = {label.interface: label.show_dfs_channels for label in labels}
    by_interface = {r.interface: r for r in radios if r.interface not in excluded}
    for r in radios:
        if r.interface in excluded:
            info("Skipping %s: used as upstream interface", r.interface)
    for label in labels:
        if label.interface not in by_interface:
            warning(
                "Configured interface %s (%s) not found or not usable as AP; skipping",
                label.interface, label.display_name,
            )
    ordered = [by_interface[label.interface] for label in labels if label.interface in by_interface]
    ordered += sorted((r for r in by_interface.values() if r.interface not in names),
                      key=lambda r: r.interface)
    networks: list[Device] = []
    used_phys: set[str] = set()
    for r in ordered:
        if r.phy in used_phys:
            info("Skipping %s: %s already managed via another interface", r.interface, r.phy)
            continue
        used_phys.add(r.phy)
        networks.append(Device(
            interface=r.interface,
            display_name=names.get(r.interface, r.interface),
            usb_port=r.usb_port,
            show_dfs_channels=show_dfs_channels.get(r.interface, True),
        ))
    return networks


def select_new_networks(
    current: list[Device], labels: list[NetworkEntry], radios: list[Any], excluded: set[str],
    *, quiet: bool = False,
) -> list[Device]:
    """Return discovered radios not yet managed, honouring disabled entries and display names."""
    managed = {n.interface for n in current}
    managed_phys = {r.phy for r in radios if r.interface in managed}
    fresh = [r for r in radios if r.interface not in managed and r.phy not in managed_phys]
    return resolve_networks(
        [label for label in labels if label.interface not in managed], fresh, excluded, quiet=quiet,
    )


def config_path(path: str | None = None) -> str:
    return path or os.environ.get('CONFIG_PATH') or os.path.join(os.getcwd(), 'config.yaml')


def _read_raw_config(cfg_path: str, *, quiet: bool = False) -> dict:
    with open(cfg_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}
    # A config saved with the wrong shape must be a clear error, not an
    # AttributeError/TypeError that kills the discovery thread (WD-9).
    if not isinstance(raw, dict):
        raise TypeError("Configuration must be a YAML mapping")
    if raw.get('antennas') is None:
        raw['antennas'] = []
    if not isinstance(raw['antennas'], list):
        raise TypeError("antennas must be a list")
    for entry in raw['antennas']:
        if not isinstance(entry, dict):
            continue
        if entry.get('disable') and not entry.get('display_name'):
            entry['display_name'] = entry.get('interface')
        if entry.pop('usb_recovery_port', None) is not None and not quiet:
            logger.warning(
                "Ignoring usb_recovery_port for %s: USB ports are detected automatically",
                entry.get('interface'),
            )
    return raw


def scan_new_networks(
    config: AppConfig, current: list[Device], path: str | None = None, *, quiet: bool = False,
) -> list[Device]:
    """Re-read `antennas` from the config file and discover radios not in *current*.

    Only additions are returned; managed devices are never removed or renamed.
    *config* itself is not changed: the labels are read from the file each time.

    Raises:
        ValueError: If the configuration file cannot be read or is invalid.
    """
    from .wifi.discovery import default_route_interfaces, discover_radios

    cfg_path = config_path(path)
    try:
        labels = AppConfig(**_read_raw_config(cfg_path, quiet=quiet)).antennas
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise ValueError(f"Cannot read configuration {cfg_path}: {e}") from e
    excluded = default_route_interfaces()
    if config.upstream_interface != "auto":
        excluded.add(config.upstream_interface)
    added = select_new_networks(
        current, labels, discover_radios(quiet=quiet), excluded, quiet=quiet,
    )
    base_third = int(str(IPv4Network(config.dhcp_base_network).network_address).split('.')[2])
    room = 256 - base_third - len(current)
    if len(added) > room:
        logger.warning("Only %d new interface(s) fit in dhcp_base_network; ignoring the rest", max(room, 0))
        added = added[:max(room, 0)]
    return added


def load_config(path: str | None = None) -> AppConfig:
    """Load and validate the configuration.

    `antennas` holds the labels only: the discovery service started with the API
    adds the managed devices, and its first scan reports configuration warnings.
    """
    cfg_path = config_path(path)
    try:
        return AppConfig(**_read_raw_config(cfg_path, quiet=True))

    except FileNotFoundError as e:
        raise SystemExit(f"Configuration file not found: {cfg_path}") from e
    except ValidationError as e:
        # Provide descriptive errors with field paths
        msgs = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        raise SystemExit("Configuration validation failed:\n" + "\n".join(msgs))
    except (ValueError, TypeError) as e:
        raise SystemExit(f"Configuration error: {e}") from e

