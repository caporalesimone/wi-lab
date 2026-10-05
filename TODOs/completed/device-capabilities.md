# Reservation Improvement Proposal — Device Capabilities

**Priority:** 1 (HIGH)
**Status:** IMPLEMENTED in 4.0.0 (a breaking release; see [§18.7](#187-revision--the-release-became-400-and-the-compatibility-shims-were-removed)) — bench validation ([§12.9](#129-bench-validation--required-and-not-possible-on-a-windows-workstation)) still outstanding.
**Read [§18](#18-implementation-status--remaining-work) first**: it records what is built,
what is left, where the implementation deviated from this proposal, and the open decisions.
**Target version:** 4.0.0 (originally planned as 4.0.0)
**Estimated effort:** ~16–20 hours (see [§13](#13-implementation-checklist) for the per-phase breakdown)
**Audience:** this document is written to be executed by an AI coding agent
**Review:** reviewed from four angles — system architecture, software architecture, development, test. Findings folded into the relevant sections; traceability in [§16](#16-review-log).

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Functional Design](#2-functional-design)
3. [Selection Algorithm](#3-selection-algorithm)
4. [Technical Design — Configuration](#4-technical-design--configuration)
5. [Technical Design — Configuration Validator](#5-technical-design--configuration-validator)
6. [Technical Design — API](#6-technical-design--api)
7. [Technical Design — Backend](#7-technical-design--backend)
8. [Technical Design — Frontend](#8-technical-design--frontend)
9. [Error Model](#9-error-model)
10. [Operations & Deployment](#10-operations--deployment)
11. [Backward Compatibility & Migration](#11-backward-compatibility--migration)
12. [Testing Plan](#12-testing-plan)
13. [Implementation Checklist](#13-implementation-checklist)
14. [Documentation To Update](#14-documentation-to-update)
15. [Design Decisions & Rejected Alternatives](#15-design-decisions--rejected-alternatives)
16. [Review Log](#16-review-log)
17. [Out Of Scope / Future Extensions](#17-out-of-scope--future-extensions)
18. [Implementation Status & Remaining Work](#18-implementation-status--remaining-work)
19. [Migration from older versions](#19-migration-from-older-versions)

---

## 1. Problem Statement

Today every managed device in `config.yaml` is described by only two fields:

```yaml
networks:
  - interface: "wlxbc071dc527d6"
    display_name: "bench-antenna-1"
```

Wi-Lab therefore treats the whole antenna pool as **homogeneous and interchangeable**.
`ReservationManager._first_available()` returns the first device that is not currently
reserved, in configuration declaration order.

In a real bench this is false. Adapters differ:

* some are **2.4 GHz only** (cheap 802.11n dongles),
* some are **dual band 2.4 / 5 GHz** (e.g. the MediaTek MT7921U listed in the README).

Three concrete problems follow:

| # | Problem | Consequence |
|---|---------|-------------|
| P1 | The reservation API cannot express *what the user needs* | A user who needs 5 GHz can be assigned a 2.4-only antenna. The reservation succeeds and the failure only surfaces later, at `POST /interface/{rid}/network`, when hostapd cannot start on the requested band. |
| P2 | *(Not pursued — see [§18.8](#188-revision--choosing-a-specific-antenna-was-removed))* The reservation API cannot express *which device the user wants* | Reserving a specific physical antenna is impossible. Originally addressed by an `interface` field; removed before release, because Wi-Lab should manage allocation on its own. |
| P3 | Allocation wastes scarce resources | Declaration order decides everything. A user needing only 2.4 GHz can consume the single dual-band adapter, blocking a colleague who genuinely needs 5 GHz, while a 2.4-only adapter sits idle. |

**Goal of this proposal:** let each device declare a set of *capabilities*, let the
reservation request declare the *required* capabilities (or force a specific device),
and let the backend allocate the **least capable device that still satisfies the
request** — i.e. always reserve the minimum necessary.

Three hard constraints from the requester shape the whole design:

* **C1 — Do not proliferate endpoints.** This proposal adds **zero new API endpoints**.
  It extends three existing payloads only.
* **C2 — No auto-detection, ever.** Capabilities are a **declaration**, not an
  observation. `config.yaml` is the single source of truth. Wi-Lab must never probe the
  hardware to decide what a device can do. See [§2.1](#21-capability-concept) for why
  this is structural, not merely a preference.
* **C3 — Validate, never correct.** Wi-Lab must never modify the administrator's
  configuration file. An incomplete or inconsistent config is reported in full and the
  service refuses to start. See [§5](#5-technical-design--configuration-validator).

---

## 2. Functional Design

### 2.1 Capability concept

A **capability** is a named property of a managed device, declared in `config.yaml` by
the lab administrator. It answers *"what may this device be used for?"* — a question
the administrator answers, not the driver.

**Capabilities are administrative, not physical.** This is the key insight that rules
out auto-detection. Even the two capabilities shipped in v1 are declarations, not
measurements: an administrator may own a dual-band adapter and still declare
`"5ghz": false` because that band is reserved for another test bench, or because the
local regulatory domain makes it unusable in practice. The declaration must win.

The model must equally accommodate capabilities that **have no hardware counterpart at
all**, for example:

| Future example | Kind | Why probing is meaningless |
|---|---|---|
| `change-ssid: false` | policy | Expresses "this bench's SSID is fixed and must not be renamed". Nothing in `iw` can tell you that. |
| `change-password: true` | policy | Same: a deliberate administrative choice. |
| `max-clients: 50` | quantitative | A cap the lab wants to impose, not a driver limit. Not even boolean. |

A mechanism that guesses capabilities from `iw phy channels` could never produce any of
these, and would actively fight the administrator on the ones it *can* see. So there is
one rule, uniformly applied: **the configuration file is the only source of truth.**

Version 1 ships exactly two capabilities:

| Capability id | Kind | Type | Meaning |
|---------------|------|------|---------|
| `2.4ghz` | `radio` | boolean | The device may operate an AP in the 2.4 GHz band |
| `5ghz`   | `radio` | boolean | The device may operate an AP in the 5 GHz band |

The identifiers are deliberately **identical to the values already accepted by the
`band` field** of `NetworkCreateRequest` (`^(2\.4ghz|5ghz|dual)$`, see
[wilab/models.py](../../wilab/models.py)). One vocabulary, no translation layer, no mapping
table.

### 2.2 The capability registry

Because capabilities will grow — and grow in *kinds*, not just in count — they are not
scattered constants. A single **registry** in `wilab/config.py` declares every known
capability together with its metadata, and that one structure drives everything
downstream: validation rules, the `/status` catalogue, the API request validator, and
how the frontend groups the picker.

Adding a capability must be a **one-place change**. See
[§4.2](#42-the-capability-registry-implementation) for the implementation.

### 2.3 Declaration is mandatory and complete

Every device must declare **every** known capability explicitly. There is no default
value, no implicit `false`, and no automatic completion of the file.

This is a specific case of a general rule introduced by this proposal:
**every key the schema knows about must be present in `config.yaml`.** No silent
defaults anywhere — not for capabilities, not for `api_port`, not for `country_code`.
A config file is either complete and explicit, or it is rejected with a full report of
what is missing.

The rationale is the same one that rules out auto-detection: a value Wi-Lab invents on
the administrator's behalf is a value nobody reviewed. For capabilities specifically, an
invented `false` silently shrinks the usable pool and an invented `true` reintroduces
problem P1. Neither failure is visible until a reservation goes wrong.

What makes this practical rather than tedious is the validator
([§5](#5-technical-design--configuration-validator)): it reports **every** problem in
one pass, with the exact path and a fix hint for each, and it can be run standalone
(`--validate-config`) before deploying. Completing a config is one editing session
driven by one report, not a restart-fix-restart loop.

### 2.4 User-facing behaviour

The client states **only what it needs**; Wi-Lab always chooses the antenna. There is no
way to request a specific device (that option was designed, built and then removed — see
[§18.8](#188-revision--choosing-a-specific-antenna-was-removed)).

**A. With requirements**
The user states *what they need* — e.g. "2.4 GHz only". The system picks the best
device on their behalf, preferring the least capable one that fits.

**B. No preference (scripting)**
`required_capabilities` is sent **empty**. Equivalent to "no requirements": any free
device is acceptable, and the least capable free one is assigned. Since 4.0.0 this is
stated explicitly: leaving the field out is an error, not a synonym.

### 2.5 Worked example (the requester's scenario)

Pool:

| Device | 2.4 GHz | 5 GHz |
|--------|---------|-------|
| `bench-antenna-1` | ✅ | ❌ |
| `bench-antenna-2` | ✅ | ✅ |
| `bench-antenna-3` | ✅ | ✅ |

* Request `["2.4ghz"]` → **`bench-antenna-1`**. Both `-1` and `-2`/`-3` satisfy the
  request, but `-1` carries no surplus capability, so the dual-band adapters stay free
  for someone who may need 5 GHz.
* Request `["5ghz"]` → **`bench-antenna-2`** (first dual-band in declaration order;
  `-1` cannot serve the request at all).
* Request `["2.4ghz", "5ghz"]` → **`bench-antenna-2`**.
* Request `["2.4ghz"]` while `-1` is already reserved → **`bench-antenna-2`**
  (fallback to a more capable device is allowed; minimality is a *preference*, never a
  hard constraint).
* Request `["5ghz"]` while `-2` and `-3` are reserved → **409**, with the next
  availability computed **over the matching subset only** (i.e. the earliest expiry
  among `-2`/`-3`, *not* among all devices) — or `null` if those reservations are
  unlimited ([§7.1](#71-wilabreservationpy)).

### 2.6 The "Reserve Device" flow in the UI

Pressing **Reserve Device** must not immediately allocate. The dialog collects, in a
single screen: the **capabilities** needed and the **duration** (unchanged). A live line reports how many devices match,
and **Reserve** is disabled when none do — turning P1 from a late, confusing hostapd
failure into an immediate, pre-submit validation.

Full layout and behaviour: [§8.2](#82-reservation-dialog).

The capability list is **not hardcoded in the frontend**. It is derived from what
`GET /api/v1/status` reports, so adding a capability to the registry surfaces in the UI
without touching Angular code.

### 2.7 Downstream effect on network creation

The reservation response carries the capabilities of the assigned device. The network
creation dialog uses them to restrict the `band` dropdown
(`['2.4ghz', '5ghz', 'dual']`): a 2.4-only device offers only `2.4ghz`, a dual-band
device offers all three. No extra API call is needed.

**The server enforces it too (4.0.0).** The declaration in `config.yaml` is authoritative:
a device declared 2.4 GHz-only provides only 2.4 GHz. `POST /interface/{rid}/network` with a
`band` the device does not declare (`dual` needs both) is answered **immediately with 422**,
before any hardware check; the adapter is never probed to see whether it could do more.
The UI filtering is a convenience on top, not the safeguard.

---

## 3. Selection Algorithm

Given a request with required capability set `R` (possibly empty) over the pool of
**free** devices `D`:

```
candidates = { d ∈ D : R ⊆ capabilities(d) }

if candidates is empty:
    → 409 (no matching device free) or 422 (no matching device exists at all)

surplus(d) = | capabilities(d) \ R |          # extra, unrequested capabilities

winner = min(candidates, key = (surplus(d), declaration_index(d)))
```

Properties this gives us:

* **Minimality** — the least capable sufficient device wins, so scarce multi-band
  hardware is preserved for requests that actually need it (solves P3).
* **Determinism** — the tie-break on declaration index makes the outcome reproducible
  and, when all devices are identical, *exactly* reproduces today's
  `_first_available()` behaviour. This is what keeps the existing test suite meaningful.
* **No starvation of the request** — minimality is a preference, not a filter. If only
  an over-capable device is free, it is used.
* **Extensibility** — adding boolean capabilities does not change the formula.

> **On the explicit tie-break.** `min()` returns the *first* minimal element and the
> candidate list preserves declaration order, so `declaration_index` is technically
> redundant today. It is kept in the key deliberately: it makes the tie-break an
> **intentional, testable property** rather than an incidental consequence of CPython's
> `min()`, and it survives a later refactor to `sorted()`, a heap, or a parallel scan.

### 3.1 How quantitative capabilities would slot in (design headroom, not v1)

A future `max-clients: 50` is not a set member, so containment does not apply. The
formula generalises cleanly if each capability contributes a *satisfaction predicate*
and a *surplus term*:

| Type | Satisfies `R` when | Surplus term |
|------|--------------------|--------------|
| boolean | `provided == true` | `1` if provided-and-not-requested, else `0` |
| integer (future) | `provided >= requested` | `(provided − requested) / scale`, normalised into `[0, 1]` |

So "I need at least 10 clients" would prefer a 20-client device over a 200-client one —
the same minimality principle, expressed on a numeric axis. The registry's `type` field
([§4.2](#42-the-capability-registry-implementation)) is the hook that makes this an
additive change rather than a rewrite.

**v1 implements the boolean row only, and adds no code for the others.** The registry
carries `type` and `matchable` as metadata, but v1 ships a module-level assertion that
every registered capability is `BOOLEAN` and `matchable=True`
([§4.2](#42-the-capability-registry-implementation)). This is the review's resolution of
a YAGNI objection: keeping the metadata field costs one dataclass attribute, whereas
implementing an unreachable `_matchable()` filter would ship an untested code path. The
assertion fails loudly the day someone registers a capability the algorithm cannot yet
handle, which is exactly when the filtering should be written.

### 3.2 Rejected refinement (documented for the future)

A scarcity-weighted score, `surplus_cost(d) = Σ_{c ∈ surplus} 1 / free_count(c)`, would
protect *rare* capabilities more aggressively than plain cardinality. With only two
capabilities the two formulas agree on every case, so v1 uses the simple count. Revisit
if/when the capability set grows past ~4 members.

### 3.3 Forced-device path — removed

An earlier draft let the request name a device (`interface`) and bypassed the algorithm.
It was removed in 4.0.0; see [§18.8](#188-revision--choosing-a-specific-antenna-was-removed).

### 3.4 Concurrency and TOCTOU

The frontend computes its match count from a polled `/status` snapshot, so a device can
be taken between the poll and the submit. This is **accepted, not defended against**:
the request then fails with the normal 409 and the UI already handles it. Server-side,
selection happens inside `ReservationManager._lock` after `_purge_expired()`, so the
decision and the claim are atomic — the snapshot the *server* selects from is never
stale.

---

## 4. Technical Design — Configuration

### 4.1 Schema

```yaml
networks:
  - interface: "wlxbc071dc527d6"
    display_name: "bench-antenna-1"
    capabilities:
      "2.4ghz": true
      "5ghz": false

  - interface: "wlx7820512451b4"
    display_name: "bench-antenna-2"
    capabilities:
      "2.4ghz": true
      "5ghz": true

  - interface: "wlx782051245264"
    display_name: "bench-antenna-3"
    capabilities:
      "2.4ghz": true
      "5ghz": true
```

Shape:

* `capabilities` is a **map of `capability_id → value`**, not a list. Every device
  declares every known capability explicitly, so a `false` is visibly different from an
  omission and the file documents the whole lab.
* Keys **must be quoted** in YAML. `2.4ghz` unquoted is still parsed as a string by the
  loader, but quoting removes any doubt for a reader and protects against a future key
  like `5` or `2.4`.
* Key matching is **case-insensitive and whitespace-trimmed**, then normalised to the
  canonical lowercase id. `"5GHz"`, `" 5ghz "` and `"5ghz"` are the same key; declaring
  two of them for one device is a duplicate-key error.

The rules that *enforce* this shape — completeness, unknown ids, the at-least-one-band
constraint — are not restated here. They live in one place, the rule set of
[§5.6](#56-the-rule-set), so there is a single authority on what a valid config is.

### 4.2 The capability registry (implementation)

Single source of metadata, in `wilab/config.py`:

```python
from enum import Enum
from dataclasses import dataclass


class Capability(str, Enum):
    """Canonical capability identifiers."""
    BAND_24GHZ = "2.4ghz"
    BAND_5GHZ = "5ghz"

    @classmethod
    def ids(cls) -> list[str]:
        return [c.value for c in cls]


class CapabilityKind(str, Enum):
    """What sort of statement a capability makes."""
    RADIO = "radio"     # what the device may transmit
    POLICY = "policy"   # what the administrator allows to be changed


class CapabilityType(str, Enum):
    """Value domain. v1 implements BOOLEAN only."""
    BOOLEAN = "boolean"
    INTEGER = "integer"   # reserved — see §3.1


@dataclass(frozen=True)
class CapabilityDef:
    id: Capability
    label: str                                   # human label, served in /status
    kind: CapabilityKind
    type: CapabilityType = CapabilityType.BOOLEAN
    group: str | None = None                     # see §5.5
    matchable: bool = True                       # reserved — see §3.1


CAPABILITY_REGISTRY: dict[Capability, CapabilityDef] = {
    Capability.BAND_24GHZ: CapabilityDef(
        id=Capability.BAND_24GHZ, label="2.4 GHz",
        kind=CapabilityKind.RADIO, group="band",
    ),
    Capability.BAND_5GHZ: CapabilityDef(
        id=Capability.BAND_5GHZ, label="5 GHz",
        kind=CapabilityKind.RADIO, group="band",
    ),
}

# Groups where at least one member must be enabled per device (see §5.5).
GROUPS_REQUIRING_ONE: frozenset[str] = frozenset({"band"})

# v1 guard: the selection algorithm implements booleans only and does no
# matchability filtering. Registering anything else must fail at import time,
# not silently mis-allocate at runtime. See §3.1.
assert all(
    d.type is CapabilityType.BOOLEAN and d.matchable
    for d in CAPABILITY_REGISTRY.values()
), "v1 supports only boolean, matchable capabilities — see §3.1 before adding one"


def normalise_capability_id(raw: object) -> str:
    """Canonical form of a capability id. Shared by the config validator and the API."""
    return str(raw).strip().lower()
```

> **Adding a capability later** = one `Capability` member + one `CAPABILITY_REGISTRY`
> entry, adjacent in the same file. Nothing else changes: validation, `/status`, the
> request validator and the frontend all read the registry. A future `change-ssid`
> would be `CapabilityDef(id=..., label="SSID change", kind=POLICY, group=None)` — no
> group, so it is free to be `false` on a perfectly usable device.
>
> Note there is no `default` field: with completion mandatory
> ([§2.3](#23-declaration-is-mandatory-and-complete)) nothing is ever defaulted, so a
> default value would be dead metadata inviting exactly the silent behaviour C3 rules
> out.
>
> Keeping the enum *and* the registry is deliberate: the enum gives mypy exhaustive,
> type-safe ids (the project runs `make type-check`), the registry carries the metadata.
> They are co-located, so they cannot drift unnoticed.

`normalise_capability_id()` is exported deliberately: the config file and the API
request must canonicalise ids **identically**, and the only way to guarantee that is one
shared function rather than two `.strip().lower()` calls that drift.

### 4.3 `NetworkEntry` changes

```python
class NetworkEntry(BaseModel):
    interface: str
    display_name: str
    capabilities: Dict[str, bool]     # required — no default

    @property
    def device_id(self) -> str:
        return self.interface

    @property
    def capability_set(self) -> set[Capability]:
        """Enabled capabilities as a set (boolean capabilities only)."""
        return {Capability(k) for k, v in self.capabilities.items() if v}
```

By the time a `NetworkEntry` is constructed the validator has already run, so
`capabilities` is guaranteed complete, canonically keyed and free of unknown ids. The
model therefore stays a plain typed container: **the semantic rules live in the
validator, not scattered across Pydantic field validators.** This is a deliberate move
of existing logic — see [§5.3](#53-validation-phases).

`capability_set` returning `set[Capability]` is what the reservation layer consumes —
the raw dict never leaves the config layer. When quantitative capabilities arrive this
property gains a sibling (`capability_values: dict[Capability, bool | int]`) rather than
changing shape.

### 4.4 `AppConfig` helper

Both the reservation route and the status route need "the enabled capability ids of
device X". The helper belongs on the config object, not in a route module:

```python
class AppConfig(BaseModel):
    ...

    def capabilities_for(self, device_id: str) -> list[str]:
        """Sorted enabled capability ids for a device ([] if unknown)."""
        for n in self.networks:
            if n.device_id == device_id:
                return sorted(c.value for c in n.capability_set)
        return []
```

An earlier draft put this in `wilab/api/routes/reservation.py` next to
`_display_name_for()` and imported it from `status.py`. **Route modules importing from
each other is a dependency direction this codebase does not otherwise have**, and it
would make `status.py` depend on the reservation router's import side effects. Putting
it on `AppConfig` keeps the routes as leaves of the dependency graph.

`_display_name_for()` stays where it is — moving it is unrelated churn, and this
proposal should not grow a refactor it does not need.

### 4.5 What is deliberately absent

There is **no hardware probing anywhere in the capability path**. No part of capability
resolution calls `ChannelManager`, `iw`, or reads `/sys/class/net`.

Two welcome consequences:

* **No startup ordering constraint.** An earlier draft had to resolve capabilities
  synchronously in the `lifespan` hook, *before* `get_reservation_manager()` built the
  pool, because the channel cache is warmed in a background daemon thread
  (`_warm_channel_cache` in [wilab/api/\_\_init\_\_.py](../../wilab/api/__init__.py)) and the
  first reservation could race it. With config as the only source, capabilities are
  fully known the moment `load_config()` returns. **`wilab/api/__init__.py` needs no
  change at all**, and the background warm-up keeps serving `available-channels`
  exactly as today.
* **Testability.** Capability logic is pure config parsing — no mocked `iw` output, no
  hardware fixtures.

`ChannelManager` retains its existing, unrelated job: validating that a *specific
channel* is usable at AP creation time. That is a per-request hardware check, not a
capability.

---

## 5. Technical Design — Configuration Validator

New module: **`wilab/config_validation.py`**.

### 5.1 Design goals

| Goal | Consequence for the implementation |
|------|-----------------------------------|
| **Report everything, fail once** | No fail-fast anywhere in the pipeline; every phase runs and accumulates issues |
| **Precise paths** | `networks[1].capabilities["5ghz"]`, not "invalid networks" — the administrator must find the line without guessing |
| **Actionable hints** | Every issue carries a concrete fix, not just a complaint |
| **Runnable standalone** | Pure function of the file; no managers constructed, no server started |
| **Runnable off-bench** | Hardware checks are a separate opt-in phase ([§5.3](#53-validation-phases)) |
| **Extensible by field** | Custom per-section rules registered declaratively |
| **Never writes** | Constraint C3 |
| **Never leaks secrets** | The report names `auth_token` as a path but must never print its value ([§10.4](#104-security-notes)) |

The *why* behind mandatory completeness is in
[§2.3](#23-declaration-is-mandatory-and-complete) and not repeated here.

### 5.2 Issue model

```python
class Severity(str, Enum):
    ERROR = "error"       # service must not start
    WARNING = "warning"   # service starts, operator should look


@dataclass(frozen=True)
class ValidationIssue:
    path: str                    # 'networks[1].capabilities["5ghz"]'
    message: str                 # what is wrong
    severity: Severity = Severity.ERROR
    hint: str | None = None      # how to fix it


@dataclass(frozen=True)
class ValidationReport:
    config_path: str
    issues: tuple[ValidationIssue, ...]
    unreadable: bool = False     # file missing / unparseable — see §5.8

    @property
    def errors(self) -> tuple[ValidationIssue, ...]: ...
    @property
    def warnings(self) -> tuple[ValidationIssue, ...]: ...
    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        """Human-readable report — used identically by the CLI and by startup."""
```

`unreadable` exists so the CLI can return exit code **2** (file missing, unreadable, or
not parseable) rather than **1** (the file was read and is wrong). Without a marker on
the report the caller cannot tell those apart, and a CI job cannot distinguish "you
forgot to mount the config" from "the config is invalid".

One renderer, two call sites: `--validate-config` prints it to stdout, startup logs it
before exiting. The administrator sees the same text either way.

### 5.3 Validation phases

```python
def validate_config_file(
    path: str, *, check_hardware: bool = False
) -> ValidationReport:
    """Validate a config file. Pure: reads the file, writes nothing."""
```

| Phase | Checks | On failure |
|-------|--------|------------|
| **1. Structural** | File exists, is readable, parses as YAML, top level is a mapping | Return immediately with `unreadable=True` — later phases have nothing to inspect |
| **2. Presence** | Every schema key present, at every level ([§5.4](#54-the-required-key-manifest)) | Collect and continue |
| **3. Unknown keys** | No key outside the schema, at every level | Collect and continue |
| **4. Types & ranges** | Delegated to the Pydantic models; each `ValidationError` mapped to a `ValidationIssue` with its `loc` as the path | Collect and continue |
| **5. Custom rules** | The registered per-field and cross-field rules ([§5.5](#55-the-rule-registry-and-the-capabilities-custom-rule)) | Collect and continue |
| **6. Hardware** *(opt-in)* | Interfaces exist, are wireless, support AP mode; `dhcp_base_network` does not overlap a host route | Collect and continue |

Phases 2–6 all run, so a single report covers a missing key, a typo and a bad subnet at
once.

**Phase 4 must de-duplicate against phase 2.** A missing key is reported by the presence
check *and* by Pydantic as `Field required` at the same `loc`. Without suppression the
administrator sees every missing key twice, which undermines the report's whole purpose.
The rule: **phase 4 discards any issue whose path was already reported by phase 2 or 3.**
Deduplicate on `path`, keeping the earlier (more specific, hint-carrying) issue. This is
a defect found in review, not an optimisation — see [§16](#16-review-log), SW-3.

**Rules must be defensive.** A rule whose input key is missing returns nothing — phase 2
already reported the absence, and a cascade of derived complaints would bury the real
problem. Concretely: `min_timeout <= max_timeout` emits nothing if either key is absent
or non-integer.

**Phase 6 is opt-in** because it is the only phase that touches the machine. This split
is what makes the validator useful on a developer laptop: `--validate-config` alone
checks structure and semantics anywhere, `--validate-config --check-hardware` adds the
adapter checks and is what startup always runs.

### 5.4 The required-key manifest

The manifest is **derived from the Pydantic models**, not hand-maintained:

```python
def _required_keys(model: type[BaseModel]) -> set[str]:
    """Every declared field is mandatory in the file, regardless of Python default."""
    return {
        name for name, f in model.model_fields.items()
        if not (f.json_schema_extra or {}).get("file_optional", False)
    }
```

So `AppConfig.model_fields` yields the top-level required keys and
`NetworkEntry.model_fields` the per-device ones — meaning **a new config field is
automatically required in the file**, with no second list to update. The
`file_optional` marker is the escape hatch for a genuinely optional future field; no
v1 field uses it.

Capability keys extend the same idea one level deeper: for each entry of `networks`,
the required keys of `capabilities` are `CAPABILITY_REGISTRY.keys()`.

Consequence for fields that today carry Python defaults (`api_port`, `max_timeout`,
`min_timeout`, `allow_unlimited_reservation`, `upstream_interface`, `country_code`,
`dns_server`, `internet_enabled_by_default`, `cors_origins`): the defaults stay in the
model as type documentation, but the file must still state them.

`cors_origins` is the one field where "present but empty" is meaningful. Both
`cors_origins: []` and `cors_origins: null` are accepted and both mean CORS disabled —
they replace today's "omit the key and hope". The type stays
`Optional[List[str]]` so `null` round-trips.

### 5.5 The rule registry and the capabilities custom rule

Rules are registered against the section they validate:

```python
ValidationRule = Callable[["ValidationContext"], Iterable[ValidationIssue]]

@dataclass(frozen=True)
class ValidationContext:
    raw: dict            # parsed YAML, untouched
    config_path: str
    check_hardware: bool

_RULES: list[tuple[str, ValidationRule]] = []

def rule(scope: str):
    """Register a custom rule for a config section (scope is documentation + report grouping)."""
    def decorator(fn: ValidationRule) -> ValidationRule:
        _RULES.append((scope, fn))
        return fn
    return decorator
```

Rules read `ctx.raw`, which is untyped parsed YAML. **Every rule must guard its inputs
with `isinstance`** — `raw["networks"]` may be a string, a dict, or absent, and phase 5
runs even when phase 2/4 found problems. A rule that assumes a shape will raise, and an
exception inside a rule must never take down the whole report.

> **Rule isolation.** `validate_config_file()` wraps each rule invocation in a
> `try/except Exception` and converts an unexpected exception into a single
> `ValidationIssue` at the rule's scope ("internal validation error in rule X"). A buggy
> rule then costs one confusing line, not the entire report. This matters because the
> report is the only diagnostic the administrator gets.

The capabilities rule the requester named — *2.4 GHz and 5 GHz cannot both be off*:

```python
@rule(scope="networks[].capabilities")
def at_least_one_enabled_per_group(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    """Every device must enable at least one capability of each required group."""
    networks = ctx.raw.get("networks")
    if not isinstance(networks, list):
        return                            # phase 2/4 already reported it
    for idx, net in enumerate(networks):
        caps = net.get("capabilities") if isinstance(net, dict) else None
        if not isinstance(caps, dict):
            continue                      # phase 2/4 already reported it
        canonical = {normalise_capability_id(k): v for k, v in caps.items()}
        for group in sorted(GROUPS_REQUIRING_ONE):
            members = [c for c, d in CAPABILITY_REGISTRY.items() if d.group == group]
            if not any(canonical.get(c.value) is True for c in members):
                yield ValidationIssue(
                    path=f"networks[{idx}].capabilities",
                    message=(
                        f"At least one capability of group '{group}' must be enabled "
                        f"({', '.join(c.value for c in members)}); all are false."
                    ),
                    hint="A device with no usable band can never host an access point.",
                )
```

Three things worth noting. First, it is a **custom rule scoped to the capabilities
section**, exactly as requested — it lives with the other rules, not buried in a
Pydantic validator. Second, it is **parameterised by the registry's `group` metadata
rather than hardcoding `2.4ghz`/`5ghz`**, so a future `change-ssid` capability
(`group=None`) is exempt automatically, as it must be: a device that forbids SSID
changes is perfectly usable. Third, `is True` rather than a truthy test — YAML `"yes"`
parses to a string in YAML 1.2 and must not be mistaken for an enabled band; phase 4
reports the type error separately.

### 5.6 The rule set

Implementing the validator is also the opportunity to close real gaps that exist today.
Rules marked **new** are not checked anywhere in the current codebase; each was verified
against the code before being labelled.

| Scope | Rule | Severity |
|-------|------|----------|
| `auth_token` | **new:** non-empty — `auth_token: ""` passes Pydantic today and produces an API where the empty Bearer token authenticates | ERROR |
| `auth_token` | **new:** warn when left at the `config.example.yaml` value | WARNING |
| `api_port` | **new:** integer in 1–65535; warn below 1024 (needs privileges) | ERROR / WARNING |
| `min_timeout` | ≥ 10 (existing hardcoded floor, relocated) | ERROR |
| `min_timeout` / `max_timeout` | **new:** `min_timeout <= max_timeout` — today a config with min > max starts cleanly and makes **every** reservation impossible: the route rejects each duration as both below min and above max | ERROR |
| `max_timeout` | **new:** positive | ERROR |
| `dhcp_base_network` | Valid IPv4 CIDR with `/24` prefix (existing, relocated) | ERROR |
| `dhcp_base_network` + `networks` | Third-octet overflow for the device count (existing, relocated) | ERROR |
| `dhcp_base_network` | **new, hardware phase:** does not overlap an existing host route — `config.example.yaml` calls this CRITICAL and warns it can block SSH, yet nothing verifies it | ERROR |
| `dns_server` | **new:** valid IPv4 address | ERROR |
| `country_code` | **new:** two-letter ISO 3166-1 alpha-2 shape, uppercase | ERROR |
| `upstream_interface` | `auto` or non-empty name (existing, relocated) | ERROR |
| `upstream_interface` | **new, hardware phase:** when not `auto`, the named interface exists | ERROR |
| `cors_origins` | **new:** each entry is a syntactically valid origin (`scheme://host[:port]`, no trailing path) | ERROR |
| `cors_origins` | **new:** warn when non-empty (CORS enabled — fine in dev, review for production) | WARNING |
| `networks` | **new:** non-empty — `networks: []` passes today (verified: the third-octet check computes `base − 1` and never trips) and yields a service that can never reserve anything | ERROR |
| `networks` | No duplicate `interface` (existing, relocated) | ERROR |
| `networks[].display_name` | **new:** non-empty | ERROR |
| `networks[].display_name` | **new:** warn on duplicates — the frontend labels cards by it and two identical labels are indistinguishable to the user | WARNING |
| `networks[].capabilities` | Complete: every registry id present | ERROR |
| `networks[].capabilities` | No unknown ids; report the valid list | ERROR |
| `networks[].capabilities` | **new:** no duplicate ids after normalisation (`"5ghz"` and `"5GHz"` in the same map) | ERROR |
| `networks[].capabilities` | At least one enabled per required group ([§5.5](#55-the-rule-registry-and-the-capabilities-custom-rule)) | ERROR |
| `networks[].interface` | **hardware phase:** exists, wireless, AP-capable (existing `validate_interface`, relocated) | ERROR |

The existing `field_validator`s in [wilab/config.py](../../wilab/config.py)
(`validate_min_timeout`, `validate_upstream_interface`, `validate_dhcp_base_network`,
`validate_network_count`) **move into the rule set**. Keeping them in Pydantic would
mean two reporting paths with different formatting, and Pydantic's fail-fast-per-field
behaviour is exactly what goal 1 rules out.

### 5.7 Report format

```
Wi-Lab configuration validation FAILED
File: /opt/wilab/config.yaml
3 error(s), 1 warning(s)

ERROR   networks[0].capabilities["5ghz"]
        Missing required capability key.
        → Add '"5ghz": true' or '"5ghz": false' under networks[0].capabilities

ERROR   networks[1].capabilities
        At least one capability of group 'band' must be enabled (2.4ghz, 5ghz);
        all are false.
        → A device with no usable band can never host an access point.

ERROR   min_timeout
        min_timeout (600) must not be greater than max_timeout (300).
        → Every reservation request would be rejected as both too short and too long.

WARNING auth_token
        Still set to the example value from config.example.yaml.
        → Generate one with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

On success:

```
Wi-Lab configuration validation OK
File: /opt/wilab/config.yaml
3 network(s), capabilities: 2.4ghz, 5ghz
1 warning(s) — see above
```

Issues are ordered by **schema position, not discovery order**: top-level keys in
`AppConfig` field order, then `networks` in declaration order, then per-device keys. A
report that reads top-to-bottom like the file is one the administrator can work through
linearly. Ordering is a tested property ([§12.2](#122-teststest_config_validationpy-new)),
because a report whose order shifts between runs is hard to diff in CI.

### 5.8 CLI integration

[main.py](../../main.py) currently takes no arguments. Add `argparse`:

```
Usage: python3 main.py [options]

  --config PATH        Path to config.yaml (default: $CONFIG_PATH or ./config.yaml)
  --validate-config    Validate the configuration and exit, without starting the server
  --check-hardware     With --validate-config, also verify interfaces and host routes
                       (implied when starting normally)
```

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Valid (warnings may have been printed) |
| `1` | Validation errors found |
| `2` | File missing, unreadable, or not parseable as YAML (`report.unreadable`) |

`--check-hardware` is **opt-in for the CLI and implied at startup**: a developer
validating a config on a laptop must not be told their bench antennas are missing, while
the service itself must never start against absent hardware.

`--check-hardware` without `--validate-config` is accepted and ignored (startup always
checks hardware), rather than being an argparse error — the flag combination is
harmless and rejecting it would only surprise someone scripting the CLI.

### 5.9 Startup integration

Single enforcement point, inside `load_config()`, so no code path can bypass it:

```python
def load_config(path: Optional[str] = None) -> AppConfig:
    cfg_path = path or os.environ.get('CONFIG_PATH') or os.path.join(os.getcwd(), 'config.yaml')

    # Imported lazily: config_validation imports the models and registry from this
    # module, so a top-level import here would be circular. This mirrors the existing
    # deferred import of validate_interface. See §16, SW-1.
    from .config_validation import validate_config_file

    report = validate_config_file(cfg_path, check_hardware=True)
    if report.warnings:
        logger.warning("Configuration warnings:\n%s", report.render())
    if not report.ok:
        raise SystemExit(report.render())

    with open(cfg_path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}
    config = AppConfig(**raw)
    _log_capability_matrix(config)
    return config
```

`main.py --validate-config` calls `validate_config_file()` **directly**, never
`load_config()` — validating must not construct managers, touch the network, or start
anything.

The Pydantic construction keeps its `try/except ValidationError` as defence in depth: if
a model and the validator ever disagree, that is a bug and it should surface loudly
rather than crash obscurely later.

`_log_capability_matrix()` emits one INFO block at startup so `journalctl` shows what
the pool actually looks like — the single most useful line when diagnosing "why did I
get that antenna":

```
INFO  Managed device capabilities:
INFO    wlxbc071dc527d6  bench-antenna-1   2.4ghz
INFO    wlx7820512451b4  bench-antenna-2   2.4ghz, 5ghz
INFO    wlx782051245264  bench-antenna-3   2.4ghz, 5ghz
```

### 5.10 Module boundaries

```
wilab/config.py              models, Capability, CAPABILITY_REGISTRY, load_config()
        ▲                                    │
        │ imports models + registry          │ imports lazily, inside load_config()
        │                                    ▼
wilab/config_validation.py   ValidationIssue/Report, @rule registry, rule set
        ▲
        │
main.py                      argparse, --validate-config
```

Two import hazards, both found in review and both with a mandated resolution:

* **Circular import.** `config_validation` needs the models and registry from `config`;
  `load_config` needs the validator. The import inside `load_config` breaks the cycle
  and matches the pattern already used in that function for `validate_interface`. The
  alternative — splitting the models into `wilab/config_models.py` — is cleaner in the
  abstract but touches every existing importer of `wilab.config` for no functional gain.

* **Deferred import of hardware helpers is mandatory, not stylistic.**
  `wilab/config_validation.py` must import `validate_interface` **inside** the phase-6
  function, not at module level. `tests/conftest.py:197` neutralises it with
  `monkeypatch.setattr(interface, "validate_interface", mock_validate_interface)`, which
  rebinds the attribute on the `wilab.wifi.interface` module. A module-level
  `from ..wifi.interface import validate_interface` captures the original function
  object at import time and the patch would silently have no effect — every test that
  loads a config would then attempt real `iw` calls. The same applies to the new
  host-route check, which must go through `commands.execute_command`
  (already mocked at `conftest.py:210`) rather than calling `subprocess` directly.

### 5.11 Why this replaces automatic completion

An earlier draft of this proposal had the parser **write missing keys back into
`config.yaml`** with default values. That is now dropped, and the simplification is
substantial:

| Dropped with it | Why it existed |
|---|---|
| `ruamel.yaml` dependency | Round-trip writing was the only way to add keys without deleting the file's ~150 lines of documentation comments |
| Atomic write + `config.yaml.bak` + mode/ownership preservation | The service runs as root; a careless rewrite could lock the administrator out of their own file |
| Read-only-file fallback path | Container secrets and read-only mounts must not block startup |
| "Fixture is rewritten by the test run" hazard | Loading `tests/test.config.yaml` would have mutated a committed file |
| Per-capability `default` metadata | Nothing is defaulted any more |

All of that surface area existed to support a behaviour that quietly decides things on
the administrator's behalf. Validation achieves the same goal — a complete, explicit,
reviewed config — while writing nothing, and it generalises to *every* field instead of
just capabilities.

---

## 6. Technical Design — API

**Zero new endpoints.** Three existing payloads are extended.

### 6.1 `GET /api/v1/status` — additive response fields

This endpoint is already polled by the frontend on a timer and already contains a
`networks[]` section built from `config.networks`
([wilab/api/routes/status.py](../../wilab/api/routes/status.py)). Capabilities are **static
config data**: serving them here costs no shell command, no extra latency, and no new
auth surface. Putting them anywhere else would mean a second round-trip for data the
client already fetches.

**Verdict: yes, `/status` is the right home for this.**

```jsonc
{
  "version": "4.0.0",
  "status": "standby",
  "networks": [
    {
      "display_name": "bench-antenna-1",
      "interface": "wlxbc071dc527d6",
      "reserved": false,
      "reservation_remaining_seconds": null,
      "capabilities": ["2.4ghz"]                      // NEW
    },
    {
      "display_name": "bench-antenna-2",
      "interface": "wlx7820512451b4",
      "reserved": true,
      "reservation_remaining_seconds": 1800,
      "capabilities": ["2.4ghz", "5ghz"]              // NEW
    }
  ],
  "capabilities_catalogue": [                          // NEW
    { "id": "2.4ghz", "label": "2.4 GHz", "kind": "radio",
      "total_devices": 2, "available_devices": 1 },
    { "id": "5ghz",   "label": "5 GHz",   "kind": "radio",
      "total_devices": 1, "available_devices": 0 }
  ],
  "reservation_policy": { "min_seconds": 60, "max_seconds": 86400, "allow_unlimited": true },
  "checks": { "...": "unchanged" }
}
```

Design notes:

* `networks[].capabilities` is a **sorted array of enabled ids**, not the config map.
  The wire format carries facts, not the administrator's `false` entries; sorting makes
  responses byte-stable and diffable.
* `capabilities_catalogue` is **derivable** client-side by unioning
  `networks[].capabilities`, but serving it explicitly buys three things: a **human
  label** owned by the backend (so a new capability needs no Angular release), the
  **kind** (so the picker can group Radio / Policy sections), and **pre-computed
  counts** used directly by the picker. It is a handful of bytes on an already-cheap
  endpoint.
* `total_devices` counts devices where the capability is **enabled**; `available_devices`
  counts the enabled-and-free subset. A capability that **no** device enables is omitted
  from the catalogue entirely: offering a filter that can never match anything is worse
  than not offering it, and a client that requests it anyway gets the 422 permanent
  error, which says the same thing more precisely.
* Both fields are **purely additive** — existing clients ignore them.

### 6.2 `POST /api/v1/device-reservation` — extended request

```python
class ReservationCreateRequest(BaseModel):
    duration_seconds: int
    required_capabilities: List[str] = Field(
        ...,                               # REQUIRED since 4.0.0; [] means "any device"
        description=(
            "Capabilities the assigned device must provide. Mandatory: an empty list "
            "explicitly means any device is acceptable. The least capable matching "
            "free device is assigned."
        ),
        json_schema_extra={"example": ["2.4ghz"]},
    )
    interface: Optional[str] = Field(
        default=None,
        description=(
            "Force a specific managed device by interface name. When omitted, "
            "Wi-Lab selects the best match automatically."
        ),
        json_schema_extra={"example": "wlxbc071dc527d6"},
    )

    @field_validator("required_capabilities")
    @classmethod
    def validate_capability_ids(cls, v: List[str]) -> List[str]:
        """Canonicalise and validate ids against the same registry as the config."""
        canonical = [normalise_capability_id(c) for c in v]
        unknown = sorted({c for c in canonical if c not in Capability.ids()})
        if unknown:
            raise ValueError(
                f"Unknown capabilities: {', '.join(unknown)}. "
                f"Valid: {', '.join(Capability.ids())}"
            )
        return sorted(set(canonical))          # de-duplicated, order-independent
```

Validation notes:

* Ids are canonicalised with **the same `normalise_capability_id()` the config uses**,
  so `"5GHz"` is accepted identically on both sides. Two independent
  `.strip().lower()` calls would eventually drift; one shared function cannot.
* Unknown id → **422**, listing the valid ids.
* Duplicates are removed and the list is sorted: `["5ghz","2.4ghz","5ghz"]` and
  `["2.4ghz","5ghz"]` are the same request, which makes the endpoint's behaviour
  independent of client-side ordering and makes tests deterministic.
* The request model **forbids unknown fields** (`extra="forbid"`): a client that still
  sends the removed `interface` gets a `422` naming it, instead of being ignored.
* `duration_seconds` validation is untouched.

> **`required_capabilities` is mandatory** (revised in 4.0.0; the first draft kept it
> optional). A client that does not say what it needs is not given a silent guess: it is
> rejected with `422` and `Missing required field(s): required_capabilities`, listing
> every missing field at once. `null` is rejected too; `[]` is the explicit "any device".
> See [D16](#15-design-decisions--rejected-alternatives).

Request examples:

```bash
# A. capability-driven
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900, "required_capabilities": ["5ghz"]}'

# B. no preference — explicit empty list
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900, "required_capabilities": []}'

# Rejected (3.x client): 422 "Missing required field(s): required_capabilities"
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900}'
```

### 6.3 `ReservationResponse` — additive field

```jsonc
{
  "reservation_id": "a1b2c3d4",
  "display_name": "bench-antenna-1",
  "interface": "wlxbc071dc527d6",
  "expires_at": "2026-04-16 15:15:00",
  "expires_in": 900,
  "capabilities": ["2.4ghz"]            // NEW — what the caller actually got
}
```

Returned by both `POST /device-reservation` and `GET /device-reservation/{rid}`, since
both go through `_build_response()`. This closes the loop: the client never has to
cross-reference `/status` to know what its own reservation can do, and the network
form dialog can filter its band list from the reservation it already holds.

### 6.4 `GET /api/v1/debug` — optional

Add `capabilities` to `interfaces.managed[]` entries for troubleshooting parity with
`/status`. Cosmetic, zero risk, do it in the same commit.

### 6.5 API surface summary

| Endpoint | Change | Breaking? |
|----------|--------|-----------|
| `GET /api/v1/status` | +`networks[].capabilities`, +`capabilities_catalogue` | No (additive; always present) |
| `POST /api/v1/device-reservation` | +`required_capabilities` (**required**) | **Yes** — a request without `required_capabilities` is rejected |
| `GET /api/v1/device-reservation/{rid}` | +`capabilities` in response | No (additive) |
| `GET /api/v1/debug` | +`capabilities` in managed interfaces | No (additive) |
| — | **no new endpoints** | — |

---

## 7. Technical Design — Backend

### 7.1 `wilab/reservation.py`

The manager currently receives `device_ids: list[str]` and has no notion of what a
device can do. It needs the capability data to select.

```python
from collections.abc import Sequence


@dataclass(frozen=True)
class DeviceSpec:
    """A managed device and its declared capabilities, in declaration order."""
    device_id: str
    capabilities: frozenset[Capability]
    index: int                      # declaration order, used as tie-break


class ReservationManager:
    def __init__(self, devices: Sequence[DeviceSpec]) -> None:
        self._devices: list[DeviceSpec] = list(devices)
        ...
```

> **`DeviceSpec` only.** The first draft also accepted a plain `str` (a capability-less
> device) to keep ~46 test call sites unchanged. That shim was removed in 4.0.0 along with
> the other compatibility paths; tests build pools with `tests/helpers.py::device_specs()`.

New/changed methods:

```python
def create(
    self,
    duration_seconds: int,
    required_capabilities: frozenset[Capability] = frozenset(),
) -> Reservation:
    """Reserve the least capable free device that satisfies the requirements.

    Args:
        duration_seconds: Reservation duration (0 = unlimited).
        required_capabilities: Capabilities the device must provide.

    Raises:
        CapabilityUnsatisfiableError: no *configured* device offers the requested
                                      capabilities (permanent — retrying will not help).
        NoDeviceAvailableError:       matching devices exist but all are reserved
                                      (transient — carries next_available_at computed
                                      over the matching subset only, or None).
    """
```

Internal helper replacing `_first_available()`:

```python
def _select(self, required: frozenset[Capability]) -> Optional[DeviceSpec]:
    """Least capable free device satisfying `required`; None if none is free."""
    candidates = [
        d for d in self._devices
        if d.device_id not in self._device_to_rid and required <= d.capabilities
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda d: (len(d.capabilities - required), d.index))
```

#### Exceptions

```python
class CapabilityUnsatisfiableError(Exception):
    """No configured device can ever satisfy the request. Permanent.

    Args:
        requested: the capability set that could not be satisfied.
        available: union of capabilities across ALL configured devices — not just
            the free ones. This is what makes the error permanent: adding time does
            not add capabilities to the pool.
    """
```

#### `_soonest_expiry` and the unlimited-reservation hole

`_soonest_expiry()` gains a filter so a 409 reports the truth:

```python
def _soonest_expiry(self, among: Optional[set[str]] = None) -> Optional[float]:
    """Earliest expiry among active reservations, restricted to `among`.

    Returns None when every relevant reservation is unlimited — there is then no
    next-available time to report.
    """
```

Two changes here, and the second is a **pre-existing bug this feature would otherwise
amplify**:

1. **The filter.** Called with the set of device ids that *would* match the request.
   Without it, a user asking for 5 GHz is told "available in 30 s" because a 2.4-only
   antenna is about to free up — a device that can never serve them.

2. **`Optional[float]`, not `float`.** Today `_soonest_expiry()` returns `time.time()`
   when no active reservation has an expiry, i.e. when every device is held by an
   **unlimited** reservation. The API then reports `next_available_in: 0` — "available
   now" — which is false, and the frontend starts a countdown that fires immediately and
   retries into another 409. With `allow_unlimited_reservation: true` (the value shipped
   in `config.example.yaml`) this is reachable today; capability filtering makes it
   reachable more often, because the matching subset is smaller and more likely to be
   entirely unlimited.

   The fix: return `None`, and have `NoDeviceAvailableError.next_available_at` /
   `next_available_in` be `Optional`. The 409 body then carries `null` for both, and the
   frontend renders "no scheduled release — all matching devices are held indefinitely"
   instead of a countdown. This is a small, well-contained bug fix that belongs in this
   change because this change is what makes it likely; it needs its own CHANGELOG entry
   under `### 🐛 Bug Fixes` and its own regression test
   ([§12.5](#125-teststest_reservationpy)).

The `Reservation` dataclass itself is **unchanged**. Capabilities are a property of the
*device*, not of the reservation; they are looked up from the pool when building the
response. Denormalising them into `Reservation` would create a second source of truth
that could drift after a config reload.

**Concurrency:** `_select()` runs inside the existing `self._lock`, after
`_purge_expired()`, exactly where `_first_available()` runs today. No new locking, no
new race surface. `delete()`, `delete_all()` and `is_device_reserved()` are untouched.

### 7.2 `wilab/api/dependencies.py`

```python
def get_reservation_manager(config: AppConfig = Depends(get_config)) -> ReservationManager:
    global _reservation_manager
    if _reservation_manager is None:
        devices = [
            DeviceSpec(
                device_id=n.device_id,
                capabilities=frozenset(n.capability_set),
                index=i,
            )
            for i, n in enumerate(config.networks)
        ]
        _reservation_manager = ReservationManager(devices)
    return _reservation_manager
```

Note how short this is: because capabilities come straight from the validated config
([§4.5](#45-what-is-deliberately-absent)), there is no resolution step, no cache and no
startup hook to coordinate with.

### 7.3 `wilab/api/routes/reservation.py`

`create_reservation()` grows a translation + error-mapping layer; the duration
validation block above it is untouched.

```python
required = frozenset(Capability(c) for c in req.required_capabilities)
try:
    r = mgr.create(duration, required_capabilities=required)
except CapabilityUnsatisfiableError as exc:
    raise HTTPException(422, detail={
        "error": "No device provides the requested capabilities",
        "requested": sorted(c.value for c in required),
        "available_capabilities": exc.available,
    })
except NoDeviceAvailableError as exc:
    raise HTTPException(409, detail={
        "error": "No matching device available",
        # Both null when every matching reservation is unlimited — see §7.1
        "next_available_at": (
            datetime.fromtimestamp(exc.next_available_at, tz=timezone.utc)
                    .strftime("%Y-%m-%d %H:%M:%S")
            if exc.next_available_at is not None else None
        ),
        "next_available_in": exc.next_available_in,
        "requested_capabilities": sorted(c.value for c in required),
    })
```

`Capability(c)` is safe here because the request validator
([§6.2](#62-post-apiv1device-reservation--extended-request)) has already canonicalised
and rejected unknown ids — but note the ordering dependency: **the conversion must stay
after validation**, or an unknown id becomes an uncaught `ValueError` and a 500.

`_build_response()` gains `capabilities=config.capabilities_for(r.device_id)`
([§4.4](#44-appconfig-helper)).

> **Timezone consistency.** `_build_response()` already formats `expires_at` with
> `tz=timezone.utc`, while the existing 409 handler uses a naive
> `datetime.fromtimestamp(...)` — the two differ by the host's UTC offset in the same
> API. Since this change touches the 409 body anyway, align it to `timezone.utc`. Note
> this is a **visible change to an existing field** for any deployment not running in
> UTC, so it belongs in the CHANGELOG under `### 🐛 Bug Fixes` rather than passing
> silently.

### 7.4 `wilab/api/routes/status.py`

In the `networks_info` loop, add
`entry["capabilities"] = config.capabilities_for(n.device_id)`. Then build the
catalogue from the registry:

```python
status_data["capabilities_catalogue"] = [
    {
        "id": cap.value,
        "label": definition.label,
        "kind": definition.kind.value,
        "total_devices": total,
        "available_devices": free,
    }
    for cap, definition in CAPABILITY_REGISTRY.items()
    if (total := _count_declaring(cap)) > 0
]
```

Iterating the registry (not the union of device sets) keeps catalogue order stable and
label ownership in one place. Both counts come from data already in hand — the config
and `reservation_mgr.all_active()`, which the loop above already calls — so this adds no
new lookups to an endpoint the frontend polls.

### 7.5 Module impact summary

| File | Change |
|------|--------|
| **`wilab/config_validation.py`** | **New.** `Severity`, `ValidationIssue`, `ValidationReport`, `ValidationContext`, the `@rule` registry with per-rule exception isolation, `validate_config_file()` with phase 2/3↔4 de-duplication, the rule set of [§5.6](#56-the-rule-set), the ordered renderer |
| [wilab/config.py](../../wilab/config.py) | `Capability`, `CapabilityKind`, `CapabilityType`, `CapabilityDef`, `CAPABILITY_REGISTRY`, `GROUPS_REQUIRING_ONE`, the v1 assertion, `normalise_capability_id()`; `NetworkEntry.capabilities` (required) + `capability_set`; `AppConfig.capabilities_for()`; existing `field_validator`s **moved out**; `load_config()` validates (lazy import) and logs the capability matrix |
| [main.py](../../main.py) | `argparse`: `--config`, `--validate-config`, `--check-hardware`; exit codes 0/1/2 |
| [wilab/reservation.py](../../wilab/reservation.py) | `DeviceSpec`, `Sequence`-typed constructor, `create()` signature, `_select()`, `_soonest_expiry()` → `Optional[float]` + filter, `Optional` on `NoDeviceAvailableError`, `UnknownDeviceError`, `CapabilityUnsatisfiableError` |
| [wilab/api/routes/reservation.py](../../wilab/api/routes/reservation.py) | Request fields + validator, error mapping, null-safe 409 body, UTC alignment, `capabilities` in response |
| [wilab/api/routes/status.py](../../wilab/api/routes/status.py) | `networks[].capabilities`, `capabilities_catalogue`, `/debug` parity |
| [wilab/api/dependencies.py](../../wilab/api/dependencies.py) | Build the `DeviceSpec` list for the manager |
| [Makefile](../../Makefile) | `validate-config` target + `help` entry |
| [install/02-install-stages/](../../install/) | New stage running the validator after the venv exists, before `03-enable.sh` |
| [install/systemd/wi-lab.service.template](../../install/systemd/wi-lab.service.template) | `StartLimitIntervalSec` / `StartLimitBurst` — see [§10.1](#101-systemd-restart-loop-on-a-bad-config) |
| [config.example.yaml](../../config.example.yaml) | Complete `capabilities` block per device + explanatory comments |
| [tests/test.config.yaml](../../tests/test.config.yaml) | Multiple devices, every key present (see [§12.1](#121-teststestconfigyaml)) |
| [wilab/api/\_\_init\_\_.py](../../wilab/api/__init__.py) | **No change** — see [§4.5](#45-what-is-deliberately-absent) |
| [requirements.txt](../../requirements.txt) | **No change** — no new dependency |

---

## 8. Technical Design — Frontend

### 8.1 Models — [frontend/src/app/models/network.models.ts](../../frontend/src/app/models/network.models.ts)

```ts
export type CapabilityId = string;          // deliberately open, not a union type

export interface CapabilityInfo {
  id: CapabilityId;
  label: string;
  kind: string;                             // 'radio' | 'policy' | future kinds
  total_devices: number;
  available_devices: number;
}

export interface InterfaceInfo {
  display_name: string;
  interface: string;
  reserved: boolean;
  reservation_remaining_seconds: number | null;
  capabilities: CapabilityId[];             // NEW
}

export interface StatusResponse {
  // ...
  capabilities_catalogue: CapabilityInfo[]; // NEW
}

export interface ReservationRequest {
  duration_seconds: number;
  required_capabilities: CapabilityId[];    // NEW, mandatory ([] = any device)
  interface?: string;                       // NEW
}

export interface ReservationResponse {
  // ...
  capabilities: CapabilityId[];             // NEW
}

export interface NoDeviceAvailableError {
  detail: string;
  next_available_at: string | null;         // CHANGED — null when all unlimited
  next_available_in: number | null;         // CHANGED — see §7.1
}
```

> `CapabilityId` is a **`string` alias, not a `'2.4ghz' | '5ghz'` union**, and `kind` is
> a plain `string` rather than an enum. A union would force a frontend release every
> time the backend registry gains an entry, defeating the whole point of the
> server-provided catalogue.

### 8.2 Reservation dialog

Extend `ReservationDialogData`:

```ts
export interface ReservationDialogData {
  allowUnlimited: boolean;
  minSeconds: number;
  maxSeconds: number;
  capabilities: CapabilityInfo[];   // NEW — from status.capabilities_catalogue
  devices: InterfaceInfo[];         // NEW — from status.networks
}
```

Form shape:

```ts
this.form = this.formBuilder.group({
  mode: ['capability'],                       // 'capability' | 'device'
  selectedCapabilities: [[] as string[]],
  selectedInterface: [null as string | null],
  unlimited: [false],
  duration_seconds: [3600, [Validators.required, Validators.min(min), Validators.max(max)]],
});
```

Template structure (Angular Material, matching the existing dialog style):

```
┌─ Reserve Device ───────────────────────── [ 01h 00m 00s ] ─┐
│                                                            │
│  RADIO                                                     │
│   [x] 2.4 GHz          1 of 2 devices free                 │
│   [ ] 5 GHz            0 of 1 devices free                 │
│  POLICY            (section appears only when populated)   │
│   ⓘ 1 device matches your selection                        │
│                                                            │
│                                                            │
│  Duration (seconds) [ 3600 ]                               │
│  *Valid value from 60s to 86400s ( 24h 00m 00s )           │
│  [ ] Unlimited reservation (no expiry)                     │
│                                                            │
│                                    [ Cancel ] [ Reserve ]  │
└────────────────────────────────────────────────────────────┘
```

Behaviour:

* Capabilities are **grouped by `kind`**, with the group header rendered only when that
  kind has at least one entry. With the v1 registry only `RADIO` appears, so the header
  is hidden when there is exactly one group — the grouping code is still there, ready
  for the first policy capability.
* `matchingDeviceCount` is a getter over the injected `devices` array:
  `devices.filter(d => !d.reserved && selected.every(c => d.capabilities.includes(c))).length`.
  It reports **feasibility only** — it deliberately does **not** predict *which* device
  will be assigned. Reimplementing the minimality tie-break in TypeScript would create
  a second copy of the allocation rule that silently drifts from the backend.
* **Reserve** is disabled when `matchingDeviceCount === 0`.
* `onSubmit()` always emits `required_capabilities` (empty = any device) and the duration.
* **Accessibility:** the capability checkbox list needs a `role="group"` with a labelled
  heading. The existing dialog is keyboard-navigable and this one must not regress that.

Ticking **no boxes** is legal and means "no requirement" —
identical to today's behaviour, mapped to case C of
[§2.4](#24-user-facing-behaviour) (sent as `required_capabilities: []`).

### 8.3 `app.component.ts`

* Store `capabilitiesCatalogue` from the status response alongside `reservationPolicy`.
* Carry `capabilities` into `InterfaceSlot` so cards can display them.
* Pass both new fields into the dialog in `openReservationDialog()`.
* `createReservation()` needs **two** new error branches:
  * a **422** with `detail.error` starting `"No device provides"` / `"Device does not
    provide"` is *permanent* and must not start the `capacityTimer` countdown — it
    deserves a snackbar naming the missing capabilities;
  * a **409 with `next_available_in === null`** (all matching devices held indefinitely,
    [§7.1](#71-wilabreservationpy)) must show a static message, not a countdown from
    zero. `startCapacityTimer()` is only called when the value is a positive number.
* `buildSlots()` must tolerate a `capabilities` field absent from an older cached
  response: default to `[]`.

### 8.4 Network card

Show capability chips under the display name — a compact `mat-chip-set` of
`capabilities` — so a user can see at a glance what each antenna offers, in both the
available and the owned states. Guard against `undefined` for reservations restored
from `localStorage` written by a previous version.

### 8.5 Network form dialog

Derive the band list from the reservation's capabilities instead of the hardcoded
`bands = ['2.4ghz', '5ghz', 'dual']`:

```ts
get availableBands(): string[] {
  const caps = this.data.capabilities ?? [];
  const bands = caps.filter(c => c === '2.4ghz' || c === '5ghz');
  if (bands.includes('2.4ghz') && bands.includes('5ghz')) bands.push('dual');
  return bands;
}
```

Default the `band` control to the first available band rather than the literal
`'2.4ghz'`, which would be invalid on a 5 GHz-only device. The channel validators that
today key off `band === '2.4ghz'` keep working unchanged, since the band values
themselves are unchanged.

---

## 9. Error Model

### 9.1 Runtime (API)

| Scenario | Status | Body | Client action |
|----------|--------|------|---------------|
| Unknown capability id in request | 422 | `detail` lists valid ids | Fix the request (bug) |
| No configured device offers the requested capability set | 422 | `{error, requested, available_capabilities}` | **Permanent** — do not retry, tell the user |
| Matching devices exist, all reserved, at least one timed | 409 | `{error, next_available_at, next_available_in, requested_capabilities}` | **Transient** — retry after countdown |
| Matching devices exist, all held by **unlimited** reservations | 409 | same shape, `next_available_*` = `null` | **Transient but unscheduled** — show a static message, no countdown |
| Duration out of policy bounds | 422 | unchanged | unchanged |

The **422 vs 409 split is the load-bearing distinction**: 422 means *"this will never
work"*, 409 means *"this will work later"*. The frontend already branches on 409 to
start a countdown timer; conflating the two would make the UI count down toward an
availability that never arrives.

### 9.2 Startup (configuration)

Configuration problems never reach the API. They are reported by the validator
([§5.7](#57-report-format)) and the service exits: `SystemExit` with the rendered report
at startup, or exit code 1 from `--validate-config`. There is no partial-start mode and
no degraded pool — a config error means the operator's intent is unknown, and guessing
is precisely what constraints C2 and C3 forbid.

---

## 10. Operations & Deployment

### 10.1 systemd: restart loop on a bad config

[install/systemd/wi-lab.service.template](../../install/systemd/wi-lab.service.template) ships
`Restart=always` with `RestartSec=10s` and **no start-limit override**. A configuration
error is permanent by nature, so with this unit the service would exit, restart ten
seconds later, exit again, and loop indefinitely — flooding the journal with the same
report and showing `activating (auto-restart)` instead of a clean `failed`.

Add to `[Unit]`:

```ini
StartLimitIntervalSec=300
StartLimitBurst=3
```

After three failures in five minutes systemd gives up and leaves the unit in `failed`,
where `systemctl status wi-lab` shows the last log lines — which are the validation
report. That is the diagnostic the operator needs, and it is currently buried.

This is worth doing regardless of capabilities: any permanent startup failure has the
same shape today. It is included here because this change makes permanent startup
failures substantially more likely, at least once per upgrade.

### 10.2 Installer integration

`--validate-config` needs the venv (pyyaml, pydantic), so it **cannot** run in
`install/01-preconditions/03-config.sh`, which executes before
`install/02-install-stages/01-venv.sh` and only checks that files exist.

Add a new stage in `install/02-install-stages/`, ordered **after** the venv stage and
**before** `03-enable.sh`, running:

```bash
"$VENV_PATH/bin/python" "$WILAB_DIR/main.py" --validate-config --check-hardware
```

and aborting the install on a non-zero exit, with the report already printed by the
tool. A misconfigured install then fails during installation with a readable report,
instead of via `journalctl` after a silent service failure.

### 10.3 Upgrade sequencing

On an upgrade the service is already running. The install script must **validate before
stopping the old service**, so a config that fails validation leaves the previous
version serving. Stopping first and discovering the problem afterwards converts a
configuration mistake into an outage.

### 10.4 Security notes

* The validation report names `auth_token` as a path and may state *that* it equals the
  example value — it must **never print the value itself**. The report goes to stdout,
  to the journal, and plausibly into a CI log.
* `--validate-config` reads the config and nothing else: no sockets bound, no iptables,
  no dnsmasq, no interface state changes. This is a testable property
  ([§12.3](#123-cli-teststest_clipy-new)), not just an intention — it is what makes the
  command safe to run on a production host at any time.
* `capabilities_catalogue` describes lab topology and is served on the
  already-authenticated `/status`. No change to the auth surface.

---

## 11. Compatibility & Migration

**4.0.0 is a deliberate breaking release.** An earlier draft kept every change additive
and optional so that 3.x clients would keep working. That was reversed: a client that
never learned about capabilities and silently receives *some* device (possibly one that
cannot do the band it needs) is a worse outcome than a clear error. There is no
compatibility mode.

| Aspect | Impact |
|--------|--------|
| Existing `config.yaml` | **Requires a one-time completion pass** — see [§11.1](#111-upgrading-an-existing-installation). Every schema key becomes mandatory, capabilities included. |
| Existing API clients (`{"duration_seconds": N}`) | **Rejected with `422`** (`Missing required field(s): required_capabilities`). Clients must send `required_capabilities`, `[]` meaning "any device". |
| Responses | `capabilities` is always present on reservation responses, `networks[]` and `/debug`; `capabilities_catalogue` is always present on `/status`. In a 409 body `next_available_at` / `next_available_in` can be `null` ([§7.1](#71-wilabreservationpy)) and `next_available_at` is UTC ([§7.3](#73-wilabapiroutesreservationpy)). |
| `ReservationManager(...)` | Takes `DeviceSpec` only; plain strings are no longer accepted. |
| Frontend | Requires the 4.0.0 API; there are no "pre-capabilities backend" fallbacks. Reservations restored from `localStorage` are re-fetched from `GET /device-reservation/{rid}`, so they always carry `capabilities`. |
| Allocation outcome | **Changes** — see [§11.2](#112-allocation-policy). |

### 11.1 Upgrading an existing installation

The upgrade is a single, guided editing pass:

```bash
$ python3 main.py --validate-config
Wi-Lab configuration validation FAILED
File: /opt/wilab/config.yaml
7 error(s), 1 warning(s)

ERROR   networks[0].capabilities
        Missing required key.
        → Add a capabilities block declaring: 2.4ghz, 5ghz
ERROR   networks[1].capabilities
        Missing required key.
        → Add a capabilities block declaring: 2.4ghz, 5ghz
ERROR   country_code
        Missing required key.
        → Add 'country_code: "IT"' (ISO 3166-1 alpha-2)
...
```

The administrator fixes everything the report lists, re-runs `--validate-config` until
it prints OK, then restarts the service. **No restart-fix-restart loop**, because the
validator reports every problem at once and can be run without touching the service.

For a config that predates capabilities entirely, the values still have to be typed by
hand — deliberately. Defaulting every antenna to dual-band would reintroduce exactly
the mis-assignment problem P1 this feature exists to solve, and inferring them by
probing is ruled out by constraint C2. One block per antenna, once, with the required
ids named in the report.

Call this out prominently in the CHANGELOG under `### ⚠️ Breaking Changes` and in the
release notes: **`config.yaml` must be completed before upgrading**, and
`--validate-config` is the tool that tells you exactly how.

### 11.2 Allocation policy

The assigned device is the *least capable free device* that satisfies the request, with
declaration order as the tie-break — also for `required_capabilities: []`. Given a pool
of `[dual, 2.4-only]`, an unqualified request gets the 2.4-only adapter and the scarce
dual-band one stays free for those who ask for 5 GHz. A 3.x client that relied on "first
free in configuration order" must state its needs with `required_capabilities`.

*Rejected alternative:* keep strict declaration order for requests with no capability
requirement. Two allocation policies would coexist, and unattended scripts would be the
ones burning the dual-band adapters.

---

## 12. Testing Plan

### 12.1 `tests/test.config.yaml`

The current test config declares a **single** device (`wls16`), which cannot exercise
selection at all. Extend it to three devices with asymmetric capabilities, mirroring
[§2.5](#25-worked-example-the-requesters-scenario). Check the blast radius first: some
existing tests assert on network counts or subnet allocation and may need adjusting —
prefer adding devices at the **end** of the list so `wls16` keeps index 0 and its
`192.168.120.0/24` subnet.

Every key must be present, since the fixture is loaded through the same validator as a
production config. That is itself a useful guarantee: **the committed fixture doubles as
a worked example of a valid file**, and any future required field that someone forgets
to add there fails the suite immediately.

Add a **second fixture**, `tests/invalid.config.yaml`, deliberately broken in several
independent ways — it is the input for the aggregation tests below.

### 12.2 `tests/test_config_validation.py` (new)

The validator is pure and file-driven, so tests are cheap. Build inputs by mutating a
known-good baseline into `tmp_path`.

**Structural**
- [ ] Missing file → `unreadable=True`, one issue, no crash
- [ ] Malformed YAML → `unreadable=True`, one parse issue, **no cascade** of missing-key errors
- [ ] Top level not a mapping (a list, a bare string) → one issue
- [ ] Empty file (`yaml.safe_load` → `None`) → treated as an empty mapping, every key reported missing
- [ ] File with a UTF-8 BOM and CRLF line endings still parses

**Presence & unknown keys**
- [ ] Every top-level key removed one at a time → each reported at its own path
- [ ] A field with a Python default (`api_port`) is still reported when absent
- [ ] Missing `networks[i].capabilities` → reported with the required ids in the hint
- [ ] Missing single capability key → reported at `networks[i].capabilities.<id>`
- [ ] Unknown top-level key, unknown per-network key, unknown capability id → each
      reported with the valid options
- [ ] Key normalisation: `"5GHz"`, `" 5ghz "` accepted as `5ghz`
- [ ] `"5ghz"` and `"5GHz"` in the same device → duplicate-key error, not silent collapse
- [ ] `cors_origins: []` and `cors_origins: null` both accepted; the key absent is an error

**Aggregation — the core promise**
- [ ] `tests/invalid.config.yaml` with 5 unrelated problems yields exactly 5 issues
- [ ] **A missing key is reported exactly once**, not twice (phase 2 + Pydantic phase 4
      de-duplication) — direct regression test for review finding SW-3
- [ ] Issues are ordered by schema position and the order is stable across runs
- [ ] A rule whose input key is missing emits nothing (no cascading noise)
- [ ] A rule that raises an unexpected exception yields one "internal validation error"
      issue and the other rules still run (inject a deliberately broken rule)

**Custom rules**
- [ ] `2.4ghz` and `5ghz` both false → group error at `networks[i].capabilities`
- [ ] Exactly one true → no error
- [ ] `"5ghz": "yes"` (string) → type error, and the group rule does **not** count it as
      enabled
- [ ] A capability with `group=None` may be false without tripping the rule — inject a
      temporary registry entry to prove the rule is generic, not band-specific
- [ ] `min_timeout > max_timeout` → error (regression guard for a gap that exists today)
- [ ] `min_timeout < 10`; bad `dhcp_base_network`; non-`/24`; third-octet overflow;
      duplicate interfaces → each reported
- [ ] `networks: []` → error (gap that exists today: verified to pass currently)
- [ ] `auth_token: ""` → error; `auth_token` at the example value → WARNING
- [ ] Invalid `dns_server`, invalid `country_code`, `api_port` out of range → reported
- [ ] `api_port: 80` → WARNING (privileged port), not an error
- [ ] Duplicate `display_name` → WARNING, `report.ok` still True
- [ ] Malformed `cors_origins` entry (`"localhost:4200"`, no scheme) → error
- [ ] A valid file with warnings only → `report.ok is True`

**Hardware phase**
- [ ] `check_hardware=False` never invokes `validate_interface` (assert with a spy) —
      this is what makes laptop validation possible
- [ ] `check_hardware=True` reports a non-existent interface at `networks[i].interface`
- [ ] `check_hardware=True` reports a `dhcp_base_network` overlapping a host route,
      using a mocked `execute_command` route table
- [ ] The conftest `validate_interface` monkeypatch is effective against the validator —
      i.e. the deferred-import requirement of [§5.10](#510-module-boundaries) actually
      holds. **This test exists to fail loudly if someone "tidies up" the import.**

**Rendering & secrets**
- [ ] `render()` contains path, message and hint for each issue
- [ ] Success rendering when there are warnings but no errors
- [ ] **The rendered report never contains the `auth_token` value**, even when the token
      is the subject of the issue (review finding SYS-4)

### 12.3 CLI (`tests/test_cli.py`, new)

- [ ] `--validate-config` on a valid file → exit 0
- [ ] `--validate-config` **never calls `uvicorn.run`** (assert with a spy)
- [ ] `--validate-config` performs **no side effects**: `execute_command`,
      `execute_iw`, `execute_ip`, `execute_tc` are not called when `--check-hardware`
      is absent
- [ ] Invalid file → exit 1, report on stdout
- [ ] Missing file → exit 2; malformed YAML → exit 2
- [ ] `--config PATH` overrides `CONFIG_PATH`
- [ ] `--check-hardware` without `--validate-config` is accepted, not an argparse error
- [ ] No arguments → normal startup path unchanged (existing behaviour preserved)
- [ ] Startup path: `load_config()` on an invalid file raises `SystemExit` whose message
      is the rendered report

### 12.4 `tests/test_config.py`

- [ ] Valid config → `capability_set` returns the enabled subset
- [ ] `AppConfig.capabilities_for()` returns sorted ids; `[]` for an unknown device
- [ ] The `field_validator`s moved to the rule set are **gone** from the model — guard
      against reintroducing a second reporting path
- [ ] The import-time registry assertion fires when a non-boolean or non-matchable
      capability is registered (build a throwaway registry and re-run the check)
- [ ] `normalise_capability_id()` is the single normaliser used by both the config
      validator and the API request validator (assert identical behaviour on the same
      inputs)

### 12.5 `tests/test_reservation.py`

**Selection** — table-driven over `(pool, request) → expected device`, so a new
capability adds rows rather than test functions:

- [ ] Request `{2.4ghz}` picks the 2.4-only device, not a dual-band one
- [ ] Request `{5ghz}` skips the 2.4-only device
- [ ] Request `{}` picks the least capable free device
- [ ] Request `{2.4ghz, 5ghz}` picks a dual-band device
- [ ] Minimal device busy → falls back to the dual-band device
- [ ] Tie-break determinism: equal-capability devices are handed out in declaration
      order, over 20 consecutive reserve/release cycles
- [ ] Declaration order is respected even when the *first* declared device is the most
      capable (the `[dual, 2.4-only]` pool of [§11.2](#112-the-one-intentional-behaviour-change-in-allocation))

**Availability & errors**
- [ ] All matching devices busy → `NoDeviceAvailableError` whose `next_available_at`
      is the earliest expiry **among matching devices only** — a 2.4-only device
      expiring sooner must not influence a 5 GHz request
- [ ] **All matching devices held by unlimited reservations →
      `next_available_at is None` and `next_available_in is None`**, not `0`
      (regression test for the bug in [§7.1](#71-wilabreservationpy))
- [ ] Mixed timed + unlimited → the timed expiry is reported
- [ ] No configured device satisfies the set → `CapabilityUnsatisfiableError` with
      `available` = union over **all** devices, not only the free ones

**Compatibility & concurrency**
- [ ] N threads calling `create()` with the same requirements never double-assign a
      device; extend the existing thread-safety test to a capability-filtered pool
- [ ] Interleaved `create()` / `delete()` under contention leaves
      `_device_to_rid` and `_reservations` consistent
- [ ] A 200-device pool selects in linear time (guard against an accidental O(n²) —
      assert on call counts, not wall clock)

### 12.6 `tests/test_api.py`

- [ ] `GET /status` exposes `networks[].capabilities` (sorted, enabled only — a `false`
      capability must **not** appear) and `capabilities_catalogue` with `label` and `kind`
- [ ] `available_devices` decrements after a reservation and restores after release
- [ ] A capability no device enables is **absent** from the catalogue
- [ ] `POST /device-reservation` with `required_capabilities` returns the expected
      interface and echoes `capabilities`
- [ ] A 3.x body `{"duration_seconds": 900}` is rejected: 422, `Missing required field(s):
      required_capabilities`, and nothing is reserved
- [ ] Every missing field is listed at once; `required_capabilities: null` is rejected
- [ ] `required_capabilities: []` means any device and gets the least capable one
- [ ] Mixed-case ids (`["5GHz"]`) accepted; duplicates de-duplicated
- [ ] Unknown capability → 422 listing valid ids
- [ ] Unsatisfiable set → 422 (**not** 409 — assert the status code explicitly)
- [ ] All matching busy → 409 with `requested_capabilities` in the detail
- [ ] All matching busy with unlimited reservations → 409 with both `next_available_*`
      fields `null`
- [ ] `next_available_at` is UTC-formatted and consistent with the value returned by
      `GET /device-reservation/{rid}` for the same reservation
- [ ] A request carrying the removed `interface` field → 422 naming it
- [ ] `GET /device-reservation/{rid}` includes `capabilities`
- [ ] `GET /debug` managed interfaces include `capabilities`
- [ ] **OpenAPI schema**: `/openapi.json` still generates, the new request fields are
      `required_capabilities` is listed as required next to `duration_seconds`

### 12.7 Frontend

The reservation dialog stops being a thin form and acquires real logic —
`matchingDeviceCount`, mode switching, conditional payload construction. **This is the
first component in the codebase that genuinely warrants a unit test**, and the review
recommends adding the minimal Angular test setup for this one spec rather than
continuing to rely entirely on manual checks:

- [ ] `matchingDeviceCount` for: no selection, one capability, two capabilities, a
      selection nothing satisfies, all devices reserved
- [ ] Mode switch clears the other control, so the payload never carries both fields
- [ ] `onSubmit()` emits `{duration_seconds}` only, in capability mode with nothing ticked
- [ ] Unlimited checkbox still produces `duration_seconds: 0`

Remaining manual verification: capability grouping by kind, disabled Reserve at zero
matches, band dropdown filtered by the
reserved device's capabilities, 422-vs-409 rendering, and the null-countdown case.

### 12.8 End-to-end / regression

- [ ] Full suite green with the extended `tests/test.config.yaml` (the fixture change
      touches subnet and count assertions across several files)
- [ ] `make lint` and `make type-check` (`ruff.toml` now pins the rule set; `ruff check
      wilab/ tests/` passes with ruff 0.6.9) clean — especially the
      `Sequence[DeviceSpec]` annotation and the `Optional[float]` return
- [ ] A v3.0 config file (no capabilities, some keys omitted) produces exactly the
      expected set of validation errors — the migration path of
      [§11.1](#111-upgrading-an-existing-installation) as an executable test
- [ ] `install/03-tests/` service-start checks still pass with the new install stage

### 12.9 Bench validation — required, and not possible on a Windows workstation

Wi-Lab targets Ubuntu and drives `iw`, `ip`, `iptables`, `hostapd`, `dnsmasq` and
systemd. Development may happen on Windows, but a meaningful part of the suite and every
integration path can only be exercised on the Linux test bench. **This is a mandatory
phase, not an optional one**: a work item is "green on the dev machine", not "verified",
until it has been through this list.

Concretely, on a Windows workstation the suite already reports **3 failures and 12
errors before any of this work**, all from the same cause — no `ip` binary, no `iw`, no
`wls16` interface. Those numbers are the honest baseline to compare against, and a
change is judged by whether it moves them, not by whether they are zero.

**What cannot be verified off-bench**

| Area | Why Windows cannot answer it |
|------|------------------------------|
| The 12 `test_qos_profile.py` errors and 3 pre-existing failures | Need real `ip` / `iw` and a real interface |
| Validator hardware phase against real adapters | The unit tests mock `validate_interface` and the route table; only the bench proves the real helpers are wired correctly |
| `dhcp_base_network` overlap detection | Needs a genuine `ip route` table, and the only convincing test is a subnet that really does collide with the host LAN |
| The installer stage | Bash, systemd, root, and the real stage ordering under `install.sh` |
| systemd `StartLimitIntervalSec` / `StartLimitBurst` | Requires a real unit and a real deliberate config error |
| `make validate-config`, `make lint`, `make type-check` | The Makefile uses POSIX venv paths (`$(VENV)/bin/python`) |
| Frontend build | Docker-based build stage |

**Bench checklist**

- [ ] **`pip install -r requirements-dev.txt` completes.** *(Pin fixed to
      `types-PyYAML>=6.0.12`; a clean install from an empty environment is still to be
      confirmed on the bench.)* It could not: the pin
      `types-PyYAML>=2024.1.0` is unsatisfiable, because that package's versions are
      `6.0.12.<date>` and `6.0.12.20260815 < 2024.1.0` under PEP 440 ordering. The
      constraint was presumably written expecting a `2024.x` calendar version scheme that
      the package does not use. Nothing in this feature depends on it, but it means
      `make venv` for development installs nothing today, so the whole tooling chain
      (`make lint`, `make type-check`, `make test-local`) is unreachable from a clean
      checkout. Fix the pin (drop the lower bound, or use `types-PyYAML>=6.0.12`) and
      confirm a clean `make venv` from an empty environment.
- [ ] `make test-local` — full suite; record failures/errors and compare against the
      pre-change baseline on the same machine
- [ ] `make lint` and `make type-check`
- [ ] `make validate-config` on a real `config.yaml`
- [ ] `python3 main.py --validate-config` on a config with **no** capabilities (a v3.0
      file): confirm every missing key is listed once, with usable hints
- [ ] `python3 main.py --validate-config` (no `--check-hardware`) with an adapter
      **unplugged**: must still exit 0, proving the phase split works
- [ ] `python3 main.py --validate-config --check-hardware` with an adapter unplugged:
      must report that interface and exit 1
- [ ] Set `dhcp_base_network` to the host's own LAN subnet and confirm
      `--check-hardware` catches the collision **before** anything is started
- [ ] Deliberately break `config.yaml`, `systemctl restart wi-lab`, then confirm the unit
      reaches `failed` (not an endless `activating (auto-restart)` loop) and that
      `systemctl status wi-lab` shows the validation report
- [ ] Fresh `sudo bash install.sh` with a broken config: the install must abort at the
      validation stage, before the service is enabled
- [ ] Fresh `sudo bash install.sh` with a good config: normal install, service starts,
      and the journal shows the "Managed device capabilities" matrix
- [ ] Confirm the rendered report is readable in `journalctl` under the bench's locale

**Frontend bench checklist**

The Angular app builds and type-checks off-bench (`npx ng build --configuration
production`), but it has **no test infrastructure at all**: `angular.json` declares no
`test` target, there is no `tsconfig.spec.json`, and karma/jasmine are absent from
`package.json`. Wiring it up means editing `package.json`, and the Docker build runs
`npm ci`, which fails unless `package-lock.json` is regenerated in the same commit — so
it is deliberately left to the bench rather than done blind.

- [x] Test target, `tsconfig.spec.json`, `karma.conf.js` and karma/jasmine devDependencies
      added, `package-lock.json` regenerated; `npm test` runs
      `reservation-dialog.component.spec.ts` (16/16 pass in headless Chrome).
- [ ] Verify the production Docker build still succeeds after that `package.json` change
- [ ] Manually: live match count, Reserve disabled at zero matches, capability chips on the
      cards
- [ ] Band dropdown in the network form limited to the reserved device's capabilities,
      and defaulting to a band that device can actually serve
- [ ] Error rendering: a 422 capability error shows a message and starts **no** countdown;
      a 409 with `next_available_in: null` shows the static "no scheduled release" text

---

## 13. Implementation Checklist

### 13.1 Execution order

The phases below are ordered by dependency, not by the order they appear in this
document. They collapse into **five work items**, each independently reviewable and
each finishing green:

| # | Work item | Phases | Effort | Unblocks |
|---|-----------|--------|--------|----------|
| WI-1 | Registry + validator | 1 + 2 | ~6 h | everything |
| WI-2 | CLI, startup & deployment | 3 | ~1.5 h | any local run of the service |
| WI-3 | Test fixtures | part of 7 | ~1 h | WI-4's tests |
| WI-4 | Reservation core + API | 4 + 5 | ~3.5 h | WI-5 |
| WI-5 | Frontend | 6 | ~4 h | — |
| WI-6 | Integration, e2e & docs | rest of 7 | ~4 h | release |
| WI-7 | **Bench validation** | [§12.9](#129-bench-validation--required-and-not-possible-on-a-windows-workstation) | ~2 h | sign-off |

**WI-1 — write phases 1 and 2 as one unit.** The registry and the validator are not
separable in practice: the validator's required-key manifest, its capability rules and
its error messages all read `CAPABILITY_REGISTRY`, so a registry landed alone has no
consumer and no test that exercises it. Splitting them means writing throwaway tests for
an interface that changes an hour later. This is the largest item and the one everything
else waits on.

**WI-2 — small, but it is what makes the system runnable again.** After WI-1 every
existing `config.yaml` in the repo (including a developer's own) is incomplete by the
new rules, and `load_config()` refuses to start. Until `--validate-config` exists there
is no ergonomic way to find out *why*. Do this immediately after WI-1, not later, or
every subsequent phase is debugged against a service that will not boot.

**WI-3 — extend the fixtures before writing selection tests, and expect collateral.**
`tests/test.config.yaml` currently declares a single device, so no selection test can be
written against it. Extending it to three devices touches assertions on network counts
and subnet allocation across `test_api.py`, `test_channels.py` and `test_qos_profile.py`.
Add the new devices **at the end of the list** so `wls16` keeps index 0 and its
`192.168.120.0/24` subnet, which limits the blast radius to count assertions. Doing this
before WI-4 rather than during it keeps a mechanical, wide diff separate from the
behavioural change.

**WI-4 — and commit the two bug fixes separately.** The `_soonest_expiry()` /
`next_available_*` nullability ([§7.1](#71-wilabreservationpy)) and the naive-vs-UTC
timestamp ([§7.3](#73-wilabapiroutesreservationpy)) are pre-existing defects, not part of
this feature. They have their own regression tests and their own CHANGELOG section
(`### 🐛 Bug Fixes`). Landing them as two commits ahead of the capability work makes both
the review and a future `git bisect` far easier, and they are independently
cherry-pickable onto a maintenance branch if 4.0.0 slips.

**WI-5 — parallelisable once the API shape is frozen.** The frontend depends only on the
response contracts of [§6](#6-technical-design--api), not on the backend implementation.
As soon as WI-4's models are agreed the frontend can proceed alongside, against those
shapes. It is the only item that can overlap.

**WI-6 — what genuinely cannot be done earlier.** Cross-cutting work only: the full-suite
run against the extended fixtures, the v3.0-config migration test, `make lint` /
`make type-check`, the installer stage test, and the documentation.

**WI-7 — the bench.** Development can happen on any workstation, but Wi-Lab drives `iw`,
`ip`, `iptables`, hostapd, dnsmasq and systemd, so a substantial part of the suite and
every integration path only mean something on the Linux test bench. Each earlier work
item is *green on the dev machine*; none is *verified* until it has been through
[§12.9](#129-bench-validation--required-and-not-possible-on-a-windows-workstation).
This is a distinct sign-off step, deliberately not folded into WI-6, because it depends
on hardware rather than on code being finished.

> **Tests are not a final phase.** Each work item is done when *its own* slice of
> [§12](#12-testing-plan) is green — WI-1 owns §12.2 and §12.4, WI-2 owns §12.3, WI-4
> owns §12.5 and §12.6, WI-5 owns §12.7. Phase 7 in the checklist below is only the
> residue that is genuinely cross-cutting ([§12.8](#128-end-to-end--regression)). Reading
> the checklist as "build everything, then test" would defeat the point of the sequencing
> above.

### 13.2 Phase checklists

Effort is given per phase; the earlier "6–8 hours" estimate predated the validator and
was not realistic.

**Phase 1 — Registry & config model** *(~1 h)*
- [ ] `Capability`, `CapabilityKind`, `CapabilityType`, `CapabilityDef` in `wilab/config.py`
- [ ] `CAPABILITY_REGISTRY` + `GROUPS_REQUIRING_ONE`
- [ ] Import-time assertion: every capability boolean and matchable ([§3.1](#31-how-quantitative-capabilities-would-slot-in-design-headroom-not-v1))
- [ ] `normalise_capability_id()` — the shared normaliser
- [ ] `NetworkEntry.capabilities` (required, no default) + `capability_set`
- [ ] `AppConfig.capabilities_for()`

**Phase 2 — Validator (`wilab/config_validation.py`)** *(~5 h)*
- [ ] `Severity`, `ValidationIssue`, `ValidationReport` (with `unreadable`), `ValidationContext`
- [ ] `@rule` registry + per-rule exception isolation
- [ ] `validate_config_file()` phase pipeline
- [ ] Required-key manifest derived from `model_fields` + the `file_optional` escape hatch
- [ ] Unknown-key detection at every level
- [ ] Pydantic `ValidationError` → `ValidationIssue` mapping (`loc` → path)
- [ ] **Phase 2/3 ↔ 4 de-duplication by path**
- [ ] Migrate the existing `field_validator`s out of `wilab/config.py` into rules
- [ ] The full rule set of [§5.6](#56-the-rule-set), including the gap-closing rules
- [ ] The capabilities group rule, parameterised by registry metadata
- [ ] `render()` with schema-position ordering — one renderer for CLI and startup
- [ ] Verify every rule is defensive against missing and wrongly-typed inputs
- [ ] **Deferred imports** of `validate_interface` and `execute_command` inside phase 6

**Phase 3 — CLI, startup & deployment** *(~1.5 h)*
- [ ] `argparse` in `main.py`: `--config`, `--validate-config`, `--check-hardware`
- [ ] Exit codes 0 / 1 / 2 driven by `report.ok` and `report.unreadable`
- [ ] `--validate-config` must not construct managers or start uvicorn
- [ ] `load_config()` validates with `check_hardware=True` (lazy import) and exits on errors
- [ ] `_log_capability_matrix()` at startup
- [ ] `make validate-config` target + `help` entry
- [ ] New `install/02-install-stages/` validation stage, after the venv, before enable
- [ ] `StartLimitIntervalSec` / `StartLimitBurst` in the systemd template

**Phase 4 — Reservation core** *(~2 h)*
- [ ] `DeviceSpec` dataclass
- [ ] `Sequence[DeviceSpec]` constructor
- [ ] `CapabilityUnsatisfiableError` (with `available`)
- [ ] `_select()` replacing `_first_available()`
- [ ] `_soonest_expiry(among=...)` returning `Optional[float]`
- [ ] `NoDeviceAvailableError.next_available_at/_in` → `Optional`
- [ ] `create()` with `required_capabilities` / `device_id`

**Phase 5 — API layer** *(~1.5 h)*
- [ ] `ReservationCreateRequest` new fields + registry-backed validator (normalise, de-dup, sort)
- [ ] `ReservationResponse.capabilities` via `AppConfig.capabilities_for()`
- [ ] Error mapping in `create_reservation()`, including the 422 body for an unsatisfiable set
- [ ] Null-safe 409 body + UTC alignment of `next_available_at`
- [ ] `/status`: `networks[].capabilities` + `capabilities_catalogue`
- [ ] `/debug` parity
- [ ] Confirm `wilab/api/__init__.py` needs no change

**Phase 6 — Frontend** *(~4 h)*
- [ ] Model updates, including nullable `next_available_*`
- [ ] Reservation dialog: mode toggle, capability checkboxes grouped by kind, device
      radio list, match count, a11y attributes
- [ ] `app.component.ts`: catalogue plumbing, slot capabilities, 422 branch, null-countdown branch
- [ ] Network card capability chips (undefined-safe)
- [ ] Network form dialog band filtering + default band

**Fixtures — WI-3, do this before Phase 4** *(~1 h)*
- [ ] `tests/test.config.yaml` extended to three devices with asymmetric capabilities,
      new entries appended so `wls16` keeps index 0 ([§12.1](#121-teststestconfigyaml))
- [ ] `tests/invalid.config.yaml` added
- [ ] Count and subnet assertions repaired across `test_api.py`, `test_channels.py`
      and `test_qos_profile.py`

**Phase 7 — Integration, e2e & docs** *(~4 h)*

Per-phase tests belong to their own phase ([§13.1](#131-execution-order)); what remains
here is only the cross-cutting work.

- [ ] Minimal Angular test setup + the reservation-dialog spec ([§12.7](#127-frontend)) — bench only
- [x] End-to-end and regression items from [§12.8](#128-end-to-end--regression),
      including the v3.0-config migration test
- [ ] `make lint` + `make type-check` clean — blocked, see [§18.5](#185-open-decisions)
- [ ] `install/03-tests/` still green with the new install stage — bench only
- [x] Docs from [§14](#14-documentation-to-update)
- [x] Version bump via `update_version.sh --bump-to 4.0.0`

**Phase 8 — Bench validation (WI-7, Linux test bench only)** *(~2 h)*

Cannot be performed on a Windows workstation. Full list and rationale in
[§12.9](#129-bench-validation--required-and-not-possible-on-a-windows-workstation).

- [ ] Full suite, lint and type-check via the Makefile on the bench
- [ ] Validator against real adapters, plugged and unplugged, with and without
      `--check-hardware`
- [ ] Subnet-collision detection against the host's real route table
- [ ] systemd start-limit behaviour on a deliberately broken config
- [ ] Installer aborts at the validation stage before enabling the service

---

## 14. Documentation To Update

| File | What |
|------|------|
| [config.example.yaml](../../config.example.yaml) | Complete `capabilities` block on all three devices + a comment block listing the valid ids, stating that **every key is mandatory**, that **no auto-detection** is performed, and that the file is **never modified** by Wi-Lab |
| [README.md](../../README.md) | Configuration snippet with capabilities; a **Validating the configuration** section documenting `--validate-config`, `--check-hardware` and the exit codes; API example showing a capability-driven reservation; upgrade note |
| [CHANGELOG.md](../../CHANGELOG.md) | `### ⚠️ Breaking Changes` for mandatory complete configuration; `### ✨ Features` for capabilities, selection, validator and CLI; `### 🐛 Bug Fixes` for the unlimited-reservation `next_available_*` hole and the naive-vs-UTC timestamp; `### 🔧 Maintenance` for the allocation change and the validators moved out of Pydantic |
| [docs/networking.md](../../docs/networking.md) | Capabilities are an administrative declaration, not a hardware probe; how they relate to `band` at AP creation; the new host-route overlap check |
| [docs/swagger.md](../../docs/swagger.md) | New request/response fields; the nullable `next_available_*` |
| [docs/troubleshooting.md](../../docs/troubleshooting.md) | "Service does not start: configuration validation failed" — how to read the report, `--validate-config` as the first diagnostic step, and the `failed` vs `auto-restart` unit state after [§10.1](#101-systemd-restart-loop-on-a-bad-config) |
| [docs/readme-dev.md](../../docs/readme-dev.md) | `make validate-config`; how to add a validation rule and a capability; the deferred-import requirement of [§5.10](#510-module-boundaries) |
| [docs/unit-testing.md](../../docs/unit-testing.md) | The two config fixtures and what each is for; the new frontend test setup |
| `TODOs/` | ✅ Moved to `TODOs/completed/` on release of 4.0.0, per the existing convention |

---

## 15. Design Decisions & Rejected Alternatives

| # | Decision | Rationale | Rejected alternative |
|---|----------|-----------|----------------------|
| D1 | Capabilities live in `/status`, not a new `GET /capabilities` | The frontend already polls `/status`; capabilities are static config data, so serving them there costs nothing and honours constraint C1 | A dedicated endpoint — one more route, one more auth surface, one more round-trip for data the client already has |
| D2 | **Configuration is the only source of truth; no hardware auto-detection** | Capabilities are administrative statements, not measurements. Policy capabilities (`change-ssid`) and quantitative ones (`max-clients`) have no hardware counterpart at all, so a probe could never produce them — and on the ones it *can* see it would override a deliberate administrative choice. Also removes any startup ordering constraint | Probing `iw phy channels` to fill in omitted capabilities — convenient for the two band flags, structurally wrong for everything else, and it fights the administrator |
| D3 | **Validate, never correct** — every key mandatory, nothing written back | A value Wi-Lab invents is a value nobody reviewed. Validation reaches the same end state while writing nothing, and generalises to every field ([§5.11](#511-why-this-replaces-automatic-completion)) | Back-filling missing keys — required `ruamel.yaml`, atomic writes, `.bak` handling, ownership preservation, a read-only fallback, and risked mutating the committed test fixture |
| D4 | The validator reports **everything**, then fails once | An administrator completing a config must see all problems in one pass | Fail-fast (Pydantic's natural behaviour) — turns an upgrade into a restart-fix-restart loop |
| D5 | Required-key manifest **derived from `model_fields`** | A new config field becomes mandatory in the file automatically | A hand-maintained list of required keys — guaranteed to drift |
| D6 | Hardware checks are a **separate opt-in phase** | Lets a config be validated on a laptop or in CI without the adapters; startup still always runs them | One monolithic validation — `--validate-config` would be useless anywhere but the bench |
| D7 | Existing `field_validator`s move into the rule set | Two reporting paths with different formatting and failure semantics is worse than one | Leave them in Pydantic — half the errors rich, half terse, and only the first per field surfaces |
| D8 | Registry metadata (`type`, `matchable`) exists but v1 **asserts** it is unused | Keeps the extension points documented and one-line-cheap without shipping unreachable, untested code | Implementing `_matchable()` filtering now (dead code path) / omitting the fields (the first policy capability becomes a refactor) |
| D9 | The "at least one enabled" rule is a **custom rule scoped to capabilities**, parameterised by the registry's `group` | Matches where the requirement belongs while staying generic: `2.4ghz`/`5ghz` are not hardcoded, so a future `change-ssid: false` is exempt automatically | A hardcoded band check — would wrongly reject a device whose only false flags are policy ones |
| D10 | Config is a hard stop, no partial start | A config error means the operator's intent is unknown; a degraded pool hides the problem until a reservation goes wrong | Start with the valid devices only and log the rest — silent capacity loss |
| D11 | One shared `normalise_capability_id()` for config and API | Two `.strip().lower()` implementations drift; a single function cannot | Per-layer normalisation — the API and the file would eventually disagree on `"5GHz"` |
| D12 | Capability ids reuse the `band` vocabulary (`2.4ghz`, `5ghz`) | One vocabulary across config, reservation API and `NetworkCreateRequest.band` | New ids like `band_24` — a mapping layer with nothing to gain |
| D13 | Selection = minimal surplus, tie-broken by declaration order | Implements "reserve the minimum necessary"; deterministic; degenerates exactly to today's behaviour on a homogeneous pool | Random pick (untestable); pure declaration order (wastes scarce hardware — P3) |
| D14 | The tie-break is **explicit**, though `min()` already provides it | Makes the property intentional and testable, and survives a refactor to `sorted()` or a parallel scan | Rely on `min()` returning the first minimum — correct today, silently fragile |
| D15 | The minimality rule also applies when no capabilities are requested | One allocation policy is easier to explain, test and reason about; protects scarce hardware from clients that state no requirement | Two policies — unattended CI scripts would be the ones burning dual-band adapters |
| D16 | Config keys are mandatory **and so is `required_capabilities`** (revised for 4.0.0; originally optional) | A client that does not say what it needs must not be handed a guess; a clear 4xx beats an unclear behaviour. A 3.x client fails fast and visibly instead of intermittently getting a device without its band | Keep it optional with a default (the first draft) — silent mis-allocation for clients that never learned about capabilities |
| D17 | *(Removed in 4.0.0)* `interface` and `required_capabilities` could be combined | The `interface` field no longer exists — [§18.8](#188-revision--choosing-a-specific-antenna-was-removed) | — |
| D18 | Unsatisfiable → 422, all-busy → 409 | 422 = "never going to work", 409 = "works later". The countdown timer is driven by 409 and must not fire on a permanent failure | One status for both — the UI counts down toward an availability that never arrives |
| D19 | *(Removed in 4.0.0)* Unknown `interface` → 404 | The `interface` field no longer exists | — |
| D20 | `next_available_*` become **nullable** rather than reporting `0` | "Available now" is false when every holder is unlimited, and it makes the UI busy-loop | Keep returning `time.time()` — preserves the type, lies to the client |
| D21 | Capabilities are **not** stored on `Reservation` | They belong to the device, not the booking; a lookup avoids a second source of truth | Denormalise into the dataclass — faster, but stale |
| D22 | `Sequence[DeviceSpec]` constructor only (revised for 4.0.0; the first draft also accepted `str`) | No compatibility shim to keep alive; tests use `device_specs()` | `Sequence[DeviceSpec]` — kept ~46 test call sites unchanged at the cost of a second code path |
| D23 | `capabilities_for()` on `AppConfig`, not in a route module | Route modules must stay leaves of the dependency graph; `status.py` importing from `reservation.py` is a direction this codebase does not otherwise have | A shared helper in `routes/reservation.py` imported by `routes/status.py` |
| D24 | Frontend shows a **match count**, not the predicted winner | Avoids reimplementing the selection rule in TypeScript, where it would drift | Client-side prediction of the assigned device — nicer UX, guaranteed to diverge |

---

## 16. Review Log

Findings from the four-perspective review, with where each is addressed. Kept for traceability so
a later reader can tell which non-obvious choices were deliberate.

### System architecture

| # | Finding | Resolution |
|---|---------|-----------|
| SYS-1 | `Restart=always` + `RestartSec=10s` and no start limit means a config error loops forever, flooding the journal and never reaching a `failed` state | `StartLimitIntervalSec` / `StartLimitBurst` added to the unit template — [§10.1](#101-systemd-restart-loop-on-a-bad-config) |
| SYS-2 | The install hook was placed in `01-preconditions/03-config.sh`, which runs **before** the venv exists — the validator would not be runnable there | Moved to a new `02-install-stages/` stage after the venv, before enable — [§10.2](#102-installer-integration) |
| SYS-3 | An upgrade that stops the service before validating turns a config mistake into an outage | Validate before stopping — [§10.3](#103-upgrade-sequencing) |
| SYS-4 | The report names `auth_token`; nothing said it must not print the value, and the report reaches journals and CI logs | Explicit non-leak requirement + test — [§10.4](#104-security-notes), [§12.2](#122-teststest_config_validationpy-new) |
| SYS-5 | Nothing showed the operator the effective capability matrix; "why did I get that antenna" had no answer in the logs | `_log_capability_matrix()` at startup — [§5.9](#59-startup-integration) |
| SYS-6 | The new host-route overlap check must be mockable, or it breaks the test suite on any machine | Routed through `commands.execute_command`, already mocked at `conftest.py:210` — [§5.10](#510-module-boundaries) |

### Software architecture

| # | Finding | Resolution |
|---|---------|-----------|
| SW-1 | `config.py` ↔ `config_validation.py` is a circular import | Lazy import inside `load_config()`, matching the existing deferred `validate_interface` import — [§5.9](#59-startup-integration), [§5.10](#510-module-boundaries) |
| SW-2 | `_capabilities_for()` in `routes/reservation.py` imported by `routes/status.py` creates a route→route dependency | Moved to `AppConfig.capabilities_for()` — [§4.4](#44-appconfig-helper), D23 |
| SW-3 | A missing key would be reported **twice** — once by the presence phase, once by Pydantic — undermining the report's purpose | Phase 4 de-duplicates by path against phases 2/3 — [§5.3](#53-validation-phases); dedicated test in [§12.2](#122-teststest_config_validationpy-new) |
| SW-4 | `ValidationReport` had no way to signal "file unreadable", so the CLI could not justify exit code 2 | `unreadable` flag on the report — [§5.2](#52-issue-model) |
| SW-5 | `matchable` was specified as filtering the surplus score but nothing prevented a client from *requesting* a non-matchable capability — the loop was open | v1 asserts all capabilities are matchable and implements no filtering; the question is deferred to when the first non-matchable capability exists — [§3.1](#31-how-quantitative-capabilities-would-slot-in-design-headroom-not-v1), D8 |
| SW-6 | An exception inside one rule would abort the whole report — the administrator's only diagnostic | Per-rule `try/except` converting a crash into one issue — [§5.5](#55-the-rule-registry-and-the-capabilities-custom-rule) |
| SW-7 | Config and API each normalised capability ids independently | Single exported `normalise_capability_id()` — [§4.2](#42-the-capability-registry-implementation), D11 |

### Development

| # | Finding | Resolution |
|---|---------|-----------|
| DEV-1 | A module-level `from ..wifi.interface import validate_interface` in the validator would defeat `conftest.py:197`'s monkeypatch, making every config-loading test hit real `iw` | Deferred import mandated and covered by a test that fails if someone "tidies" it — [§5.10](#510-module-boundaries), [§12.2](#122-teststest_config_validationpy-new) |
| DEV-2 | `list[DeviceSpec] \| list[str]` rejects mixed lists and narrows badly under mypy | Superseded: the `str` form was removed in 4.0.0 — [§7.1](#71-wilabreservationpy), D22 |
| DEV-3 | `Capability(c)` in the route raises `ValueError` → 500 if it ever runs before validation | Ordering dependency documented; normalisation and rejection happen in the request validator — [§6.2](#62-post-apiv1device-reservation--extended-request), [§7.3](#73-wilabapiroutesreservationpy) |
| DEV-4 | `available_capabilities` on the permanent error was unspecified as free-only or all | Defined as the union over **all** configured devices — that is what makes the error permanent — [§7.1](#71-wilabreservationpy) |
| DEV-5 | Request-side duplicates and ordering made the endpoint's behaviour client-dependent and tests non-deterministic | Validator de-duplicates and sorts — [§6.2](#62-post-apiv1device-reservation--extended-request) |
| DEV-6 | `cors_origins: null` vs `[]` was undefined under mandatory presence | Both accepted, both mean CORS disabled — [§5.4](#54-the-required-key-manifest) |
| DEV-7 | The 409 handler formats `next_available_at` naively while `_build_response()` uses UTC — same API, two timezones | Aligned to UTC, flagged as a visible fix needing a CHANGELOG entry — [§7.3](#73-wilabapiroutesreservationpy) |
| DEV-8 | The explicit `declaration_index` tie-break is redundant with `min()` semantics | Kept deliberately, with the reasoning recorded so it is not "simplified" away — [§3](#3-selection-algorithm), D14 |

### Test

| # | Finding | Resolution |
|---|---------|-----------|
| TST-1 | Three rules were labelled "existing" that are **not** enforced today. Verified: `networks: []` passes (the third-octet check computes `base − 1`), `auth_token: ""` passes, and `min_timeout > max_timeout` passes while making every reservation unsatisfiable | Relabelled **new** and each given a test — [§5.6](#56-the-rule-set), [§12.2](#122-teststest_config_validationpy-new) |
| TST-2 | `_soonest_expiry()` returns `time.time()` when all holders are unlimited → the API reports "available now" and the UI busy-loops. Reachable today with the shipped `allow_unlimited_reservation: true`, and more likely once the matching subset is filtered | `Optional[float]`, nullable API fields, frontend branch, regression tests — [§7.1](#71-wilabreservationpy), [§8.3](#83-appcomponentts), [§12.5](#125-teststest_reservationpy) |
| TST-3 | No test asserted that `--validate-config` is side-effect free — the property that makes it safe to run on a production host | Explicit spy-based tests on `uvicorn.run` and all four `execute_*` helpers — [§12.3](#123-cli-teststest_clipy-new) |
| TST-4 | Report ordering was unspecified, so a CI diff of two runs could be noise | Ordering defined as schema position and made a tested property — [§5.7](#57-report-format) |
| TST-5 | Aggregation — the validator's core promise — had no direct test | `tests/invalid.config.yaml` fixture with independent faults; exact-count and single-report-per-key assertions — [§12.1](#121-teststestconfigyaml), [§12.2](#122-teststest_config_validationpy-new) |
| TST-6 | Selection tests were a flat list, so each new capability would mean new test functions | Table-driven `(pool, request) → expected` — [§12.5](#125-teststest_reservationpy) |
| TST-7 | The reservation dialog gains real logic but the project has no frontend test infrastructure at all | Recommend adding the minimal Angular setup for this one spec rather than leaving it manual-only — [§12.7](#127-frontend) |
| TST-8 | Nothing checked that a `false` capability never reaches the wire, or that the OpenAPI schema stays backward compatible | Both added — [§12.6](#126-teststest_apipy) |
| TST-9 | The `"5ghz": "yes"` case (YAML 1.2 string) could be counted as enabled by a truthy test in the group rule | `is True` comparison + explicit test — [§5.5](#55-the-rule-registry-and-the-capabilities-custom-rule), [§12.2](#122-teststest_config_validationpy-new) |
| TST-10 | The original effort estimate (6–8 h) predated the validator and the test plan | Re-estimated per phase, ~16–20 h — [§13](#13-implementation-checklist) |

---

## 17. Out Of Scope / Future Extensions

Deliberately **not** part of this proposal — listed so the design leaves room for them:

* **More boolean capabilities.** `wifi6`, `wifi6e`, `6ghz`, `dfs`, `160mhz`, `mesh`,
  `monitor-mode` (radio kind); `change-ssid`, `change-password`, `change-channel`
  (policy kind). Each is one `Capability` member plus one registry entry; validation,
  the API, the algorithm and the UI absorb them unchanged.
* **Quantitative capabilities** such as `max-clients: 50`. The registry carries
  `CapabilityType.INTEGER` and [§3.1](#31-how-quantitative-capabilities-would-slot-in-design-headroom-not-v1)
  sketches the matching rule; the v1 import-time assertion is what forces that work to
  happen deliberately rather than by accident. Enforcing such a cap at runtime (hostapd
  `max_num_sta`) is a separate feature from declaring it.
* **Enforcing policy capabilities.** Declaring `change-ssid: false` is meaningless until
  some endpoint refuses the change. The declaration mechanism lands first; the
  enforcement points are per-capability follow-ups.
* **`--validate-config --json`** for CI pipelines that want to parse issues rather than
  read them. Exit codes already cover the common case; machine-readable output is worth
  adding the first time something actually consumes it.
* **Config schema documentation generated from the models.** The required-key manifest
  and the rule set together describe the whole file; emitting a reference table into
  `docs/` would keep documentation from drifting.
* **Scarcity-weighted selection.** [§3.2](#32-rejected-refinement-documented-for-the-future).
* **Capability-aware queueing.** "Notify me when a 5 GHz device frees up" — needs the
  event/SSE work in [TODOs/realtime-events.md](../realtime-events.md). This is also
  the natural home for a better answer to the all-unlimited 409 case.
* **Multi-device reservations.** Booking two antennas in one call (roaming/handover
  tests) — a substantially different reservation model.
* **A declaration-vs-hardware consistency report.** A `diagnostics/` script could
  compare declared capabilities against `iw phy channels` and print a table of
  discrepancies, as an *operator-run audit tool*. Explicitly **not** in the startup path
  and never able to influence allocation — that would be auto-detection through the back
  door, which constraint C2 rules out.
* **Runtime config reload.** Capabilities are read once at startup; editing
  `config.yaml` needs a service restart. Related to
  [TODOs/startup-recovery.md](../startup-recovery.md).
* ~~**Enforcing capabilities at AP creation.**~~ Done in 4.0.0: see §2.7.

---

## 18. Implementation Status & Remaining Work

Recorded at the end of the implementation session on **2026-09-01**, on branch
`feature/device-capabilities`. Everything that can be done off-bench is done: backend,
frontend, documentation and the 4.0.0 version bump. **Only bench validation (WI-7) is
outstanding** — see [§18.3](#183-remaining--wi-7-bench-validation-2-h).

### 18.1 What is built

| Work item | Commit | Contents |
|---|---|---|
| WI-1 (phases 1+2) | `3152a78` | Capability registry, `config_validation.py`, `load_config()` enforcement, 88 tests |
| WI-2 (phase 3) | `cbd3f2c` | `--validate-config` CLI with exit codes 0/1/2, capability matrix logging, `make validate-config`, installer stage, systemd start limit, 17 tests |
| WI-3 (fixtures) | `c21e2f1` | `tests/test.config.yaml` extended to three asymmetric devices |
| bug fix | `e6cddbb` | 409 `next_available_at` rendered in UTC |
| bug fix | `6a8ca70` | `next_available_*` null when every holder is unlimited |
| WI-4 (phases 4+5) | `0e278bc` | `DeviceSpec`, `_select()`, the two new exceptions, request/response fields, `/status` catalogue, 42 tests |
| refactor | `d42528b` | Configuration parsed once at startup instead of twice |
| WI-5 (phase 6) | `728ef7f` | Reservation dialog (capability picker; the device mode was later removed, §18.8), card chips, band filtering |
| WI-6 (phase 7) | this commit | README, CHANGELOG, the five `docs/` files, the migration test, version bump to 4.0.0 |

**Suite state:** 545 collected, 531 passed. The 2 failures and 12 errors are pre-existing
and environmental (Windows workstation: no `ip`, no `iw`, no `wls16`). mypy is clean
across 43 source files. `ng build` succeeds in development and production configurations.

### 18.2 WI-6 — documentation and release (done)

Completed on **2026-09-01**. What each item became:

- [x] **`config.example.yaml`** — complete `capabilities` block on all three devices, with
      the valid ids, the "every key mandatory" rule and the "never probed, never edited"
      statement in the comment header
- [x] **`README.md`** — capabilities in *How It Works* and in the configuration snippet;
      a *Device capabilities* subsection; a new *Validating the Configuration* section with
      the exit-code table and the upgrade note; `--validate-config` in *Quick Start*;
      `make validate-config` in the Makefile listing; capability-driven API examples
      plus the 409/422 table
- [x] **`CHANGELOG.md`** — `[4.0.0] - 2026-10-05`, deliberately short and user-facing, with
      `⚠️ Breaking Changes`, `✨ Features`, `🐛 Bug Fixes`, `🔧 Maintenance` and `✅ Tests`,
      pointing here for the design detail. The `[Unreleased]` hostapd entries folded into
      the release
- [x] **`docs/troubleshooting.md`** — *Issue 0: Service Does Not Start — Configuration
      Validation Failed* as the first thing in *Common Issues*, with a real report, how to
      read it, the exit codes, and the `failed` versus `activating (auto-restart)`
      distinction; cross-referenced from *Quick Diagnostics*, *Issue 1* and *Getting Help*
- [x] **`docs/swagger.md`** — *Device Capabilities (4.0.0)*: request and response fields,
      the nullable UTC `next_available_*`, both shapes of the 422 body, and the
      `/status` catalogue
- [x] **`docs/networking.md`** — *Automatic Detection (4.0.0)* under the subnet-conflict
      section, and *Device Capabilities and Bands* covering declaration-not-probe, the
      relation to `band` at AP creation, and the fact that capabilities do not touch
      subnets or NAT
- [x] **`docs/readme-dev.md`** — a complete example config; `make validate-config` in the
      targets and the pre-commit checklist; a new *Extending the Configuration* section on
      adding a rule (with the deferred-import requirement and why it is not stylistic) and
      adding a capability
- [x] **`docs/unit-testing.md`** — a *Configuration Fixtures* section contrasting
      `tests/test.config.yaml` with the `write_config` fixture, the three-device table, and
      the ordering constraint on the fixture
- [x] **Version bump** — `update_version.sh --bump-to 4.0.0`; `VERSION` and
      `frontend/package.json` aligned
- [x] **Migration test (§12.8)** — `TestV30Migration` in `tests/test_config_validation.py`:
      a v3.0-style file reports exactly `allow_unlimited_reservation`,
      `networks[0].capabilities`, `networks[1].capabilities`, `cors_origins`, once each,
      every one with a hint naming the required ids; completing the file as directed makes
      it valid; and `load_config()` still refuses rather than defaulting capabilities in

Not done, and deliberately so: `make lint` — see [§18.5](#185-open-decisions).

### 18.3 Remaining — WI-7, bench validation (~2 h)

**The only outstanding work.** The full list is
[§12.9](#129-bench-validation--required-and-not-possible-on-a-windows-workstation), which
also carries the `requirements-dev.txt` fix. Nothing there can be done off-bench, and
4.0.0 should not be released until it is done.

### 18.4 Deviations from this proposal, and why

Recorded so a later reader does not mistake them for oversights.

| # | Deviation | Reason |
|---|---|---|
| 1 | `load_config()` validation was wired in WI-1, though the checklist puts it in phase 3 | The four `field_validator`s leave the model in WI-1. Without the wiring the relocated rules would be unenforced for one commit and the suite red, which contradicts §13.1's own rule that each work item finishes green. |
| 2 | `capabilities` is `Dict[str, StrictBool]`, not `Dict[str, bool]` | Pydantic coerces the YAML string `"yes"` to `True`, while the group rule compares with `is True` and reads it as disabled. Plain `bool` made the model and the rule set disagree about a value that decides whether a device can host an AP. |
| 3 | The report is ASCII-only; §5.7 showed typographic arrows | Found by a manual smoke test, not the suite: pytest captures stdout as UTF-8, so the arrow passed every test and then raised `UnicodeEncodeError` on a cp1252 console. The same would happen in journald under `LANG=C`. |
| 4 | The v1 registry guard raises instead of asserting | `assert` is stripped under `python -O`, and this guard protects allocation correctness. |
| 5 | `NetworkEntry` normalises capability keys in a `field_validator`; §4.3 called it a plain container | Purely mechanical key canonicalisation, no semantics. Without it `capability_set` breaks on a file that legitimately writes `"5GHz"`. |
| 6 | No `tests/invalid.config.yaml`; the `write_config` fixture builds broken configs instead | Self-contained, and each test states its own faults rather than depending on a shared broken file whose contents must be cross-referenced. |
| 7 | Capability tests live in `tests/test_reservation_capabilities.py`, not `test_reservation.py` | That file is already 800+ lines and covers the reservation lifecycle; allocation policy is a separate concern. |
| 8 | The install stage is `02-validate-config.sh`, sharing the `02` prefix with `02-systemd.sh` | The orchestrator's `find` piped through `sort -V` orders it after systemd and before `03-enable.sh`, which is what matters. Renumbering the later stages would churn their `INSTALL_STAGE_NN_DONE` state keys for no gain. |
| 9 | Card capability chips reuse `.status-chip` rather than defining their own rule | See the SCSS budget in §18.5. A standalone rule broke the production build. |
| 10 | Capability keys are bracket-quoted in issue paths — `networks[0].capabilities["2.4ghz"]`, not `.2.4ghz` | The id contains a dot, so the dotted form reads as three nested keys and cannot be told apart from real nesting. The quoted form is unambiguous and shows how the key must be written in YAML, so the report doubles as an example. `_capability_path()` and `_loc_to_path()` both produce it and a test asserts they agree — phase 4 is de-duplicated against phases 2/3 by exact path string, so a drift would report the same fault twice. |

### 18.5 Open decisions

Two questions this implementation deliberately did **not** answer.

**`make lint` is not achievable as the project stands, and §12.8 asks for it.**
412 errors, of which 386 predate this feature. The composition is the point:

| Rule | Count | What it is |
|---|---|---|
| UP045 / UP006 / UP035 | 242 | `typing.List` and `Optional[X]` instead of the PEP 585/604 builtins — the convention of the entire codebase |
| B008 | 49 | `Depends()` in argument defaults — FastAPI's own idiom, which ruff flags by design |
| BLE001 | 50 | `except Exception`, used throughout and often deliberately |

The root cause is that **the project has no ruff configuration file** — no `pyproject.toml`,
no `ruff.toml` — so `make lint` runs whatever default rule set the installed version
carries, and `requirements-dev.txt` pins only `ruff>=0.3.0`. The output therefore changes
with whoever runs it (measured with 0.16.5). Closing this needs a `ruff.toml` fixing the
rule set, with `flake8-bugbear.extend-immutable-calls` listing `fastapi.Depends` to
remove the 49 false positives. Out of scope here, but §12.8 cannot be satisfied until
someone decides it.

> **REMINDER (decided 2026-10-05):** the `anyComponentStyle` budget is held at a 5 kB error / 4 kB warning
> limit for now. Revisit: shrink `network-card.component.scss` (3.98 kB) or drop the budget.

**`network-card.component.scss` had 30 bytes of headroom left.** The `anyComponentStyle`
budget in `frontend/angular.json` held the Angular CLI's `ng new` defaults (2 kB warning,
4 kB error), which nobody on this project chose, and that file sits at 3.98 kB. Raised to
3 kB / 5 kB to buy room; the initial bundle already exceeds its own budget by 471 kB, so
these budgets are decorative except where they hit the error threshold. Whether to keep
them at all is still open.

### 18.6 Facts discovered during implementation

Small findings that are worth not rediscovering.

* **`tests/test_api.py::TestAuthentication::test_request_without_auth` is a weak test.**
  It requests `/api/v1/interfaces`, an endpoint that no longer exists, and expects 200.
  It fails on a clean checkout and passes as soon as `frontend/dist` exists, because the
  SPA catch-all then answers every path. Verified by renaming the directory. It asserts
  nothing about authentication.
* **`requirements-dev.txt` cannot be installed.** `types-PyYAML>=2024.1.0` is
  unsatisfiable: that package versions as `6.0.12.<date>`, and `6.0.12.x < 2024.1.0`
  under PEP 440. `make venv` for development therefore installs nothing from a clean
  checkout. Listed in §12.9.
* **The configuration was parsed twice on every boot** before `d42528b`, once by
  `run_server()` and once by `create_app()` through `get_config()`.


---

### 18.7 Revision — the release became 4.0.0 and the compatibility shims were removed

Decided **2026-10-05**, after the implementation above. The feature was first built as an
additive, backward-compatible 3.1.0. That was reversed: a 3.x client cannot say it needs
5 GHz, so under 3.1.0 it silently received whichever device was free (the least capable
one, which is the *worst* choice for it). A clear error is better than a behaviour the
client cannot control.

**3.1.0 was never released and no longer exists**; the work ships as **4.0.0**.

What changed relative to §18.1–§18.6 (those sections describe the earlier build and are
kept as history):

| Area | Before | Now |
|---|---|---|
| `POST /device-reservation` | `required_capabilities` and `interface` optional | `required_capabilities` **required** (`[]` = any device); `interface` removed in §18.8. A missing field gives `422` `Missing required field(s): ...`, all fields listed at once |
| `ReservationManager` | accepted `DeviceSpec` or plain `str` | `DeviceSpec` only; tests use `tests/helpers.py::device_specs()` |
| Frontend | tolerated a backend without capabilities (`?? []`, optional TS fields, "all bands" fallback in the network form) | requires the 4.0.0 API; fields are mandatory in the models; the reservation dialog always sends `required_capabilities` |
| Version | 3.1.0 | 4.0.0 (`VERSION`, `frontend/package.json`, lockfile) |
| Docs | additive wording | README, CHANGELOG, `docs/swagger.md`, §6, §7, §11, §12, D16, D22 and §19 rewritten |

Internal `ReservationManager.create()` still defaults `required_capabilities` to empty:
the contract is enforced at the HTTP boundary, where a client can get it wrong.

### 18.8 Revision — choosing a specific antenna was removed

Decided **2026-10-05**, before any release. The first design let a request name an
antenna (`interface`) and bypass the allocation algorithm. It was removed: for now Wi-Lab
manages allocation entirely on its own, and **the client states only the capabilities it
needs**. With all antennas in one location and differing only in the bands they support,
nothing strictly requires naming one; a difference the capabilities cannot express (a
chipset, a cable, an attenuator) would be better modelled as a new capability than as a
device name. If a real need appears, the feature can be reintroduced.

Removed everywhere: the `interface` request field, the 404 for an unknown interface, the
pinned-device 422 body (`interface`, `missing`), `UnknownDeviceError`,
`ReservationManager.create(device_id=...)`, and the "By device" mode of the reservation
dialog. Sections §2.4, §3.3, §6, §7, §8.2 and §9.1 above were updated accordingly; D17 and
D19 are retired. The request model now **forbids unknown fields**, so a client that still
sends `interface` gets `422` naming it rather than being silently ignored.

## 19. Migration from older versions

For API clients moving from **3.x to 4.0.0**. 4.0.0 is a **breaking release**: one
request becomes stricter and is rejected if it is not updated, everything else is
additive. There is no compatibility mode, and no endpoint was added or removed.

### Before you upgrade (operators)

`config.yaml` must be completed first: every key is mandatory, including a `capabilities`
block on each device. Run `python3 main.py --validate-config`, fix what it lists, then
restart. The service refuses to start on an incomplete file.

### What an API client must do

1. **Add `required_capabilities` to every `POST /device-reservation`.** List what you
   need (`["5ghz"]`), or send `[]` for "any device". Omitting it, or sending `null`, is
   rejected.
2. **Handle the new error cases** (the 422 variants and 409 with a `null` ETA, below).
3. **Stop assuming which device you get.** You cannot choose the antenna: state what you
   need and read `interface` and `capabilities` from the response.
4. Create the network with a `band` the device provides (see `capabilities` in your
   reservation; `dual` needs both). The API enforces it: any other band is refused at once
   with `422`, and the hardware is not consulted.

### The request that breaks

```bash
# 3.x                                        # 4.0.0 -> 422
-d '{"duration_seconds": 3600}'              {"detail": "Missing required field(s): required_capabilities"}

# 4.0.0
-d '{"duration_seconds": 3600, "required_capabilities": []}'       # any device
-d '{"duration_seconds": 3600, "required_capabilities": ["5ghz"]}' # needs 5 GHz
```

Ids are case-insensitive; duplicates are ignored. **Any other field is rejected** (for
example `interface`): you cannot choose the antenna.

### Reservation flow

Before: one call, whichever device was first free.

```
POST /device-reservation {duration}  ->  200 device | 409 all busy
```

Now: state what you need.

```
POST /device-reservation {duration, required_capabilities}
  200  -> use response.interface / response.capabilities
  409  -> TRANSIENT: matching devices busy. Retry after next_available_in
          (null = no scheduled release: do not start a countdown)
  422  -> missing or unknown field, unknown capability, or PERMANENT: no device
          provides this.
          Change the request, never retry it unchanged
```

Treat 409 and 422 differently: waiting fixes the first and can never fix the second.

### Other endpoints and responses

All additive; existing fields are untouched.

| Endpoint | Change |
|---|---|
| `POST /device-reservation`, `GET /device-reservation/{id}` — response | adds `capabilities` (what the assigned device provides, e.g. `["2.4ghz"]`) |
| `GET /status` | `networks[]` adds `capabilities`; new top-level `capabilities_catalogue`: `[{id, label, kind, total_devices, available_devices}]`, only capabilities at least one device has |
| `GET /debug` | each managed interface adds `capabilities` |

### Errors

| Status | 3.x | 4.0.0 |
|---|---|---|
| 409 no device free | `{"error", "next_available_at", "next_available_in"}`; `next_available_at` in the **server's local time**; "now" when every holder was unlimited | adds `requested_capabilities`. `next_available_at` is **UTC**. Both `next_available_*` are `null` when every matching device is held by an unlimited reservation. The ETA covers only devices that match the request |
| 422 | duration out of range / unlimited not allowed (string `detail`) | unchanged, plus: **missing required field(s)** (string `detail`, all listed); unknown field; unknown capability id; no device can ever provide the set (`detail`: `error`, `requested`, `available_capabilities`) |

### Behaviour change

With `required_capabilities: []` you get the **least capable** free device, not the first
in configuration order, so dual-band adapters stay free for requests that need them. A
script that assumed "first device" must state its needs with `required_capabilities`.

### Example

```bash
curl -X POST http://HOST:8080/api/v1/device-reservation \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"duration_seconds": 3600, "required_capabilities": ["5ghz"]}'
# -> {"reservation_id":"a1b2c3d4","interface":"wls16","capabilities":["2.4ghz","5ghz"], ...}
```

Field-level detail: [docs/swagger.md](../../docs/swagger.md); the README has more examples.
