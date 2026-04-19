# QoS Profiles

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
| `GET` | `/api/v1/qos/profiles` | List all available profiles (full detail) |

### Per-Reservation (requires `Authorization: Bearer <token>`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/interface/{reservation_id}/qos/profile` | Start a profile |
| `GET` | `/api/v1/interface/{reservation_id}/qos/profile` | Get active profile state |
| `DELETE` | `/api/v1/interface/{reservation_id}/qos/profile` | Stop profile and clear QoS |

---

## Profile Catalogue

wi-lab ships with 10 built-in profiles simulating common scenarios:

| Profile ID | Mode | Steps | Scenario |
|---|---|---|---|
| `4g_urban_stationary` | loop | 4 | Stable urban, minor signal fluctuations |
| `4g_urban_moving` | loop | 7 | On foot in city, signal dips between buildings |
| `4g_highway` | loop | 7 | Vehicle at highway speed, frequent cell handovers |
| `4g_train_tunnel` | once | 7 | Train entering/exiting a tunnel |
| `4g_rural` | loop | 6 | Rural area, low signal, occasional drops |
| `4g_congested_stadium` | loop | 6 | Many users sharing same cell |
| `4g_to_3g_fallback` | once | 6 | 4G loss → 3G fallback with speed caps → recovery |
| `wifi_interference` | loop | 6 | Periodic interference from nearby networks |
| `satellite_link` | loop | 2 | Geostationary satellite: high latency, stable bandwidth |
| `progressive_degradation` | once | 8 | Progressive signal loss for stress testing |

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

Create a new JSON file (e.g. `custom.json`) with the same structure as `default.json`:

```json
{
  "profiles": [
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
}
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

| Quality | Packet Loss | Delay | Jitter | Corruption | Perceived |
|---------|-------------|-------|--------|------------|-----------|
| 100 | 0% | 0 ms | 0 ms | 0% | Perfect |
| 90 | 0.3% | 10 ms | 3 ms | ~0% | Near-perfect |
| 75 | 1.9% | 62 ms | 19 ms | 0.002% | Slightly degraded |
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
BASE=http://localhost:8080/api/v1
TOKEN=<your_auth_token>
RES=<reservation_id>
```

### 1. Start a profile from the catalogue

```bash
curl -X POST "$BASE/interface/$RES/qos/profile" \
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
  "description": "Device on foot in city, occasional signal dips between buildings and crossing streets.",
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
curl -X POST "$BASE/interface/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 8000,
    "upload_speed_kbit": 3000,
    "download_quality": 80
  }'
```

This creates an auto-generated `once-hold-last` profile with a single step. The configuration is applied and held indefinitely until you stop it.

### 3. Apply inline QoS with advanced override

```bash
curl -X POST "$BASE/interface/$RES/qos/profile" \
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
curl "$BASE/interface/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"
```

Response when active:

```json
{
  "interface": "wlan0",
  "active": true,
  "profile_id": "4g_highway",
  "description": "Device in a vehicle at highway speed, frequent cell handovers causing brief signal drops.",
  "source_file": "default.json",
  "mode": "loop",
  "steps": 7,
  "current_step": {
    "index": 3,
    "elapsed_sec": 1,
    "duration_sec": 2
  },
  "total_elapsed_sec": 19
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
curl -X DELETE "$BASE/interface/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"
```

Response:

```json
{
  "detail": "Profile '4g_urban_moving' deactivated correctly."
}
```

Returns `404` if no profile is currently active on the interface.

### 6. Switch profiles

You must stop the current profile before starting a new one:

```bash
# Stop current
curl -X DELETE "$BASE/interface/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN"

# Start new
curl -X POST "$BASE/interface/$RES/qos/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profile_id": "satellite_link"}'
```

---

## Error Responses

| Status | Cause | Example detail |
|--------|-------|----------------|
| 401 | Missing or invalid token | `"Not authenticated"` |
| 404 | Reservation not found / expired | `"Reservation not found"` |
| 404 | Profile ID not in catalogue | `"Profile 'xyz' not found in catalogue"` |
| 404 | No active profile (on DELETE) | `"No active profile on this interface"` |
| 409 | Network not active | `"Cannot apply QoS: network is not active for this reservation"` |
| 409 | Profile already active | `"A profile is already active on this interface. Stop it first."` |
| 422 | Both profile_id and inline params | `"Cannot specify both 'profile_id' and inline QoS parameters"` |
| 422 | Empty request body | `"Must specify either 'profile_id' or at least one QoS parameter"` |

---

## Notes

- **One profile at a time:** A reservation can have at most one active profile. Stop it before starting another.
- **QoS is cleared automatically** when the network is stopped.
- **Profiles do not survive a network restart.** Re-apply after stopping and starting the network.
- **Quality is interface-wide**, not per-client. All connected clients share the simulated conditions.
- **Step timing is approximate.** Transitions are not real-time precise; expect tens of milliseconds variance.
