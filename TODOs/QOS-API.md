# Feature: QoS API

**Priority:** 2 (HIGH)
**Status:** IMPLEMENTED

---

## Overview

Wi-Lab provides per-reservation network condition simulation via **QoS profiles**. A profile is an ordered sequence of timed steps, each defining bandwidth limits, a quality score, or advanced netem overrides.

This single model covers:

- **Dynamic scenarios** (time-varying conditions): moving devices, cell handovers, tunnels, congested cells, satellite links
- **Static scenarios** (fixed configuration): a single step applied indefinitely via auto-generated `once-hold-last` profile

Profiles are read-only and distributed with wi-lab. Any reservation can apply a profile from the catalogue **or** provide QoS parameters inline, which are transparently converted into an ephemeral profile.

---

## Architecture

- **`QosProfileManager`** (`wilab/network/qos_profile.py`) is the sole orchestrator of QoS state. It manages profile execution via a dedicated thread per active reservation, advancing through steps according to the playback mode.
- **`QosManager`** (`wilab/network/qos.py`) is the kernel `tc` driver. It manages HTB, IFB, and netem qdiscs. It does not own application-level state — it is called by `QosProfileManager` at each step transition.
- **No conflict state (409)**: since everything is a profile, a reservation has at most one active profile at any time.

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
| `advanced` | No | Advanced netem override applied to both directions (same schema as `QosQualityAdvanced`) |

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
| `once-hold-last` | Single execution: after the last step completes, remains fixed on that step indefinitely until explicitly stopped |

### Profile Catalogue — Multi-file

Profiles are distributed in `wilab/data/qos-profiles/`. The catalogue is loaded at startup:

1. `default.json` is always loaded first — its profiles take priority over any other file
2. All other `*.json` files in the folder are loaded in alphabetical order
3. Each file is validated against `profile.schema.json` (JSON Schema) before processing
4. If a profile `id` is already present in the catalogue, the duplicate is discarded and a warning is logged
5. `profile.schema.json` itself is excluded from loading

This allows users to add custom profile files alongside the defaults without modifying the distributed `default.json`.

### Generated Profiles (Inline Static QoS)

When a user submits QoS parameters directly via `POST /qos/profile` (instead of a `profile_id`), an **ephemeral profile** is auto-generated internally:

- `id`: UUID prefix + `:generated_static` (e.g. `18f7a2b1:generated_static`)
- `mode`: always `once-hold-last`
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

**`POST` request body — Option 2: inline QoS (auto-generates `once-hold-last` profile)**
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
  "description": "Device on foot in city, occasional signal dips between buildings and crossing streets.",
  "mode": "loop",
  "steps": 7,
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
- `404` — no active profile on the interface (on DELETE)
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

## Technical Implementation — tc / HTB / IFB / netem

### Bandwidth Throttling: `tc` + HTB

Linux `tc` (traffic control) with **HTB** (Hierarchical Token Bucket) provides per-interface rate limiting.

**Download vs Upload direction:**

| Client direction | Kernel direction | Where tc applies |
|---|---|---|
| **Download** (client receives) | **Egress** (AP sends) | Directly on physical interface |
| **Upload** (client sends) | **Ingress** (AP receives) | IFB required (see below) |

Linux `tc` can shape only **egress** natively. Upload control uses an **IFB** (Intermediate Functional Block) device: ingress traffic on the physical interface is redirected to a virtual IFB device, and shaping is applied on the IFB egress.

Each physical interface uses a dedicated IFB mapping (e.g. `wlan0` → `ifb0`, `wlan1` → `ifb1`).

**Download throttle (egress on physical interface):**
```bash
tc qdisc add dev wlan0 root handle 1: htb default 10
tc class add dev wlan0 parent 1: classid 1:10 htb rate 5000kbit ceil 5000kbit burst 15k
```

**Upload throttle (through IFB):**
```bash
modprobe ifb numifbs=2
ip link set dev ifb0 up
tc qdisc add dev wlan0 handle ffff: ingress
tc filter add dev wlan0 parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0
tc qdisc add dev ifb0 root handle 1: htb default 10
tc class add dev ifb0 parent 1: classid 1:10 htb rate 2000kbit ceil 2000kbit burst 15k
```

**Live update (no tree rebuild):**
```bash
tc class change dev wlan0 parent 1: classid 1:10 htb rate 8000kbit ceil 8000kbit
```

### Link Quality: `tc` + netem

**netem** (Network Emulator) is chained as a child qdisc under HTB for link impairment simulation.

| Effect | netem option | Range |
|---|---|---|
| Packet loss | `loss {x}%` | 0–100% |
| Latency | `delay {x}ms` | 0–5000 ms |
| Jitter | `delay {x}ms {y}ms distribution {dist}` | 0–1000 ms |
| Corruption | `corrupt {x}%` | 0–5% |

**HTB + netem chaining:**
```bash
tc qdisc add dev wlan0 root handle 1: htb default 10
tc class add dev wlan0 parent 1: classid 1:10 htb rate 5000kbit ceil 5000kbit burst 15k
tc qdisc add dev wlan0 parent 1:10 handle 10: netem \
    loss 2% delay 50ms 10ms distribution normal corrupt 0.1%
```

**Quality without throttling:** HTB is still created with a very high rate (`1000000kbit`) as netem parent.

### Quality Score Formula

Quality is expressed as a **0–100% score** (100 = perfect, 0 = severely degraded). The score is mapped to netem parameters via quadratic/cubic curves:

```
degradation = (100 - quality) / 100.0

packet_loss%    = degradation² × 30       # 0% → 30%
delay_ms        = degradation² × 1000     # 0 ms → 1000 ms
jitter_ms       = degradation² × 300      # 0 ms → 300 ms
corruption%     = degradation³ × 1        # 0% → 1%
```

| Quality | Packet Loss | Delay | Jitter | Corruption | Perceived |
|---|---|---|---|---|---|
| 100 | 0% | 0 ms | 0 ms | 0% | Perfect |
| 90 | 0.3% | 10 ms | 3 ms | ~0% | Near-perfect |
| 75 | 1.9% | 62 ms | 19 ms | 0.002% | Slightly degraded |
| 50 | 7.5% | 250 ms | 75 ms | 0.125% | Noticeable |
| 25 | 16.9% | 562 ms | 169 ms | 0.42% | Poor |
| 0 | 30% | 1000 ms | 300 ms | 1% | Nearly unusable |

### Advanced Override

Optional `QosQualityAdvanced` parameters override the formula for precise control:

| Field | Type | Range | Default |
|---|---|---|---|
| `packet_loss_percent` | float | 0–100 | 0 |
| `delay_ms` | int | 0–5000 | 0 |
| `jitter_ms` | int | 0–1000 | 0 |
| `corruption_percent` | float | 0–5 | 0 |
| `delay_distribution` | string | `normal`, `pareto`, `paretonormal` | `normal` |

Delay distribution profiles:
- **normal**: Gaussian; typical for stable wired or good WiFi paths
- **pareto**: Heavy-tail; models bursty wireless conditions
- **paretonormal**: Mixed; often more realistic for real WiFi links

---

## System Dependencies

- **`iproute2`** (`tc` binary): required. Usually present on Linux.
- **`ifb` kernel module**: required for upload control (`modprobe ifb`). May be unavailable on minimal/container kernels.
- **`sch_netem` kernel module**: required for quality simulation. Usually available on standard kernels.
- **`sch_htb` kernel module**: required for HTB shaping. Usually available on standard kernels.
- **Root/CAP_NET_ADMIN**: `tc` requires elevated network privileges. wi-lab already runs with required privileges for hostapd/iptables.
- **`jsonschema`** (Python): for JSON Schema validation of profile catalogue files.
- **Active reservation + active network**: QoS can only be applied when the network is started on a reserved interface.

---

## Known Limitations

- **No persistence across restarts:** An active profile is lost on server restart. The user must reapply manually.
- **Step timing is approximate:** Transitions are not real-time precise. Under CPU load, delays of tens of milliseconds are possible.
- **No mid-step interpolation:** Parameters change discretely at step boundaries. No gradual fade between steps.
- **tc does not survive interface down/up:** QoS rules are cleared when the interface resets. The active profile is marked inactive automatically.
- **Not per-client:** This feature is interface-wide. Per-client QoS profiles are a separate future feature.
- **Wireless precision caveats:** WiFi MAC-level retransmissions are invisible to tc; netem packet loss is additive to real RF losses.
- **Driver queueing effects:** WiFi drivers have internal queues; very low-rate shaping can be less precise.
- **IFB overhead:** Ingress redirect to IFB introduces extra packet processing overhead, measurable on weak AP hardware under load.

---

## Implementation Tasks

All phases completed.

### Phase 1 — Data & Catalogue

- [x] Create directory `wilab/data/qos-profiles/`
- [x] Create `profile.schema.json` — JSON Schema for profile validation
- [x] Create `default.json` with the 10 default profiles

### Phase 2 — Pydantic Models

- [x] `QosProfileMode` — string enum: `loop`, `bounce`, `once`, `once-hold-last`
- [x] `QosProfileStep` — with mutual exclusivity and presence validators
- [x] `QosProfile` — id, description, mode, steps
- [x] `QosProfileStartRequest` — XOR validation (profile_id OR inline params)
- [x] `QosProfileStepState`, `QosProfileState` (includes description field)

### Phase 3 — QosProfileManager

- [x] `_ActiveProfile` dataclass with threading support
- [x] Catalogue loading with JSON Schema validation and multi-file merge
- [x] Profile execution thread with all 4 playback modes
- [x] Step isolation (all 6 QosManager fields set explicitly per step)
- [x] Inline profile generation (single-step `once-hold-last`)

### Phase 4 — Dependency Injection

- [x] `get_qos_profile_manager()` singleton in `wilab/api/dependencies.py`

### Phase 5 — API Routes

- [x] `catalogue_router` — `GET /profiles`, `GET /profiles/{profile_id}` (no auth)
- [x] `reservation_router` — `POST/GET/DELETE /{rid}/qos/profile` (auth required)
- [x] Route registration in `__init__.py`

### Phase 6 — Tests

- [x] 113 tests covering models, catalogue loading, profile manager (all 4 modes), API endpoints, and QosManager tc driver
