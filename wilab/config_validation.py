"""Optional, read-only configuration diagnostics."""

from ipaddress import IPv4Address
from pathlib import Path

import yaml
from pydantic import ValidationError

from .config import AppConfig


def validate_config_file(path: str) -> tuple[list[str], list[str]]:
    """Return errors and warnings without disclosing configuration values."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return ["Cannot read or parse configuration file."], []
    if not isinstance(raw, dict):
        return ["Configuration must be a YAML mapping."], []

    errors: list[str] = []
    warnings: list[str] = []
    for key in raw:
        if key not in AppConfig.model_fields:
            warnings.append(f"Unknown top-level key: {key!s}")
    networks = raw.get("networks")
    if networks is None:
        networks = []
    if isinstance(networks, list):
        for index, entry in enumerate(networks):
            if not isinstance(entry, dict):
                continue
            for key in entry:
                if key not in {"interface", "display_name", "disable"}:
                    warnings.append(f"Unknown or ignored key in networks[{index}]: {key!s}")

    # Match the normal loader's handling of disabled devices and ignored USB ports.
    normalized = dict(raw)
    if isinstance(networks, list):
        normalized["networks"] = [
            {**entry, "display_name": entry.get("display_name") or entry.get("interface")}
            if isinstance(entry, dict) and entry.get("disable") else entry
            for entry in networks
        ]
        normalized["networks"] = [
            {k: v for k, v in entry.items() if k != "usb_recovery_port"}
            if isinstance(entry, dict) else entry
            for entry in normalized["networks"]
        ]
    try:
        config = AppConfig(**normalized)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            errors.append(f"Invalid configuration field: {location}")
        return errors, warnings

    if not config.auth_token.strip():
        errors.append("auth_token must not be empty.")
    elif config.auth_token == "secret-token-12345":
        warnings.append("auth_token is still set to the example value.")
    if not 1 <= config.api_port <= 65535:
        errors.append("api_port must be between 1 and 65535.")
    if config.max_timeout <= 0 or config.min_timeout > config.max_timeout:
        errors.append("max_timeout must be positive and at least min_timeout.")
    try:
        IPv4Address(config.dns_server)
    except ValueError:
        errors.append("dns_server must be a valid IPv4 address.")
    return errors, warnings
