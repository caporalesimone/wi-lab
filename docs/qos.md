# QoS Profiles

> **Experimental in 4.1:** untested, and its API and behaviour may change in any release. Do not
> build client logic on it.

QoS lets you simulate real-world network conditions on a per-reservation basis. You can apply a **profile** from the built-in catalogue or provide **inline QoS parameters** that are applied as a static configuration.

> **Prerequisite:** the network must be **active** on the reservation before applying a QoS profile.

---

## How It Works

A **profile** is an ordered sequence of steps. Each step defines a duration and network parameters (speed limits, link quality, or advanced netem settings). The system executes steps in sequence according to the profile's **playback mode**.

**Static QoS** (fixed speed/quality) is a profile too — it's automatically created as a single-step `once-hold-last` profile behind the scenes.

---

## Endpoints

### Catalogue (no auth required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v2/qos/profiles` | List all available profiles (full detail) |

### Per-Reservation (requires `Authorization: Bearer <token>`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v2/reservations/{reservation_id}/qos/profile` | Start a profile |
| `GET` | `/api/v2/reservations/{reservation_id}/qos/profile` | Get active profile state |
| `DELETE` | `/api/v2/reservations/{reservation_id}/qos/profile` | Stop profile and clear QoS |

---

## Profile Catalogue

wi-lab ships with 10 built-in profiles simulating common scenarios. Every profile that
imitates a real network limits the bandwidth; latency and loss are moderate, as on a real
mobile link, where retransmissions hide most of the radio loss.

| Profile ID | Mode | Steps | Scenario |
|---|---|---|---|
| `4g_urban_stationary` | loop | 4 | Urban 4G, stationary: 20–35 Mbit/s down, 30–50 ms added RTT, short dips |
| `4g_urban_moving` | loop | 7 | On foot in a city: bandwidth drops between buildings |
| `4g_highway` | loop | 7 | Vehicle at highway speed: variable bandwidth, handovers as 1 s outages |
| `4g_train_tunnel` | once-hold-last | 7 | Train in a tunnel: 30 s without connectivity, then 4G until stopped |
| `4g_rural` | loop | 6 | Weak rural 4G: 0.5–5 Mbit/s, 80–200 ms added RTT, a short drop |
| `4g_congested_stadium` | loop | 6 | Crowded cell: little bandwidth per user, high latency |
| `4g_to_3g_fallback` | once-hold-last | 6 | 4G lost, 3 s outage, 30 s on 3G, then 4G until stopped |
| `wifi_interference` | loop | 6 | Periodic interference: bandwidth cut, latency up, low loss |
| `satellite_link` | loop | 2 | Geostationary satellite: about 600 ms added RTT, periodic rain fade |
| `progressive_degradation` | once-hold-last | 8 | Stress test: worse every 15 s, down to no connectivity, held |

**Values are per direction.** `delay_ms` and `packet_loss_percent` apply to the download
(towards the clients) and again to the upload: the added RTT is twice `delay_ms`
(`satellite_link` uses 300 ms for about 600 ms of RTT). An outage is a step with
`"advanced": {"packet_loss_percent": 100}`. Step durations are whole seconds, so a real
handover (tens of milliseconds) is approximated by a 1 s outage. The built-in profiles use no
jitter: netem reorders packets when jitter is set, which hurts TCP far more than a real link.

### Browse the catalogue

```bash
curl "$BASE/qos/profiles"
```

Each profile in the response includes a `source_file` field indicating which JSON file it was loaded from (e.g. `"default.json"`).

### Custom Profile Files

You can add your own profiles by placing `.json` files in `wilab/data/qos-profiles/`. The loading order is:

1. `default.json` is loaded first (shipped with wi-lab — do not modify)
2. All other `*.json` files are loaded in alphabetical order
3. `profile.schema.json` is excluded automatically
4. Each file is validated against `profile.schema.json` — invalid files are skipped with a warning
5. If a profile `id` already exists in the catalogue, the duplicate is discarded and a warning is logged

Create a new JSON file (e.g. `custom.json`) with the same structure as `default.json`, a JSON array of profiles:

```json
[
  {
    "id": "my_scenario",
    "description": "Description of the scenario.",
    "mode": "loop",
    "steps": [
      { "duration_sec": 10, "quality": 80, "dl_speed_kbit": 5000 },
      { "duration_sec": 5, "quality": 30, "dl_speed_kbit": 1000 }
    ]
  }
]
```

Custom profiles appear in the catalogue endpoints and can be used exactly like built-in ones. Profiles are loaded at service startup.

---

## Playback Modes

| Mode | Behaviour |
|------|-----------|
| `loop` | Repeats indefinitely: restarts from step 0 after the last step |
| `bounce` | Ping-pong: reverses direction at boundaries (no step duplication) |
| `once` | Single pass: QoS is cleared after the last step completes |
| `once-hold-last` | Single pass: holds the last step indefinitely until stopped |

---

## Step Parameters

Each step in a profile defines:

| Field | Required | Description |
|---|---|---|
| `duration_sec` | Yes | Duration in seconds |
| `quality` | No | Link quality 0–100 (applied symmetrically to download and upload) |
| `dl_speed_kbit` | No | Download speed cap in kbit/s |
| `ul_speed_kbit` | No | Upload speed cap in kbit/s |
| `advanced` | No | Advanced netem override (mutually exclusive with `quality`) |

**Constraints:**
- `quality` and `advanced` cannot both be set in the same step
- At least one of `quality`, `advanced`, `dl_speed_kbit`, `ul_speed_kbit` must be present
- Each step is **self-contained**: parameters not set in a step revert to baseline (no carry-over)

### Quality Score Mapping

The quality score (0–100) is mapped to network impairments:

Values per direction; the added RTT is twice the delay.

| Quality | Packet Loss | Delay | Jitter | Corruption | Perceived |
|---------|-------------|-------|--------|------------|-----------|
| 100 | 0% | 0 ms | 0 ms | 0% | Perfect |
| 90 | 0.3% | 10 ms | 3 ms | ~0% | Near-perfect |
| 75 | 1.9% | 62 ms | 19 ms | 0.016% | Slightly degraded |
| 50 | 7.5% | 250 ms | 75 ms | 0.125% | Noticeable |
| 25 | 16.9% | 562 ms | 169 ms | 0.42% | Poor |
| 0 | 30% | 1000 ms | 300 ms | 1% | Nearly unusable |

### Advanced Override

For precise control over impairment parameters:

| Field | Type | Range | Default |
|-------|------|-------|---------|
| `packet_loss_percent` | float | 0–100 | 0 |
| `delay_ms` | int | 0–5000 | 0 |
| `jitter_ms` | int | 0–1000 | 0 |
| `corruption_percent` | float | 0–5 | 0 |
| `delay_distribution` | string | `normal`, `pareto`, `paretonormal` | `normal` |

---

## Usage Examples

All examples assume:

```
BASE=http://localhost:8080/api/v2
TOKEN=<your_auth_token>
RES=<reservation_id>
```

### 1. Start a profile from the catalogue

```bash
curl -X POST "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "4g_urban_moving"}'
```

Response:

```json
{
  "interface": "wlan0",
  "active": true,
  "profile_id": "4g_urban_moving",
  "description": "Device on foot in a city on 4G: bandwidth drops between buildings and at crossings, latency rises, loss stays low. Delay and loss are per direction.",
  "source_file": "default.json",
  "mode": "loop",
  "steps": 7,
  "current_step": {
    "index": 0,
    "elapsed_sec": 0,
    "duration_sec": 15
  },
  "total_elapsed_sec": 0
}
```

### 2. Apply static QoS (inline parameters)

```bash
curl -X POST "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 8000,
    "upload_speed_kbit": 3000,
    "download_quality": 80
  }'
```

This creates an auto-generated `once-hold-last` profile with a single step. The configuration is applied and held indefinitely until you stop it.

One quality applies to both directions: `download_quality` and `upload_quality` may be sent alone or together with the same value; different values, or a quality together with `advanced`, answer `422` (they used to be ignored in silence).

### 3. Apply inline QoS with advanced override

```bash
curl -X POST "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 15000,
    "upload_speed_kbit": 3000,
    "advanced": {
      "delay_ms": 600,
      "jitter_ms": 30,
      "packet_loss_percent": 0.5,
      "delay_distribution": "normal"
    }
  }'
```

### 4. Check active profile state

```bash
curl "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"
```

Response when active:

```json
{
  "interface": "wlan0",
  "active": true,
  "profile_id": "4g_highway",
  "description": "Device in a vehicle at highway speed on 4G: variable bandwidth and cell handovers. A handover is a 1 s outage here (real ones last tens of ms; steps are whole seconds). Delay and loss are per direction.",
  "source_file": "default.json",
  "mode": "loop",
  "steps": 7,
  "current_step": {
    "index": 2,
    "elapsed_sec": 5,
    "duration_sec": 8
  },
  "total_elapsed_sec": 14
}
```

Response when inactive:

```json
{
  "interface": "wlan0",
  "active": false,
  "profile_id": null,
  "description": null,
  "source_file": null,
  "mode": null,
  "steps": null,
  "current_step": null,
  "total_elapsed_sec": null
}
```

### 5. Stop the active profile

```bash
curl -X DELETE "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "detail": "Profile '4g_urban_moving' deactivated correctly."
}
```

Returns `409` with `detail.code: 1011` (`qos_profile_not_active`) if no profile is currently active on the interface.

### 6. Switch profiles

You must stop the current profile before starting a new one:

```bash
# Stop current
curl -X DELETE "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"

# Start new
curl -X POST "$BASE/reservations/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "satellite_link"}'
```

---

## Error Responses

Every error body is `{"detail": {"code": ..., "reason": "...", "message": "..."}}`;
use the status and `detail.code` for control flow (see [Error codes](error-codes.md)).

| Status / `detail.code` | Cause | Example `detail.message` |
|--------|-------|----------------|
| 401 / 401 | Missing or invalid token | `"Invalid token"` |
| 404 / 404 | The reservation ID is no longer valid; `detail.reason` says why (`reservation_released`, `reservation_expired`, `reservation_invalidated`, `reservation_not_found`) | `"Reservation released (by its owner or by release-all)"` |
| 409 / 1007 | Network not active (start, get and stop) | `"Network wlan0 is not active"` |
| 409 / 1010 | Profile already active (on POST) | `"A profile is already active on this interface. Stop it first."` |
| 409 / 1011 | No active profile (on DELETE) | `"No active profile on this interface"` |
| 422 / 422 | Profile ID not in catalogue | `"profile_id: profile 'xyz' not found in catalogue"` |
| 422 / 422 | Both profile_id and inline params | `"Cannot specify both 'profile_id' and inline QoS parameters"` |
| 422 / 422 | Empty request body | `"Must specify either 'profile_id' or at least one QoS parameter"` |
| 503 / 1006 | Another operation holds the adapter; repeat after `Retry-After` (2 s) | `"Another operation on this adapter is still running; retry after Retry-After"` |

---

## Notes

- **One profile at a time:** A reservation can have at most one active profile. Stop it before starting another.
- **QoS is cleared automatically** when the network is stopped.
- **Profiles do not survive a network restart.** Re-apply after stopping and starting the network.
- **Quality is interface-wide**, not per-client. All connected clients share the simulated conditions.
- **Step timing is approximate.** Transitions are not real-time precise; expect tens of milliseconds variance.
