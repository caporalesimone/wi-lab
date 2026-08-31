"""Configuration file validation.

Validates ``config.yaml`` against the schema and a set of semantic rules, reporting
**every** problem in a single pass so an administrator can fix a configuration in one
editing session instead of a restart-fix-restart loop.

Design constraints (TODOs/device-capabilities.md §5):

* **Pure.** This module reads the configuration file and writes nothing. Wi-Lab never
  modifies the administrator's configuration.
* **Complete.** No fail-fast: every phase runs and accumulates issues.
* **Mandatory keys.** Every field the schema knows about must be present in the file.
  A value Wi-Lab invents is a value nobody reviewed.
* **Off-bench.** Hardware checks are an opt-in phase, so a configuration can be
  validated on a machine without the WiFi adapters attached.
* **Secret-safe.** The report names ``auth_token`` as a path but never prints its value.

Entry point: :func:`validate_config_file`.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type

import yaml
from pydantic import BaseModel, ValidationError

from .config import (
    CAPABILITY_REGISTRY,
    GROUPS_REQUIRING_ONE,
    AppConfig,
    Capability,
    NetworkEntry,
    normalise_capability_id,
)

# The token shipped in config.example.yaml. Left in a real deployment it is a credential
# published in the repository.
EXAMPLE_AUTH_TOKEN = "secret-token-12345"

# Hardcoded floor for min_timeout, independent of what the file requests.
MIN_TIMEOUT_FLOOR = 10

_ORIGIN_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s]+$")
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ==================================================================================================
# ISSUE MODEL
# ==================================================================================================


class Severity(str, Enum):
    ERROR = "error"       # service must not start
    WARNING = "warning"   # service starts, operator should look


@dataclass(frozen=True)
class ValidationIssue:
    """One problem found in the configuration file."""

    path: str                              # e.g. "networks[1].capabilities.5ghz"
    message: str                           # what is wrong
    severity: Severity = Severity.ERROR
    hint: Optional[str] = None             # how to fix it


@dataclass(frozen=True)
class ValidationReport:
    """The outcome of validating one configuration file."""

    config_path: str
    issues: Tuple[ValidationIssue, ...] = ()
    unreadable: bool = False       # file missing / unreadable / unparseable -> CLI exit code 2
    network_count: Optional[int] = None

    @property
    def errors(self) -> Tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> Tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """True when nothing blocks startup. Warnings do not block."""
        return not self.errors

    def render(self) -> str:
        """Human-readable report, used identically by the CLI and by startup.

        Deliberately ASCII-only. This text is printed to a terminal, written to the
        journal and pasted into CI logs; a report that raises UnicodeEncodeError on a
        console with a legacy code page is worse than one without typographic arrows.
        """
        lines: List[str] = []
        if self.ok:
            lines.append("Wi-Lab configuration validation OK")
            lines.append(f"File: {self.config_path}")
            if self.network_count is not None:
                lines.append(
                    f"{self.network_count} network(s), "
                    f"capabilities: {', '.join(Capability.ids())}"
                )
        else:
            lines.append("Wi-Lab configuration validation FAILED")
            lines.append(f"File: {self.config_path}")
            lines.append(
                f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
            )

        if self.issues:
            lines.append("")
            for issue in self.issues:
                lines.append(f"{issue.severity.value.upper():<7} {issue.path}")
                for msg_line in issue.message.splitlines():
                    lines.append(f"        {msg_line}")
                if issue.hint:
                    lines.append(f"        -> {issue.hint}")
                lines.append("")

        if self.ok and self.warnings:
            lines.append(f"{len(self.warnings)} warning(s) - see above")

        return "\n".join(lines).rstrip() + "\n"


# ==================================================================================================
# RULE REGISTRY
# ==================================================================================================


@dataclass(frozen=True)
class ValidationContext:
    """Inputs available to a rule.

    ``raw`` is untyped parsed YAML: a rule must guard every access with ``isinstance``,
    because phase 5 runs even when earlier phases found problems.
    """

    raw: Dict[str, Any]
    config_path: str
    check_hardware: bool


ValidationRule = Callable[[ValidationContext], Iterable[ValidationIssue]]

# (scope, hardware, function). ``scope`` documents the section a rule guards and is used as
# the issue path if the rule itself raises.
_RULES: List[Tuple[str, bool, ValidationRule]] = []


def rule(scope: str, hardware: bool = False) -> Callable[[ValidationRule], ValidationRule]:
    """Register a custom rule for a configuration section.

    Args:
        scope: The section this rule guards, e.g. ``"networks[].capabilities"``.
        hardware: True if the rule touches the machine (interfaces, routes). Hardware rules
            run only when ``check_hardware=True``, which is what lets a configuration be
            validated on a laptop without the adapters attached.
    """

    def decorator(fn: ValidationRule) -> ValidationRule:
        _RULES.append((scope, hardware, fn))
        return fn

    return decorator


# ==================================================================================================
# ENTRY POINT
# ==================================================================================================


def validate_config_file(path: str, *, check_hardware: bool = False) -> ValidationReport:
    """Validate a configuration file.

    Args:
        path: Path to the YAML configuration file.
        check_hardware: Also run the rules that inspect the machine (interfaces exist and
            support AP mode, subnet does not collide with a host route).

    Returns:
        A report listing every problem found. Never raises for a bad configuration; only
        programming errors propagate.
    """
    raw, structural = _load_raw(path)
    if structural is not None:
        return ValidationReport(config_path=path, issues=(structural,), unreadable=True)
    assert raw is not None  # _load_raw returns one or the other

    issues: List[ValidationIssue] = []

    # Phase 2 + 3 — presence and unknown keys.
    issues.extend(_check_presence(raw))
    issues.extend(_check_unknown_keys(raw))

    # Phase 4 — types and ranges, via the Pydantic models.
    # De-duplicated against phases 2/3: a missing key is reported by the presence check *and*
    # by Pydantic as "Field required" at the same location, and reporting every missing key
    # twice would undermine the whole point of the report.
    already_reported = {i.path for i in issues}
    issues.extend(i for i in _check_types(raw) if i.path not in already_reported)

    # Phase 5 + 6 — custom rules. Each is isolated: a rule that raises costs one confusing
    # line, not the entire report, which is the administrator's only diagnostic.
    ctx = ValidationContext(raw=raw, config_path=path, check_hardware=check_hardware)
    for scope, is_hardware, fn in _RULES:
        if is_hardware and not check_hardware:
            continue
        try:
            issues.extend(fn(ctx))
        except Exception as exc:  # pragma: no cover - defensive
            issues.append(ValidationIssue(
                path=scope,
                message=f"Internal validation error in rule '{fn.__name__}': {exc}",
                hint="This is a Wi-Lab bug; the rest of the report is still valid.",
            ))

    issues = _scrub(issues, _secrets(raw))
    networks = raw.get("networks")
    return ValidationReport(
        config_path=path,
        issues=tuple(sorted(issues, key=_sort_key)),
        unreadable=False,
        network_count=len(networks) if isinstance(networks, list) else None,
    )


# ==================================================================================================
# PHASE 1 — STRUCTURAL
# ==================================================================================================


def _load_raw(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[ValidationIssue]]:
    """Read and parse the file. Returns (mapping, None) or (None, blocking issue)."""
    try:
        # utf-8-sig transparently strips a BOM, which Windows editors like to add.
        with open(path, "r", encoding="utf-8-sig") as f:
            parsed = yaml.safe_load(f)
    except FileNotFoundError:
        return None, ValidationIssue(
            path=path,
            message="Configuration file not found.",
            hint="Create it with: cp config.example.yaml config.yaml",
        )
    except OSError as exc:
        return None, ValidationIssue(
            path=path,
            message=f"Cannot read configuration file: {exc}",
        )
    except yaml.YAMLError as exc:
        return None, ValidationIssue(
            path=path,
            message=f"Invalid YAML: {exc}",
            hint="Check indentation and quoting; YAML is whitespace-sensitive.",
        )

    if parsed is None:
        # An empty file is readable and parseable; it is simply missing every key, which the
        # presence phase reports precisely.
        return {}, None
    if not isinstance(parsed, dict):
        return None, ValidationIssue(
            path=path,
            message=f"Top level must be a mapping of settings, got {type(parsed).__name__}.",
        )
    return parsed, None


# ==================================================================================================
# PHASE 2 — PRESENCE
# ==================================================================================================

# Per-key hints for the top-level keys, so a missing key tells the administrator what to write.
_KEY_HINTS: Dict[str, str] = {
    "auth_token": "Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'",
    "api_port": "Add 'api_port: 8080'",
    "max_timeout": "Add 'max_timeout: 86400' (24 h upper bound for reservations)",
    "min_timeout": "Add 'min_timeout: 60' (lower bound for reservations)",
    "allow_unlimited_reservation": "Add 'allow_unlimited_reservation: false'",
    "dhcp_base_network": "Add 'dhcp_base_network: \"192.168.120.0/24\"' (must not overlap your LAN)",
    "upstream_interface": "Add 'upstream_interface: \"auto\"'",
    "country_code": "Add 'country_code: \"IT\"' (ISO 3166-1 alpha-2)",
    "dns_server": "Add 'dns_server: \"208.67.222.222\"'",
    "internet_enabled_by_default": "Add 'internet_enabled_by_default: true'",
    "networks": "Add a 'networks:' list with one entry per managed WiFi interface",
    "cors_origins": "Add 'cors_origins: []' to disable CORS, or list the allowed origins",
}


def _required_keys(model: Type[BaseModel]) -> List[str]:
    """Every declared field is mandatory in the file, regardless of its Python default.

    Derived from the model so that adding a configuration field automatically makes it
    required in the file, with no second list to keep in sync. ``file_optional`` in a
    field's ``json_schema_extra`` is the escape hatch; no v1 field uses it.
    """
    required = []
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("file_optional"):
            continue
        required.append(name)
    return required


def _check_presence(raw: Dict[str, Any]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    for key in _required_keys(AppConfig):
        if key not in raw:
            issues.append(ValidationIssue(
                path=key,
                message="Missing required key.",
                hint=_KEY_HINTS.get(key),
            ))

    networks = raw.get("networks")
    if not isinstance(networks, list):
        return issues

    for idx, entry in enumerate(networks):
        if not isinstance(entry, dict):
            continue  # phase 4 reports the type error
        for key in _required_keys(NetworkEntry):
            if key not in entry:
                hint = None
                if key == "capabilities":
                    hint = f"Add a capabilities block declaring: {', '.join(Capability.ids())}"
                issues.append(ValidationIssue(
                    path=f"networks[{idx}].{key}",
                    message="Missing required key.",
                    hint=hint,
                ))
        caps = entry.get("capabilities")
        if not isinstance(caps, dict):
            continue
        declared = {normalise_capability_id(k) for k in caps}
        for cap in CAPABILITY_REGISTRY:
            if cap.value not in declared:
                issues.append(ValidationIssue(
                    path=f"networks[{idx}].capabilities.{cap.value}",
                    message="Missing required capability key.",
                    hint=(
                        f"Add '\"{cap.value}\": true' or '\"{cap.value}\": false' "
                        f"under networks[{idx}].capabilities"
                    ),
                ))
    return issues


# ==================================================================================================
# PHASE 3 — UNKNOWN KEYS
# ==================================================================================================


def _check_unknown_keys(raw: Dict[str, Any]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    known_top = set(AppConfig.model_fields)
    for key in raw:
        if str(key) not in known_top:
            issues.append(ValidationIssue(
                path=str(key),
                message=f"Unknown configuration key '{key}'.",
                hint=f"Valid keys: {', '.join(sorted(known_top))}",
            ))

    networks = raw.get("networks")
    if not isinstance(networks, list):
        return issues

    known_net = set(NetworkEntry.model_fields)
    valid_caps = Capability.ids()
    for idx, entry in enumerate(networks):
        if not isinstance(entry, dict):
            continue
        for key in entry:
            if str(key) not in known_net:
                issues.append(ValidationIssue(
                    path=f"networks[{idx}].{key}",
                    message=f"Unknown key '{key}' in network entry.",
                    hint=f"Valid keys: {', '.join(sorted(known_net))}",
                ))
        caps = entry.get("capabilities")
        if not isinstance(caps, dict):
            continue
        for key in caps:
            if normalise_capability_id(key) not in valid_caps:
                issues.append(ValidationIssue(
                    path=f"networks[{idx}].capabilities.{key}",
                    message=f"Unknown capability '{key}'.",
                    hint=f"Valid capabilities: {', '.join(valid_caps)}",
                ))
    return issues


# ==================================================================================================
# PHASE 4 — TYPES & RANGES (Pydantic)
# ==================================================================================================


def _loc_to_path(loc: Tuple[Any, ...]) -> str:
    """Render a Pydantic error location as a configuration path."""
    parts: List[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts)


def _check_types(raw: Dict[str, Any]) -> List[ValidationIssue]:
    try:
        AppConfig.model_validate(raw)
        return []
    except ValidationError as exc:
        return [
            ValidationIssue(
                path=_loc_to_path(tuple(err["loc"])),
                message=err["msg"] + ".",
            )
            for err in exc.errors()
        ]


# ==================================================================================================
# PHASE 5 — CUSTOM RULES
# ==================================================================================================
#
# Every rule guards its own inputs: a rule whose key is missing or wrongly typed emits nothing,
# because the presence and type phases have already reported that, and a cascade of derived
# complaints would bury the real problem.


def _get_int(raw: Dict[str, Any], key: str) -> Optional[int]:
    """Return an int-valued key, or None if absent or not an int (bools are not ints here)."""
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _get_str(raw: Dict[str, Any], key: str) -> Optional[str]:
    value = raw.get(key)
    return value if isinstance(value, str) else None


@rule(scope="auth_token")
def check_auth_token(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """The API token must be set, and must not be the one published in the example file."""
    token = _get_str(ctx.raw, "auth_token")
    if token is None:
        return
    if not token.strip():
        yield ValidationIssue(
            path="auth_token",
            message="auth_token is empty; every request would authenticate with an empty token.",
            hint="Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'",
        )
    elif token == EXAMPLE_AUTH_TOKEN:
        yield ValidationIssue(
            path="auth_token",
            message="Still set to the example value from config.example.yaml.",
            severity=Severity.WARNING,
            hint="Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'",
        )


@rule(scope="api_port")
def check_api_port(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    port = _get_int(ctx.raw, "api_port")
    if port is None:
        return
    if not 1 <= port <= 65535:
        yield ValidationIssue(
            path="api_port",
            message=f"api_port ({port}) must be between 1 and 65535.",
            hint="The default is 8080.",
        )
    elif port < 1024:
        yield ValidationIssue(
            path="api_port",
            message=f"api_port ({port}) is a privileged port.",
            severity=Severity.WARNING,
            hint="Binding below 1024 requires root or CAP_NET_BIND_SERVICE.",
        )


@rule(scope="min_timeout")
def check_timeouts(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Reservation bounds must be usable: above the floor, positive, and min <= max."""
    min_timeout = _get_int(ctx.raw, "min_timeout")
    max_timeout = _get_int(ctx.raw, "max_timeout")

    if min_timeout is not None and min_timeout < MIN_TIMEOUT_FLOOR:
        yield ValidationIssue(
            path="min_timeout",
            message=(
                f"min_timeout ({min_timeout}) must be at least {MIN_TIMEOUT_FLOOR} seconds "
                "(hardcoded floor)."
            ),
            hint=f"Raise it to at least {MIN_TIMEOUT_FLOOR}; shorter reservations are rejected "
                 "by the API anyway.",
        )
    if max_timeout is not None and max_timeout <= 0:
        yield ValidationIssue(
            path="max_timeout",
            message=f"max_timeout ({max_timeout}) must be positive.",
            hint="This is the upper bound for a reservation, in seconds (86400 = 24 h).",
        )
    if (
        min_timeout is not None
        and max_timeout is not None
        and max_timeout > 0
        and min_timeout > max_timeout
    ):
        yield ValidationIssue(
            path="min_timeout",
            message=f"min_timeout ({min_timeout}) must not be greater than max_timeout ({max_timeout}).",
            hint="Every reservation request would be rejected as both too short and too long.",
        )


@rule(scope="dhcp_base_network")
def check_dhcp_base_network(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Must be a /24, and wide enough for the declared number of devices."""
    value = _get_str(ctx.raw, "dhcp_base_network")
    if value is None:
        return
    try:
        net = ipaddress.IPv4Network(value, strict=False)
    except ValueError as exc:
        yield ValidationIssue(
            path="dhcp_base_network",
            message=f"Invalid IPv4 network: {exc}.",
            hint="Use CIDR notation with a /24 prefix, e.g. \"192.168.120.0/24\"",
        )
        return
    if net.prefixlen != 24:
        yield ValidationIssue(
            path="dhcp_base_network",
            message=f"dhcp_base_network must be a /24 network, got /{net.prefixlen}.",
            hint="Wi-Lab assigns one sequential /24 per managed device.",
        )
        return

    networks = ctx.raw.get("networks")
    if not isinstance(networks, list) or not networks:
        return
    base_third = int(str(net.network_address).split(".")[2])
    max_third = base_third + len(networks) - 1
    if max_third > 255:
        yield ValidationIssue(
            path="dhcp_base_network",
            message=(
                f"Too many networks ({len(networks)}) for {value}: the third octet would "
                f"overflow (would reach {max_third})."
            ),
            hint="Lower the third octet of dhcp_base_network, or manage fewer devices.",
        )


@rule(scope="dns_server")
def check_dns_server(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    value = _get_str(ctx.raw, "dns_server")
    if value is None:
        return
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        yield ValidationIssue(
            path="dns_server",
            message=f"'{value}' is not a valid IPv4 address.",
            hint="Use a plain address, e.g. \"208.67.222.222\" or your gateway.",
        )


@rule(scope="country_code")
def check_country_code(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    value = _get_str(ctx.raw, "country_code")
    if value is None:
        return
    if not _COUNTRY_CODE_RE.match(value):
        yield ValidationIssue(
            path="country_code",
            message=f"'{value}' is not an uppercase ISO 3166-1 alpha-2 country code.",
            hint="Two uppercase letters, e.g. \"IT\", \"US\", \"DE\". This drives the WiFi "
                 "regulatory domain.",
        )


@rule(scope="upstream_interface")
def check_upstream_interface(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    value = _get_str(ctx.raw, "upstream_interface")
    if value is None:
        return
    if not value.strip():
        yield ValidationIssue(
            path="upstream_interface",
            message="upstream_interface must be 'auto' or a non-empty device name.",
            hint="'auto' detects the interface holding the default route.",
        )


@rule(scope="cors_origins")
def check_cors_origins(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Entries must look like origins; a non-empty list means CORS is on."""
    value = ctx.raw.get("cors_origins")
    if value is None or not isinstance(value, list):
        return
    for i, origin in enumerate(value):
        if not isinstance(origin, str) or not _ORIGIN_RE.match(origin):
            yield ValidationIssue(
                path=f"cors_origins[{i}]",
                message=f"'{origin}' is not a valid origin.",
                hint="Use scheme://host[:port] with no trailing path, e.g. \"http://localhost:4200\"",
            )
    if value:
        yield ValidationIssue(
            path="cors_origins",
            message=f"CORS is enabled for {len(value)} origin(s).",
            severity=Severity.WARNING,
            hint="Fine for development; use an empty list in production.",
        )


@rule(scope="networks")
def check_networks_list(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """At least one device, with unique interfaces."""
    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return
    if not networks:
        yield ValidationIssue(
            path="networks",
            message="No managed devices declared.",
            hint="Wi-Lab needs at least one WiFi interface; list them with: iw dev",
        )
        return

    seen: Dict[str, int] = {}
    for idx, entry in enumerate(networks):
        if not isinstance(entry, dict):
            continue
        iface = entry.get("interface")
        if not isinstance(iface, str):
            continue
        if iface in seen:
            yield ValidationIssue(
                path=f"networks[{idx}].interface",
                message=f"Duplicate interface '{iface}' (already declared at networks[{seen[iface]}]).",
                hint="Each physical interface can be managed only once.",
            )
        else:
            seen[iface] = idx


@rule(scope="networks[].display_name")
def check_display_names(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Labels must be present and, ideally, distinguishable in the UI."""
    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return

    seen: Dict[str, int] = {}
    for idx, entry in enumerate(networks):
        if not isinstance(entry, dict):
            continue
        name = entry.get("display_name")
        if not isinstance(name, str):
            continue
        if not name.strip():
            yield ValidationIssue(
                path=f"networks[{idx}].display_name",
                message="display_name is empty.",
                hint="This is the label shown on the device card in the web UI.",
            )
            continue
        if name in seen:
            yield ValidationIssue(
                path=f"networks[{idx}].display_name",
                message=(
                    f"Duplicate display_name '{name}' (also at networks[{seen[name]}])."
                ),
                severity=Severity.WARNING,
                hint="Two cards with the same label are indistinguishable to the user.",
            )
        else:
            seen[name] = idx


@rule(scope="networks[].capabilities")
def check_duplicate_capability_ids(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """'5ghz' and '5GHz' in the same map are the same key declared twice."""
    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return
    for idx, entry in enumerate(networks):
        caps = entry.get("capabilities") if isinstance(entry, dict) else None
        if not isinstance(caps, dict):
            continue
        seen: Dict[str, Any] = {}
        for key in caps:
            canonical = normalise_capability_id(key)
            if canonical in seen:
                yield ValidationIssue(
                    path=f"networks[{idx}].capabilities.{key}",
                    message=(
                        f"Capability '{canonical}' is declared twice "
                        f"(as '{seen[canonical]}' and '{key}')."
                    ),
                    hint="Capability ids are case-insensitive; keep one declaration.",
                )
            else:
                seen[canonical] = key


@rule(scope="networks[].capabilities")
def at_least_one_enabled_per_group(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Every device must enable at least one capability of each required group.

    Parameterised by the registry's ``group`` metadata rather than hardcoding the band ids,
    so a future policy capability (``group=None``) is exempt automatically: a device that
    forbids SSID changes is still perfectly usable.
    """
    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return
    for idx, entry in enumerate(networks):
        caps = entry.get("capabilities") if isinstance(entry, dict) else None
        if not isinstance(caps, dict):
            continue
        canonical = {normalise_capability_id(k): v for k, v in caps.items()}
        for group in sorted(GROUPS_REQUIRING_ONE):
            members = [c for c, d in CAPABILITY_REGISTRY.items() if d.group == group]
            if not members:
                continue
            # `is True` and not a truthy test: a YAML string such as "yes" must not be
            # mistaken for an enabled band. Phase 4 reports the type error separately.
            if not any(canonical.get(c.value) is True for c in members):
                yield ValidationIssue(
                    path=f"networks[{idx}].capabilities",
                    message=(
                        f"At least one capability of group '{group}' must be enabled "
                        f"({', '.join(c.value for c in members)}); all are false."
                    ),
                    hint="A device with no usable band can never host an access point.",
                )


# ==================================================================================================
# PHASE 6 — HARDWARE (opt-in)
# ==================================================================================================


@rule(scope="networks[].interface", hardware=True)
def check_interfaces_exist(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Each managed interface must exist, be wireless, and support AP mode."""
    # Imported here, not at module level: the test suite neutralises this helper with
    # monkeypatch.setattr on the wilab.wifi.interface module, and a module-level import
    # would capture the original function and silently defeat the patch.
    from .wifi.interface import InterfaceError, validate_interface

    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return
    for idx, entry in enumerate(networks):
        iface = entry.get("interface") if isinstance(entry, dict) else None
        if not isinstance(iface, str) or not iface:
            continue
        try:
            validate_interface(iface)
        except InterfaceError as exc:
            yield ValidationIssue(
                path=f"networks[{idx}].interface",
                message=str(exc) + ".",
                hint="List available interfaces with: iw dev",
            )


@rule(scope="upstream_interface", hardware=True)
def check_upstream_interface_exists(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """When pinned to a name, the upstream interface must exist."""
    from .network.commands import CommandError, execute_command

    value = _get_str(ctx.raw, "upstream_interface")
    if value is None or value == "auto" or not value.strip():
        return
    try:
        execute_command(["ip", "link", "show", value])
    except CommandError:
        yield ValidationIssue(
            path="upstream_interface",
            message=f"Upstream interface '{value}' does not exist on this host.",
            hint="Use \"auto\" to detect the interface holding the default route.",
        )


@rule(scope="dhcp_base_network", hardware=True)
def check_dhcp_network_collision(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """The WiFi subnets must not overlap a subnet the host already routes.

    A collision silently breaks host networking and can lock the operator out over SSH,
    which config.example.yaml warns about but nothing has ever verified.
    """
    from .network.commands import CommandError, execute_command

    value = _get_str(ctx.raw, "dhcp_base_network")
    networks = ctx.raw.get("networks")
    if value is None or not isinstance(networks, list) or not networks:
        return
    try:
        base = ipaddress.IPv4Network(value, strict=False)
    except ValueError:
        return  # the static rule already reported it
    if base.prefixlen != 24:
        return

    try:
        route_output = execute_command(["ip", "route"])
    except CommandError:
        return  # cannot tell; not a configuration error

    planned: List[ipaddress.IPv4Network] = []
    base_third = int(str(base.network_address).split(".")[2])
    octets = str(base.network_address).split(".")
    for i in range(len(networks)):
        if base_third + i > 255:
            break
        planned.append(ipaddress.IPv4Network(
            f"{octets[0]}.{octets[1]}.{base_third + i}.0/24"
        ))

    for line in route_output.splitlines():
        token = line.split()[0] if line.split() else ""
        if "/" not in token:
            continue
        try:
            existing = ipaddress.IPv4Network(token, strict=False)
        except ValueError:
            continue
        for subnet in planned:
            if subnet.overlaps(existing):
                yield ValidationIssue(
                    path="dhcp_base_network",
                    message=(
                        f"Planned WiFi subnet {subnet} overlaps the existing host route "
                        f"{existing}."
                    ),
                    hint="A collision breaks host networking and can drop your SSH session. "
                         "Pick a range your host does not route.",
                )
                return


# ==================================================================================================
# REPORT ASSEMBLY
# ==================================================================================================


def _secrets(raw: Dict[str, Any]) -> List[str]:
    """Values that must never appear in a rendered report."""
    values = []
    token = raw.get("auth_token")
    if isinstance(token, str) and token.strip():
        values.append(token)
    return values


def _scrub(issues: List[ValidationIssue], secrets: List[str]) -> List[ValidationIssue]:
    """Redact secret values from issue text.

    Scrubbing the issues rather than the rendered string keeps them safe wherever they go:
    logs, the journal, a CI transcript, or a future JSON output.
    """
    if not secrets:
        return issues
    scrubbed = []
    for issue in issues:
        message, hint = issue.message, issue.hint
        for secret in secrets:
            message = message.replace(secret, "***")
            if hint:
                hint = hint.replace(secret, "***")
        scrubbed.append(replace(issue, message=message, hint=hint))
    return scrubbed


_TOP_ORDER = {name: i for i, name in enumerate(AppConfig.model_fields)}
_NET_ORDER = {name: i for i, name in enumerate(NetworkEntry.model_fields)}
_CAP_ORDER = {cap.value: i for i, cap in enumerate(CAPABILITY_REGISTRY)}

_NET_PATH_RE = re.compile(r"^networks\[(\d+)\](?:\.(.+))?$")
_INDEXED_TOP_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]$")


def _sort_key(issue: ValidationIssue) -> Tuple[int, int, int, int, int, str]:
    """Order issues by position in the schema, so the report reads like the file.

    Capability ids contain dots ("2.4ghz"), so paths are matched structurally rather than
    split on ".".
    """
    path = issue.path

    match = _NET_PATH_RE.match(path)
    if match:
        net_index = int(match.group(1))
        remainder = match.group(2)
        if remainder is None:
            return (1, _TOP_ORDER["networks"], net_index, -1, -1, path)
        if remainder == "capabilities" or remainder.startswith("capabilities."):
            field_rank = _NET_ORDER.get("capabilities", 99)
            cap_id = remainder[len("capabilities."):] if "." in remainder else ""
            cap_rank = _CAP_ORDER.get(normalise_capability_id(cap_id), 99) if cap_id else -1
            return (1, _TOP_ORDER["networks"], net_index, field_rank, cap_rank, path)
        return (1, _TOP_ORDER["networks"], net_index, _NET_ORDER.get(remainder, 99), -1, path)

    match = _INDEXED_TOP_RE.match(path)
    if match and match.group(1) in _TOP_ORDER:
        return (1, _TOP_ORDER[match.group(1)], int(match.group(2)), -1, -1, path)

    if path in _TOP_ORDER:
        return (1, _TOP_ORDER[path], -1, -1, -1, path)

    # Structural issues (keyed by file path) and unknown keys sort first.
    return (0, 0, -1, -1, -1, path)
