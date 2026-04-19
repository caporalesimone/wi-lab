# Feature: QoS Profiles (Unified Architecture)

**Priority:** 3 (MEDIUM)
**Status:** PROPOSED
**Estimated Effort:** ~8 hours
**Note:** Replaces the current static QoS system with a unified profile-based architecture

---

## Overview

This feature implements a unified QoS system based on **profiles**. A profile is an ordered sequence of steps, each with a defined duration and network parameters. This single model covers both:

- **Dynamic scenarios** (time-varying conditions): moving devices, cell handovers, tunnels, congested cells, satellite links
- **Static scenarios** (fixed configuration): a single step applied indefinitely

Profiles are read-only and distributed with wi-lab. Any reservation can apply a profile from the catalogue **or** provide QoS parameters inline, which are transparently converted into an ephemeral profile.

---

## Architecture

The current QoS implementation uses two separate concerns:
- `QosManager` (`wilab/network/qos.py`): manages `tc` rules (HTB + IFB + netem) and maintains per-interface state (`_InterfaceQosState`)
- `wilab/api/routes/qos.py`: exposes `POST/GET/DELETE /api/v1/interface/{rid}/qos` endpoints that call `QosManager` directly

This refactor **unifies static and dynamic QoS into a single profile-based system**:

- **`QosProfileManager`** becomes the sole orchestrator of QoS state. It manages profile execution via a dedicated thread per active reservation, advancing through steps according to the playback mode.
- **`QosManager`** is retained as the kernel `tc` driver. It continues to manage HTB, IFB, and netem qdiscs. However, it no longer owns application-level state — it is called by `QosProfileManager` at each step transition.
- **Static QoS** (the current `POST /qos` with direct parameters) becomes an auto-generated profile with `mode: hold` and a single step. The user-facing behaviour is equivalent: parameters are applied and held indefinitely until explicitly stopped.
- **No conflict state (409)**: since everything is a profile, a reservation has at most one active profile at any time. There is no separate "static QoS" vs "profile" state to conflict.

The old `/qos` endpoints are **removed entirely** and replaced by `/qos/profile`.

---

## Core Concepts

### Profile

A profile is a named, ordered list of steps. Each step specifies:

| Field | Required | Description |
|---|---|---|
| `duration_sec` | Yes | Duration of this step in seconds |
| `quality` | No | Quality score 0–100 applied symmetrically to both download and upload netem |
| `dl_speed_kbit` | No | Download speed cap (kbit/s) |
| `ul_speed_kbit` | No | Upload speed cap (kbit/s) |
| `advanced` | No | Advanced netem override applied to both directions (same schema as existing `QosQualityAdvanced`) |

**Constraints:**
- `quality` and `advanced` are **mutually exclusive** within a step
- At least one of `quality`, `advanced`, `dl_speed_kbit`, `ul_speed_kbit` must be present
- `quality` acts only on netem parameters (packet loss, delay, jitter, corruption) — it does not affect speed throttling
- `dl_speed_kbit` / `ul_speed_kbit` act only on the HTB rate limit, independent of `quality`

**Step parameter isolation:** fields are not inherited between steps. Each step is fully self-contained. Parameters not specified in a step revert to baseline (no throttle, no netem). This prevents unexpected carry-over across step boundaries.

### Playback Mode

The profile field `mode` (string enum) controls how the step sequence is executed:

| Value | Behaviour |
|---|---|
| `loop` | Repeats indefinitely: after the last step, restarts from the first |
| `bounce` | Repeats indefinitely: at the end, reverses direction (ping-pong); boundary steps are not duplicated |
| `once` | Single execution: after the last step completes, QoS is cleared and the profile becomes inactive |
| `hold` | Single execution: after the last step completes, remains fixed on that step indefinitely until explicitly stopped |

### Profile Catalogue — Multi-file

Profiles are distributed in `wilab/data/qos-profiles/`. The catalogue is loaded at startup:

1. `default.json` is always loaded first — its profiles take priority over any other file
2. All other `*.json` files in the folder are loaded in alphabetical order
3. Each file is validated against `profile.schema.json` (JSON Schema) before processing
4. If a profile `id` is already present in the catalogue, the duplicate is discarded and a warning is logged: `profile '{id}' in '{file}' conflicts with an existing entry, skipping`
5. `profile.schema.json` itself is excluded from loading

This allows users to add custom profile files alongside the defaults without modifying the distributed `default.json`.

### Generated Profiles (Inline Static QoS)

When a user submits QoS parameters directly via `POST /qos/profile` (instead of a `profile_id`), an **ephemeral profile** is auto-generated internally:

- `id`: UUID prefix + `:generated_static` (e.g. `18f7a2b1:generated_static`)
- `mode`: always `hold`
- `steps`: single step with the user-provided parameters

This profile is never stored in the catalogue and exists only in memory for the duration of its activation.

---

## API Design

### Catalogue Endpoints (global, not reservation-scoped)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/qos/profiles` | List all available profiles (id, description, mode, step count) |
| `GET` | `/api/v1/qos/profiles/{profile_id}` | Get full detail of a single profile including all steps |

No auth required for catalogue endpoints (read-only, no sensitive data).

### Profile Application Endpoints (reservation-scoped)

Bearer token and active network required.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/interface/{reservation_id}/qos/profile` | Start a profile on the reservation |
| `GET` | `/api/v1/interface/{reservation_id}/qos/profile` | Get active profile state and current step info |
| `DELETE` | `/api/v1/interface/{reservation_id}/qos/profile` | Stop the active profile and clear QoS |

**`POST` request body — Option 1: profile from catalogue**
```json
{ "profile_id": "4g_urban_moving" }
```

**`POST` request body — Option 2: inline QoS (auto-generates `hold` profile)**
```json
{
  "download_speed_kbit": 1000,
  "download_quality": 40
}
```

Only one format is allowed per request: either `profile_id` **or** QoS parameters, never both. Pydantic validation enforces this constraint.

**`POST` response:**
```json
{
  "interface": "wlan0",
  "active": true,
  "profile_id": "4g_urban_moving",
  "mode": "loop",
  "current_step": {
    "index": 0,
    "elapsed_sec": 2,
    "duration_sec": 15
  },
  "total_elapsed_sec": 2
}
```

**Error responses:**
- `404` — profile_id not found in catalogue
- `409` — a profile is already active on the interface (stop it first)
- `422` — invalid request body (both profile_id and QoS params, or neither)

---

## Default Profile Catalogue

The following 10 profiles are shipped in `wilab/data/qos-profiles/default.json`:

| Profile ID | Mode | Steps | Scenario |
|---|---|---|---|
| `4g_urban_stationary` | `loop` | 4 | Stable urban environment, minor fluctuations |
| `4g_urban_moving` | `loop` | 7 | Device on foot, signal dips between buildings |
| `4g_highway` | `loop` | 7 | Vehicle at highway speed, frequent cell handovers |
| `4g_train_tunnel` | `once` | 7 | Train entering and exiting a tunnel |
| `4g_rural` | `loop` | 6 | Rural area, low signal with occasional complete drops |
| `4g_congested_stadium` | `loop` | 6 | Many users sharing the same cell (stadium, concert) |
| `4g_to_3g_fallback` | `once` | 6 | 4G loss, 3G fallback with speed caps, 4G recovery |
| `wifi_interference` | `loop` | 6 | Periodic interference from nearby networks |
| `satellite_link` | `loop` | 2 | Geostationary satellite: high latency, stable bandwidth |
| `progressive_degradation` | `once` | 8 | Progressive signal loss, useful for stress testing |

---

## Known Limitations

- **No persistence across restarts:** An active profile is lost on server restart. The interface reverts to no QoS and the user must reapply manually.
- **Step timing is approximate:** Transitions are not real-time precise. Under CPU load, delays of tens of milliseconds are possible. Acceptable for network simulation.
- **No mid-step interpolation:** Parameters change discretely at step boundaries. There is no gradual fade between steps.
- **Profile does not survive interface down/up:** QoS rules are cleared when the interface resets. The active profile is marked inactive automatically.
- **Not per-client:** This feature is interface-wide. Per-client QoS profiles are a separate future feature.

---
---

## Implementation Tasks

Starting from the current codebase state where static QoS is already implemented (`QosManager`, `wilab/api/routes/qos.py`, `wilab/models.py` QoS models, `tests/test_qos.py`).

### Phase 1 — Data & Catalogue

- [ ] Create directory `wilab/data/qos-profiles/`
- [ ] Create `wilab/data/qos-profiles/profile.schema.json` — JSON Schema:
  - Root: array of profile objects
  - Required per profile: `id` (string), `description` (string), `mode` (enum: `loop`, `bounce`, `once`, `hold`), `steps` (array, minItems 1)
  - Per step: `duration_sec` (integer, minimum 1) required; at least one of `quality`, `dl_speed_kbit`, `ul_speed_kbit`, `advanced` present; `quality` and `advanced` mutually exclusive via `not`
  - `quality`: integer, minimum 0, maximum 100
  - `dl_speed_kbit` / `ul_speed_kbit`: integer, minimum 1, maximum 1000000
  - `advanced`: object with optional fields `delay_ms` (int, 0–5000), `jitter_ms` (int, 0–1000), `packet_loss_percent` (number, 0–100), `corruption_percent` (number, 0–5), `delay_distribution` (enum: `normal`, `pareto`, `paretonormal`)
- [ ] Create `wilab/data/qos-profiles/default.json` with the 10 default profiles listed above

### Phase 2 — Pydantic Models

In `wilab/models.py`:

- [ ] Add `QosProfileMode` — string enum: `loop`, `bounce`, `once`, `hold`
- [ ] Add `QosProfileStep` model:
  - Fields: `duration_sec: int`, `quality: Optional[int]`, `dl_speed_kbit: Optional[int]`, `ul_speed_kbit: Optional[int]`, `advanced: Optional[QosQualityAdvanced]`
  - Validator: `quality` and `advanced` mutually exclusive
  - Validator: at least one of `quality`, `advanced`, `dl_speed_kbit`, `ul_speed_kbit` must be set
  - Validator: `quality` range 0–100
- [ ] Add `QosProfile` model:
  - Fields: `id: str`, `description: str`, `mode: QosProfileMode`, `steps: list[QosProfileStep]`
- [ ] Add `QosProfileStartRequest` — unified request model:
  - `profile_id: Optional[str]` — profile from catalogue
  - `download_speed_kbit: Optional[int]`, `upload_speed_kbit: Optional[int]`, `download_quality: Optional[int]`, `upload_quality: Optional[int]`, `advanced: Optional[QosQualityAdvanced]` — inline QoS parameters
  - Validator (XOR): either `profile_id` is set, **or** at least one QoS parameter is set, but not both
- [ ] Add `QosProfileStepState` model:
  - Fields: `index: int`, `elapsed_sec: int`, `duration_sec: int`
- [ ] Add `QosProfileState` model:
  - Fields: `interface: str`, `active: bool`, `profile_id: Optional[str]`, `mode: Optional[QosProfileMode]`, `current_step: Optional[QosProfileStepState]`, `total_elapsed_sec: Optional[int]`

### Phase 3 — QosProfileManager

New file `wilab/network/qos_profile.py`:

- [ ] Define `_ActiveProfile` dataclass:
  - `profile_id: str`, `mode: QosProfileMode`, `steps: list[QosProfileStep]`, `step_index: int`, `direction: int` (+1/-1 for bounce), `step_started_at: float`, `started_at: float`, `stop_event: threading.Event`, `thread: threading.Thread`
- [ ] Implement `QosProfileManager.__init__(catalogue_dir: str)`:
  - Load `profile.schema.json` from the catalogue directory
  - Glob all `*.json` files excluding the schema
  - Load `default.json` first, then remaining files in alphabetical order
  - Validate each file against the JSON Schema (skip + warn on failure)
  - Merge profiles into `dict[str, QosProfile]`; skip + warn on duplicate `id`
- [ ] Implement `list_profiles() -> list[QosProfile]`
- [ ] Implement `get_profile(profile_id: str) -> Optional[QosProfile]`
- [ ] Implement `is_active(interface: str) -> bool`
- [ ] Implement `get_state(interface: str) -> Optional[_ActiveProfile]`
- [ ] Implement `start_profile(interface: str, profile: QosProfile, qos_manager: QosManager) -> None`:
  - Create `_ActiveProfile`, start daemon thread running `_run_profile`
- [ ] Implement `stop_profile(interface: str, qos_manager: QosManager) -> None`:
  - Set stop event, join thread, call `qos_manager.clear_qos(interface)`, remove from active dict
- [ ] Implement `_run_profile(interface, active, qos_manager)` thread target:
  - At each step: call `qos_manager.apply_qos()` with all 6 fields explicitly (pass `None` for unset fields to enforce step isolation)
  - Wait via `stop_event.wait(step.duration_sec)` for interruptibility
  - If stop event fires: exit immediately
  - Advance step index per mode:
    - `loop`: `(index + 1) % len(steps)`
    - `bounce`: advance by `direction`; invert at boundaries without repeating the boundary step
    - `once`: advance linearly; after last step call `qos_manager.clear_qos()` and mark inactive
    - `hold`: advance linearly; on last step enter `stop_event.wait()` with no timeout

### Phase 4 — Dependency Injection

In `wilab/api/dependencies.py`:

- [ ] Add `_qos_profile_manager: QosProfileManager | None = None`
- [ ] Add `get_qos_profile_manager() -> QosProfileManager` — singleton, resolves catalogue dir as `Path(__file__).resolve().parent.parent / "data" / "qos-profiles"`

### Phase 5 — API Routes

New file `wilab/api/routes/qos_profile.py`:

- [ ] Implement `catalogue_router` (prefix `/qos`, tag `QoS Profiles`):
  - `GET /profiles` — list all profiles, no auth
  - `GET /profiles/{profile_id}` — profile detail or 404, no auth
- [ ] Implement `reservation_router` (prefix `/interface`, tag `QoS Profiles`):
  - `POST /{reservation_id}/qos/profile` — validate request (XOR), resolve profile or generate inline, check no active profile (409), start profile, return `QosProfileState`
  - `GET /{reservation_id}/qos/profile` — return current state (active or inactive)
  - `DELETE /{reservation_id}/qos/profile` — stop profile if active (no-op otherwise), return 204

In `wilab/api/routes/__init__.py`:

- [ ] Remove import and registration of old `qos_router` from `qos.py`
- [ ] Import `catalogue_router` and `reservation_router` from `qos_profile`
- [ ] Register both on the main `/api/v1` router

Cleanup:

- [ ] Delete `wilab/api/routes/qos.py` (old static QoS endpoints — fully replaced)
- [ ] Delete `tests/test_qos.py` API tests that reference the old `/qos` endpoints (keep `QosManager` unit tests — the tc driver is unchanged)

### Phase 6 — Tests

New file `tests/test_qos_profile.py`:

- [ ] **TestQosProfileModels**
  - `QosProfileStep` rejects both `quality` and `advanced` set simultaneously
  - `QosProfileStep` rejects step with no quality/advanced/speed fields
  - `QosProfileStep` accepts quality-only, advanced-only, speed-only, mixed speed+quality
  - `QosProfileStep` rejects `quality` outside 0–100
  - `QosProfileMode` has exactly 4 values: `loop`, `bounce`, `once`, `hold`
  - `QosProfileStartRequest` accepts `profile_id` alone
  - `QosProfileStartRequest` accepts QoS parameters alone
  - `QosProfileStartRequest` rejects both `profile_id` and QoS parameters
  - `QosProfileStartRequest` rejects empty body (neither set)
- [ ] **TestQosProfileCatalogue**
  - Load single valid JSON from temp directory
  - `default.json` loaded before other files (priority)
  - Duplicate `id` across files: second skipped, warning logged
  - Invalid JSON: skipped with warning
  - JSON Schema validation failure: skipped with warning
- [ ] **TestQosProfileManager**
  - `list_profiles()` returns all loaded profiles
  - `get_profile("existing")` returns correct profile
  - `get_profile("nonexistent")` returns `None`
  - `is_active()` returns `False`/`True`/`False` across start/stop lifecycle
  - `start_profile()` raises if profile not found
  - `start_profile()` raises if interface already has active profile
  - `stop_profile()` calls `qos_manager.clear_qos()` and joins thread
  - Step apply calls `apply_qos` with all 6 fields (verify `None` for unset)
  - `loop` mode: step_index wraps to 0 after last step
  - `bounce` mode: sequence 0→1→2→1→0→1→2 (boundaries not duplicated)
  - `once` mode: `clear_qos` called after last step, profile inactive
  - `hold` mode: thread waits on stop_event after last step
- [ ] **TestQosProfileAPI**
  - `GET /api/v1/qos/profiles` → 200, list of profiles
  - `GET /api/v1/qos/profiles/{id}` → 200, correct profile
  - `GET /api/v1/qos/profiles/nonexistent` → 404
  - `POST /{rid}/qos/profile` with `profile_id` → 200, profile starts
  - `POST /{rid}/qos/profile` with inline QoS params → 200, hold profile starts
  - `POST /{rid}/qos/profile` with unknown `profile_id` → 404
  - `POST /{rid}/qos/profile` with profile already active → 409
  - `POST /{rid}/qos/profile` with both `profile_id` and QoS params → 422
  - `POST /{rid}/qos/profile` with neither → 422
  - `GET /{rid}/qos/profile` while active → 200 with step info
  - `GET /{rid}/qos/profile` while inactive → 200 with `active: false`
  - `DELETE /{rid}/qos/profile` → 204
  - `DELETE /{rid}/qos/profile` while inactive → 204 (no-op)