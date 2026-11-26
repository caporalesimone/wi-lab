"""Optional, read-only configuration diagnostics."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from .config import AppConfig, _read_raw_config


def validate_config_file(path: str) -> tuple[list[str], list[str]]:
    """Return errors and warnings without disclosing configuration values.

    Errors come only from `AppConfig`, after the same normalization as
    `load_config`, so the verdict is the startup's (BUG-3).
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return ["Cannot read or parse configuration file."], []
    if not isinstance(raw, dict):
        return ["Configuration must be a YAML mapping."], []

    warnings: list[str] = []
    for key in raw:
        if key not in AppConfig.model_fields:
            warnings.append(f"Unknown top-level key: {key!s}")
    antennas = raw.get("antennas")
    if isinstance(antennas, list):
        for index, entry in enumerate(antennas):
            if not isinstance(entry, dict):
                continue
            for key in entry:
                if key not in {"interface", "display_name", "disable", "show_dfs_channels"}:
                    warnings.append(f"Unknown or ignored key in antennas[{index}]: {key!s}")

    try:
        config = AppConfig(**_read_raw_config(path, quiet=True))
    except TypeError as exc:
        return [f"Invalid configuration: {exc}."], warnings
    except ValidationError as exc:
        errors = []
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            # Errors of the whole model (timeouts) have no location: their own
            # message names the fields and never contains values.
            errors.append(f"Invalid configuration field: {location}" if location
                          else f"Invalid configuration: {error['msg']}")
        return errors, warnings

    if config.auth_token == "secret-token-12345":
        warnings.append("auth_token is still set to the example value.")
    if config.protected_commands_password == "change-me":
        warnings.append("protected_commands_password is still set to the example value.")
    return [], warnings
