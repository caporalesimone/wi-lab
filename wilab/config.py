import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set

import yaml
from pydantic import BaseModel, Field, StrictBool, ValidationError, field_validator

logger = logging.getLogger(__name__)


# ==================================================================================================
# DEVICE CAPABILITIES
# ==================================================================================================
#
# A capability is a named property of a managed device, DECLARED by the lab administrator in
# config.yaml. It is never inferred from the hardware: capabilities are administrative statements
# ("this antenna may be used for 5 GHz"), not measurements, and future capabilities such as
# "change-ssid" or "max-clients" have no hardware counterpart at all.
#
# See TODOs/device-capabilities.md §2.1 and §4.2.


class Capability(str, Enum):
    """Canonical capability identifiers.

    The values deliberately match the ``band`` vocabulary already accepted by
    ``NetworkCreateRequest`` (``2.4ghz`` / ``5ghz``), so configuration, the reservation
    API and AP creation all speak one language with no translation table.
    """

    BAND_24GHZ = "2.4ghz"
    BAND_5GHZ = "5ghz"

    @classmethod
    def ids(cls) -> List[str]:
        """All canonical capability ids, in registry order."""
        return [c.value for c in cls]


class CapabilityKind(str, Enum):
    """What sort of statement a capability makes."""

    RADIO = "radio"     # what the device may transmit
    POLICY = "policy"   # what the administrator allows to be changed


class CapabilityType(str, Enum):
    """Value domain of a capability. v1 implements BOOLEAN only."""

    BOOLEAN = "boolean"
    INTEGER = "integer"   # reserved for future quantitative capabilities (e.g. max-clients)


@dataclass(frozen=True)
class CapabilityDef:
    """Metadata for one capability.

    Attributes:
        id: Canonical identifier.
        label: Human-readable label, served in the ``/status`` catalogue.
        kind: Grouping used by the frontend picker.
        type: Value domain. Only ``BOOLEAN`` is implemented in v1.
        group: Optional group name. Groups listed in ``GROUPS_REQUIRING_ONE`` must have at
            least one enabled member per device.
        matchable: Whether the capability participates in reservation matching. Reserved:
            v1 requires every capability to be matchable.
    """

    id: "Capability"
    label: str
    kind: CapabilityKind
    type: CapabilityType = CapabilityType.BOOLEAN
    group: Optional[str] = None
    matchable: bool = True


CAPABILITY_REGISTRY: Dict[Capability, CapabilityDef] = {
    Capability.BAND_24GHZ: CapabilityDef(
        id=Capability.BAND_24GHZ,
        label="2.4 GHz",
        kind=CapabilityKind.RADIO,
        group="band",
    ),
    Capability.BAND_5GHZ: CapabilityDef(
        id=Capability.BAND_5GHZ,
        label="5 GHz",
        kind=CapabilityKind.RADIO,
        group="band",
    ),
}

# Groups where at least one member must be enabled on every device.
# A device with neither 2.4 GHz nor 5 GHz could never host an AP.
GROUPS_REQUIRING_ONE: FrozenSet[str] = frozenset({"band"})


# v1 guard: the selection algorithm implements boolean capabilities only and performs no
# matchability filtering. Registering anything else must fail at import time rather than
# silently mis-allocate devices at runtime. A plain `assert` would be stripped under
# `python -O`, so this is an explicit raise.
_unsupported = [
    d.id.value
    for d in CAPABILITY_REGISTRY.values()
    if d.type is not CapabilityType.BOOLEAN or not d.matchable
]
if _unsupported:
    raise RuntimeError(
        "v1 supports only boolean, matchable capabilities; unsupported: "
        f"{', '.join(_unsupported)}. See TODOs/device-capabilities.md §3.1 before adding one."
    )
del _unsupported


def normalise_capability_id(raw: object) -> str:
    """Canonical form of a capability id.

    Shared deliberately by the configuration validator and the reservation API request
    validator: two independent ``.strip().lower()`` calls would eventually drift and the
    file and the wire would disagree on ``"5GHz"``.
    """
    return str(raw).strip().lower()


# ==================================================================================================
# CONFIGURATION MODELS
# ==================================================================================================
#
# These models are typed containers. Semantic rules (ranges, cross-field constraints, required
# keys) live in wilab/config_validation.py so that every problem is reported through one
# formatter, in one pass. See TODOs/device-capabilities.md §4.3 and §5.6.


class NetworkEntry(BaseModel):
    interface: str
    display_name: str
    # StrictBool, not bool: Pydantic would otherwise coerce a YAML string such as "yes" to
    # True, while the validator's group rule (which compares with `is True`) would read it as
    # disabled. Strictness keeps the model and the rule set from disagreeing about a value
    # that decides whether a device can host an AP.
    capabilities: Dict[str, StrictBool]

    @field_validator("capabilities")
    @classmethod
    def _canonicalise_keys(cls, v: Dict[str, bool]) -> Dict[str, bool]:
        """Mechanical key canonicalisation only — no semantic validation here.

        The configuration validator has already rejected unknown and duplicate ids by the
        time a model is built; this keeps ``capabilities`` canonically keyed so that
        ``capability_set`` can rely on it.
        """
        return {normalise_capability_id(k): val for k, val in v.items()}

    @property
    def device_id(self) -> str:
        """Stable internal identifier derived from interface name."""
        return self.interface

    @property
    def capability_set(self) -> Set[Capability]:
        """Enabled capabilities as a set (boolean capabilities only)."""
        return {Capability(k) for k, v in self.capabilities.items() if v}


class AppConfig(BaseModel):
    auth_token: str
    api_port: int = 8080
    max_timeout: int = 86400   # 24 hours default upper bound
    min_timeout: int = 60      # 60 seconds default lower bound
    allow_unlimited_reservation: bool = False
    dhcp_base_network: str
    upstream_interface: str = "auto"
    country_code: str = "IT"
    dns_server: str = "192.168.10.21"
    internet_enabled_by_default: bool = True
    networks: List[NetworkEntry]
    cors_origins: Optional[List[str]] = Field(
        default=None,
        description="CORS allowed origins. An empty list (or null) disables CORS, which is the "
                    "secure choice for production. For development, add frontend URLs like "
                    "['http://localhost:4200', 'http://192.168.1.100:4200']"
    )

    def capabilities_for(self, device_id: str) -> List[str]:
        """Sorted enabled capability ids for a device ([] if the device is unknown).

        Lives here rather than in a route module so that both the reservation and the status
        routes can use it without importing from each other.
        """
        for n in self.networks:
            if n.device_id == device_id:
                return sorted(c.value for c in n.capability_set)
        return []


def load_config(path: Optional[str] = None) -> AppConfig:
    """Validate and load the configuration file.

    Validation is the single enforcement point: an invalid configuration raises SystemExit
    carrying the full report, so no code path can start the service against a bad config.
    """
    cfg_path = path or os.environ.get('CONFIG_PATH') or os.path.join(os.getcwd(), 'config.yaml')

    # Imported lazily: config_validation imports the models and registry from this module, so a
    # top-level import here would be circular. Mirrors the deferred import style already used
    # for the hardware helpers.
    from .config_validation import validate_config_file

    report = validate_config_file(cfg_path, check_hardware=True)
    if report.warnings:
        logger.warning("Configuration warnings:\n%s", report.render())
    if not report.ok:
        raise SystemExit(report.render())

    try:
        with open(cfg_path, 'r', encoding='utf-8-sig') as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig(**raw)
    except ValidationError as e:
        # Defence in depth: the validator already passed, so a failure here means the models
        # and the rule set disagree. Surface it loudly rather than crashing obscurely later.
        msgs = [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        raise SystemExit(
            "Configuration passed validation but failed model construction (this is a bug):\n"
            + "\n".join(msgs)
        )
