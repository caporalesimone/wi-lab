# Feature: QoS (Quality of Service)

**Priority:** 2 (HIGH)
**Status:** PROPOSED
**Estimated Effort:** ~5 hours

## Overview

Add per-interface QoS controls to wi-lab: bandwidth throttling and link quality degradation. Each direction (download/upload) is independently controllable. All APIs are reservation-scoped (and therefore bound to the reserved interface) and must not affect other interfaces.

### Per-Interface Parameters

| Parameter | Unit | Range |
|-----------|------|-------|
| Max download speed | kbit/s | 1 - 1,000,000 |
| Max upload speed | kbit/s | 1 - 1,000,000 |
| Download link quality | % | 0 - 100 |
| Upload link quality | % | 0 - 100 |

### API Endpoints

All QoS APIs are under the reservation path, using the same pattern as txpower and internet:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/interface/{reservation_id}/qos` | Apply or update QoS settings |
| `GET` | `/api/v1/interface/{reservation_id}/qos` | Get current QoS status |
| `DELETE` | `/api/v1/interface/{reservation_id}/qos` | Remove all QoS rules |

Bearer token required (same auth as existing interface APIs). Network must be active on the reserved interface.

---

# Part 1: Bandwidth Throttling

## Technical Analysis

### Problem

Enforce max download and upload speed limits on a single WiFi AP interface without impacting any other system interface.

### Solution: `tc` + HTB (Hierarchical Token Bucket)

Linux `tc` (traffic control) is the kernel-native traffic shaping tool. It is **per-interface** by design: every command targets `dev <iface>`, so rules on `wlan0` do not affect `wlan1`.

**HTB** is chosen because:
- It provides accurate rate limiting with burst tolerance
- It supports class hierarchy (parent/child)
- It supports child qdiscs, required for chaining `netem` (Part 2)
- It is more flexible than TBF (flat, non-hierarchical)

### Download vs Upload Direction

From the AP interface perspective:

| Client direction | Kernel direction | Where tc applies |
|------------------|------------------|------------------|
| **Download** (client receives) | **Egress** (AP sends) | Directly on physical interface |
| **Upload** (client sends) | **Ingress** (AP receives) | Not directly; IFB is required |

**Ingress constraint**: Linux `tc` can shape only **egress** natively. Ingress qdisc can police/drop but cannot perform full shaping (queueing/delay). Upload control requires indirection.

### IFB (Intermediate Functional Block) for Upload

Standard Linux approach:

1. Create IFB virtual device (for example `ifb0`)
2. Redirect physical-interface ingress traffic to IFB
3. Apply shaping on IFB **egress**

Each physical interface should use a dedicated IFB mapping (for example `wlan0` -> `ifb0`, `wlan1` -> `ifb1`).

### tc Commands

**Download throttle setup (egress on physical interface):**
```bash
# Build HTB tree with default class 10
tc qdisc add dev wlan0 root handle 1: htb default 10
tc class add dev wlan0 parent 1: classid 1:10 htb rate 5000kbit ceil 5000kbit burst 15k
```

**Upload throttle setup (through IFB):**
```bash
# Load IFB kernel module (once)
modprobe ifb numifbs=2

# Bring dedicated IFB up
ip link set dev ifb0 up

# Redirect physical-interface ingress to IFB
tc qdisc add dev wlan0 handle ffff: ingress
tc filter add dev wlan0 parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0

# Shape on IFB egress
tc qdisc add dev ifb0 root handle 1: htb default 10
tc class add dev ifb0 parent 1: classid 1:10 htb rate 2000kbit ceil 2000kbit burst 15k
```

**Live update (no tree rebuild):**
```bash
tc class change dev wlan0 parent 1: classid 1:10 htb rate 8000kbit ceil 8000kbit
tc class change dev ifb0 parent 1: classid 1:10 htb rate 4000kbit ceil 4000kbit
```

**Full cleanup:**
```bash
tc qdisc del dev wlan0 root 2>/dev/null
tc qdisc del dev wlan0 ingress 2>/dev/null
tc qdisc del dev ifb0 root 2>/dev/null
ip link set dev ifb0 down 2>/dev/null
```

### Critical Timing

tc rules are **cleared** when an interface goes down/up (for example AP mode switch). Since `hostapd` resets the interface during startup, tc rules MUST be applied **after** hostapd is fully up.

With runtime QoS APIs (applied after network start), this requirement is naturally satisfied.

---

# Part 2: Link Quality

## Technical Analysis

### Problem

Simulate degraded network conditions (packet loss, latency, jitter, corruption) on a single interface for QA testing, realistic network simulation, and stress testing.

### Solution: `tc` + netem (Network Emulator)

**netem** is a Linux kernel qdisc specialized for network impairment simulation. It is chained as a child qdisc under HTB so throttling (Part 1) and quality degradation can coexist in one tc tree.

### netem Capabilities

| Effect | netem option | Description | Scope |
|--------|--------------|-------------|-------|
| **Packet loss** | `loss {x}%` | Random packet drop | Initial |
| **Latency** | `delay {x}ms` | Fixed delay on all packets | Initial |
| **Jitter** | `delay {x}ms {y}ms distribution normal` | Delay variance around base latency | Initial |
| **Corruption** | `corrupt {x}%` | Random bit flips in packets | Initial |
| Correlated loss | `loss {x}% {corr}%` | Time-correlated losses | Future |
| Burst loss (Gilbert-Elliott) | `loss gemodel {p} {r} {1-h} {1-k}` | State-based burst loss model | Future |
| Duplication | `duplicate {x}%` | Duplicate packets | Future |
| Reordering | `reorder {x}% {corr}%` | Out-of-order delivery | Future |

### Quality Modes: Simple Score + Advanced Override

Quality is expressed as a **0-100% score** (100% = perfect connection, 0% = severely degraded).

The score is mapped to netem parameters using quadratic/cubic curves so that **80-100% is nearly imperceptible** and degradation becomes severe below 30%:

```text
degradation = (100 - quality) / 100.0    # 0.0 (perfect) -> 1.0 (worst)

packet_loss%    = degradation^2 * 30      # 0% -> 30%
delay_ms        = degradation^2 * 1000    # 0ms -> 1000ms
jitter_ms       = degradation^2 * 300     # 0ms -> 300ms
corruption%     = degradation^3 * 1       # 0% -> 1%
```

**Reference table:**

| Quality % | Packet Loss | Delay | Jitter | Corruption | Perceived Quality |
|-----------|-------------|-------|--------|------------|-------------------|
| 100 | 0% | 0ms | 0ms | 0% | Perfect |
| 90 | 0.3% | 10ms | 3ms | 0% | Near-perfect |
| 75 | 1.9% | 62ms | 19ms | 0.002% | Slightly degraded |
| 50 | 7.5% | 250ms | 75ms | 0.125% | Noticeable |
| 25 | 16.9% | 562ms | 169ms | 0.42% | Poor |
| 10 | 24.3% | 810ms | 243ms | 0.73% | Very poor |
| 0 | 30% | 1000ms | 300ms | 1% | Nearly unusable |

**Advanced override**: optional `QosQualityAdvanced` parameters can be provided to override formula-derived values for precise test scenarios.

### Advanced Parameters

```text
QosQualityAdvanced:
  packet_loss_percent: float    (0 - 100)
  delay_ms: int                 (0 - 5000)
  jitter_ms: int                (0 - 1000)
  corruption_percent: float     (0 - 5)
  delay_distribution: string    (normal | pareto | paretonormal, default: normal)
```

Delay distribution profiles:
- **normal**: Gaussian behavior, typical for stable wired paths
- **pareto**: heavy-tail behavior, useful for bursty wireless conditions
- **paretonormal**: mixed profile, often more realistic for WiFi

### Independent Direction Control

As with throttling, download and upload quality are controlled independently:
- **Download quality** -> netem on physical interface egress
- **Upload quality** -> netem on IFB egress

### tc Commands (HTB + netem chaining)

**Full tree: HTB (throttle) + netem (quality):**
```bash
# Download: HTB root + netem leaf
tc qdisc add dev wlan0 root handle 1: htb default 10
tc class add dev wlan0 parent 1: classid 1:10 htb rate 5000kbit ceil 5000kbit burst 15k
tc qdisc add dev wlan0 parent 1:10 handle 10: netem \
    loss 2% delay 50ms 10ms distribution normal corrupt 0.1%

# Upload: same structure on IFB
tc qdisc add dev ifb0 root handle 1: htb default 10
tc class add dev ifb0 parent 1: classid 1:10 htb rate 2000kbit ceil 2000kbit burst 15k
tc qdisc add dev ifb0 parent 1:10 handle 10: netem \
    loss 1% delay 30ms 5ms distribution normal corrupt 0.05%
```

**Quality without throttling:**
```bash
# If throttling is not requested, HTB is still created as netem parent
# with a very high rate (effectively unlimited)
tc qdisc add dev wlan0 root handle 1: htb default 10
tc class add dev wlan0 parent 1: classid 1:10 htb rate 1000000kbit ceil 1000000kbit
tc qdisc add dev wlan0 parent 1:10 handle 10: netem loss 5% delay 100ms 20ms
```

**Live quality update (no tree rebuild):**
```bash
tc qdisc change dev wlan0 parent 1:10 handle 10: netem \
    loss 5% delay 100ms 30ms distribution normal corrupt 0.2%
```

---

# Considerations

## System Dependencies

- **`iproute2` package**: required (`tc` binary). Usually present on Linux, verify in install preconditions.
- **`ifb` kernel module**: required for upload control (`modprobe ifb`). Might be unavailable on minimal/container kernels.
- **`sch_netem` kernel module**: required for quality simulation. Usually available on standard kernels.
- **`sch_htb` kernel module**: required for HTB shaping. Usually available on standard kernels.
- **Root/CAP_NET_ADMIN**: `tc` requires elevated network privileges. wi-lab already runs with required privileges for hostapd/iptables.

## Software Dependencies

- No new Python dependency required (`tc` called through subprocess wrappers)
- No new frontend npm dependency required

## Feature Dependencies

- **Active reservation**: QoS requires a valid reservation token (same as all interface APIs)
- **Active network**: QoS can be applied only when network is started on that reservation/interface
- **Internet independent**: QoS works with internet enabled or disabled; it operates at interface traffic-control level

## Implementation Order

1. **Part 1 first** (throttling): establishes tc/HTB/IFB infrastructure, manager, and APIs
2. **Part 2 second** (link quality): extends same manager with netem child qdisc under HTB

Part 2 depends on Part 1 because netem is chained beneath HTB in the tc hierarchy.

## Known Limitations

- **tc does not survive interface down/up**: after stop/start cycle, QoS must be reapplied by user/API unless persistence is added later
- **Wireless precision caveats**: WiFi MAC-level retransmissions are invisible to tc; netem packet loss is additive to real RF losses
- **Driver queueing effects**: WiFi drivers have internal queues; very low-rate shaping can be less precise
- **IFB overhead**: ingress redirect to IFB introduces extra packet processing overhead, measurable on weak AP hardware under load
- **Not per-client QoS**: this feature is interface-wide. Per-client QoS remains a separate future feature (see `TODOs/client-controls.md`)

## Compatibility

- No breaking changes
- `NetworkStatus` gains optional `qos` field (backward compatible)
- Endpoints are additive only
- Frontend displays QoS controls/status only when network is active

## Verification

1. `make lint` - no new warnings
2. `make type-check` - no mypy errors
3. `python -m pytest tests/test_qos.py -v` - all QoS tests pass
4. `python -m pytest` - full suite passes (no regressions)
5. Manual: start network -> apply QoS -> `tc qdisc show dev {iface}` -> verify rules
6. Manual: apply throttle -> run iperf3 -> confirm cap
7. Manual: apply quality 50% -> run ping -> verify latency/loss profile
8. Manual: clear QoS -> verify rules removed

---

# API Examples

The examples below use:
- `BASE_URL=http://localhost:8000/api/v1`
- `TOKEN=<bearer_token>`
- `RESERVATION_ID=<reservation_id>`

## API Semantics: Field Presence and `null` Reset

**Key rule: partial updates via presence/absence/null**

| Field state | Behavior |
|-------------|----------|
| **Omitted** (not in JSON) | Do not modify this setting; keep current value |
| **Present with value** | Apply/update this setting to the value |
| **Present as `null`** | Reset/remove this specific setting (revert to unlimited/inactive) |
| **DELETE /qos** | Clear ALL QoS rules (speed + quality) and reset to baseline |

### Examples of selective resets

**Reset download speed to unlimited (keep upload as-is):**
```json
{"download_speed_kbit": null}
```

**Reset upload quality to inactive (keep upload speed as-is):**
```json
{"upload_quality": null}
```

**Reset both download and upload speed, leave quality untouched:**
```json
{
  "download_speed_kbit": null,
  "upload_speed_kbit": null
}
```

---

## 1) Apply QoS (simple mode: speed + quality score)

```bash
curl -X POST "$BASE_URL/interface/$RESERVATION_ID/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 8000,
    "upload_speed_kbit": 3000,
    "download_quality": 80,
    "upload_quality": 65
  }'
```

Example response:

```json
{
  "interface": "wlan0",
  "active": true,
  "download_speed_kbit": 8000,
  "upload_speed_kbit": 3000,
  "download_quality": 80,
  "upload_quality": 65,
  "download_netem_params": {
    "packet_loss_percent": 1.2,
    "delay_ms": 40,
    "jitter_ms": 12,
    "corruption_percent": 0.008,
    "delay_distribution": "normal"
  },
  "upload_netem_params": {
    "packet_loss_percent": 3.7,
    "delay_ms": 122,
    "jitter_ms": 36,
    "corruption_percent": 0.043,
    "delay_distribution": "normal"
  }
}
```

## 2) Apply QoS (advanced override for upload)

```bash
curl -X POST "$BASE_URL/interface/$RESERVATION_ID/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 12000,
    "download_quality": 90,
    "upload_quality_advanced": {
      "packet_loss_percent": 5.5,
      "delay_ms": 140,
      "jitter_ms": 25,
      "corruption_percent": 0.2,
      "delay_distribution": "paretonormal"
    }
  }'
```

Notes:
- Download uses simple score mapping (`download_quality=90`).
- Upload uses explicit advanced values (override mode).

## 3) Read current QoS status

```bash
curl -X GET "$BASE_URL/interface/$RESERVATION_ID/qos" \
  -H "Authorization: Bearer $TOKEN"
```

Example response:

```json
{
  "interface": "wlan0",
  "active": true,
  "download_speed_kbit": 12000,
  "upload_speed_kbit": null,
  "download_quality": 90,
  "upload_quality": null,
  "download_netem_params": {
    "packet_loss_percent": 0.3,
    "delay_ms": 10,
    "jitter_ms": 3,
    "corruption_percent": 0.001,
    "delay_distribution": "normal"
  },
  "upload_netem_params": {
    "packet_loss_percent": 5.5,
    "delay_ms": 140,
    "jitter_ms": 25,
    "corruption_percent": 0.2,
    "delay_distribution": "paretonormal"
  }
}
```

## 4) Clear all QoS rules

```bash
curl -X DELETE "$BASE_URL/interface/$RESERVATION_ID/qos" \
  -H "Authorization: Bearer $TOKEN"
```

Example response:

```json
{
  "message": "QoS cleared successfully"
}
```

## 5) Common error examples

Invalid range (HTTP 422):

```json
{
  "detail": "download_speed_kbit must be between 1 and 1000000"
}
```

Network not active (HTTP 409):

```json
{
  "detail": "Cannot apply QoS: network is not active for this reservation"
}
```

Reservation not found/expired (HTTP 404):

```json
{
  "detail": "Reservation not found"
}
```

---

# Implementation Roadmap

The feature is implemented in **4 sequential phases**. Each phase is independent but parts of the implementation unlock subsequent phases. Backend comes before Frontend to establish API contracts first.

## Phase 1: API - Bandwidth Throttling (Speed)

**Objective**: Implement POST/GET/DELETE endpoints for download/upload speed throttling only. No link quality yet.

**Files to create/modify**:
- `wilab/network/commands.py` - add `execute_tc()` wrapper
- `wilab/models.py` - add throttling models
- `wilab/network/qos.py` - new QosManager with speed logic
- `wilab/api/routes/qos.py` - new API routes (speed-only)
- `wilab/wifi/manager.py` - integrate cleanup
- `tests/test_qos.py` - throttling tests

**Swagger Documentation**:

```yaml
/api/v1/interface/{reservation_id}/qos:
  post:
    summary: Apply or update bandwidth throttling
    tags:
      - QoS
    parameters:
      - name: reservation_id
        in: path
        required: true
        schema:
          type: string
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              download_speed_kbit:
                type: integer
                nullable: true
                description: "Download speed limit in kbit/s (1-1000000) or null to reset"
                example: 8000
              upload_speed_kbit:
                type: integer
                nullable: true
                description: "Upload speed limit in kbit/s (1-1000000) or null to reset"
                example: 3000
            minProperties: 1
    responses:
      200:
        description: Throttling applied successfully
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/QosStatus'
      409:
        description: Network not active on this reservation
      422:
        description: Invalid speed range or format
  get:
    summary: Get current speed throttling status
    tags:
      - QoS
    parameters:
      - name: reservation_id
        in: path
        required: true
        schema:
          type: string
    responses:
      200:
        description: Current QoS status
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/QosStatus'
      404:
        description: Reservation not found
  delete:
    summary: Clear all QoS rules (throttle + quality)
    tags:
      - QoS
    parameters:
      - name: reservation_id
        in: path
        required: true
        schema:
          type: string
    responses:
      204:
        description: All QoS rules cleared
      404:
        description: Reservation not found

components:
  schemas:
    QosStatus:
      type: object
      properties:
        interface:
          type: string
          example: "wlan0"
        active:
          type: boolean
        download_speed_kbit:
          type: integer
          nullable: true
          example: 8000
        upload_speed_kbit:
          type: integer
          nullable: true
          example: 3000
        download_quality:
          type: integer
          nullable: true
        upload_quality:
          type: integer
          nullable: true
```

**Tasks**:

- [x] **P1.1** Add `execute_tc()` wrapper in `wilab/network/commands.py`
  - Pattern: mirror `execute_iptables()` and `execute_iw()`
  - Handle timeout, errors, and logging

- [x] **P1.2** Create Pydantic models in `wilab/models.py`
  - `QosThrottleRequest`: `download_speed_kbit`, `upload_speed_kbit` (both Optional[int])
  - `QosStatus`: full QoS state including speeds
  - Validation: each field 1–1,000,000 or None
  - Validation: at least one field in request must be non-None

- [x] **P1.3** Create `QosManager` in `wilab/network/qos.py`
  - Class composition into `NetworkManager`
  - `apply_throttle(interface, download_kbit, upload_kbit)` - HTB setup
  - `clear_throttle(interface)` - full cleanup
  - `get_status(interface) -> QosStatus` - current state
  - IFB allocation/tracking
  - State persistence (in-memory dict per interface)

- [x] **P1.4** Create API routes in `wilab/api/routes/qos.py`
  - `POST /interface/{reservation_id}/qos` - call manager.apply_throttle() 
  - `GET /interface/{reservation_id}/qos` - call manager.get_status()
  - `DELETE /interface/{reservation_id}/qos` - call manager.clear_throttle()
  - Bearer token required on all endpoints
  - Validate network is active before apply
  - Register in `wilab/api/routes/__init__.py`
  - Include full Swagger docs with schemas

- [x] **P1.5** Integrate cleanup in `wilab/wifi/manager.py`
  - Call `qos_manager.clear_throttle()` before `hostapd` stop
  - Handle exceptions gracefully

- [x] **P1.6** Tests in `tests/test_qos.py`
  - Model validation (ranges, None handling)
  - tc command generation (mocked)
  - IFB allocation logic
  - Lifecycle: apply → update → clear
  - Download-only, upload-only, both
  - Idempotency tests
  - API endpoint tests (mock manager)

---

## Phase 2: API - Link Quality Degradation (Quality)

**Objective**: Extend Phase 1 API to include quality score (0–100%) and advanced netem parameters.

**Files to modify**:
- `wilab/models.py` - add quality models
- `wilab/network/qos.py` - extend QosManager with quality logic
- `wilab/api/routes/qos.py` - update endpoints with quality fields
- `tests/test_qos.py` - add quality tests

**Swagger Documentation**:

```yaml
/api/v1/interface/{reservation_id}/qos:
  post:
    summary: Apply or update QoS (throttling + quality)
    requestBody:
      content:
        application/json:
          schema:
            type: object
            properties:
              download_speed_kbit:
                type: integer
                nullable: true
              upload_speed_kbit:
                type: integer
                nullable: true
              download_quality:
                type: integer
                nullable: true
                minimum: 0
                maximum: 100
                description: "Link quality 0-100% (null to reset)"
              upload_quality:
                type: integer
                nullable: true
                minimum: 0
                maximum: 100
              download_quality_advanced:
                $ref: '#/components/schemas/QosQualityAdvanced'
              upload_quality_advanced:
                $ref: '#/components/schemas/QosQualityAdvanced'
    responses:
      200:
        description: QoS applied
        content:
          application/json:
            schema:
              allOf:
                - $ref: '#/components/schemas/QosStatus'
                - type: object
                  properties:
                    download_netem_params:
                      $ref: '#/components/schemas/NetemParams'
                    upload_netem_params:
                      $ref: '#/components/schemas/NetemParams'

components:
  schemas:
    QosQualityAdvanced:
      type: object
      properties:
        packet_loss_percent:
          type: number
          minimum: 0
          maximum: 100
        delay_ms:
          type: integer
          minimum: 0
          maximum: 5000
        jitter_ms:
          type: integer
          minimum: 0
          maximum: 1000
        corruption_percent:
          type: number
          minimum: 0
          maximum: 5
        delay_distribution:
          type: string
          enum: [normal, pareto, paretonormal]
          default: normal
    
    NetemParams:
      type: object
      properties:
        packet_loss_percent:
          type: number
        delay_ms:
          type: integer
        jitter_ms:
          type: integer
        corruption_percent:
          type: number
        delay_distribution:
          type: string
```

**Tasks**:

- [x] **P2.1** Add quality models in `wilab/models.py`
  - `QosQualityAdvanced`: all 5 fields with ranges
  - Enum for `delay_distribution`
  - Update `QosRequest` with quality fields
  - `NetemParams`: resolved parameters sent in response

- [x] **P2.2** Implement quality→netem formula in `QosManager`
  - `quality_to_netem_params(quality: int) -> NetemParams`
  - Quadratic/cubic formulas as documented
  - If advanced override provided, use instead of formula

- [x] **P2.3** Extend QosManager with quality management
  - `apply_quality(interface, direction, quality, quality_advanced)`
  - Chain netem under HTB (parent 1:10, handle 10:)
  - Create HTB if quality-only (no throttle)
  - Use `tc qdisc change` for live updates
  - `clear_quality(interface)` without losing throttle

- [x] **P2.4** Update API routes for quality fields
  - POST endpoint accepts quality + advanced params
  - GET returns netem_params resolved
  - Validation: quality 0–100 or None
  - Swagger docs updated with all schemas

- [x] **P2.5** Tests for quality
  - Formula validation (edge cases: 0, 50, 100)
  - Advanced override precedence
  - netem command generation
  - Combined throttle+quality tests
  - Quality-only (HTB created)

---

## Phase 3: Frontend - Bandwidth Throttling UI (Speed)

**Objective**: Implement speed throttling UI components and service methods.

**Files to create/modify**:
- `frontend/src/app/models/network.models.ts` - add QoS types
- `frontend/src/app/services/wilab-api.service.ts` - add QoS service methods
- `frontend/src/app/components/qos-dialog/` - new QosDialogComponent
- `frontend/src/app/components/network-card/` - integrate QoS buttons

**Tasks**:

- [ ] **P3.1** Add TypeScript models in `network.models.ts`
  - `QosRequest` interface
  - `QosStatus` interface
  - Extend `NetworkStatus` with optional `qos` field

- [ ] **P3.2** Add service methods in `wilab-api.service.ts`
  - `applyQos(reservationId, request): Observable<QosStatus>`
  - `getQos(reservationId): Observable<QosStatus>`
  - `clearQos(reservationId): Observable<void>`
  - Follow existing `enableInternet()` pattern

- [ ] **P3.3** Create QosDialogComponent standalone
  - Reactive form with speed fields (download, upload)
  - Toggles to enable/disable each direction
  - Slider/input for kbit/s with validation
  - Show current values on edit
  - Submit → call `applyQos()` from service
  - Error handling with snackbar

- [ ] **P3.4** Integrate into NetworkCardComponent
  - "QoS Settings" button (visible when network active)
  - Opens QosDialogComponent with current status
  - "Clear QoS" button (visible when throttle active)
  - Display throttle status: "↓ 8 Mbps / ↑ 3 Mbps"
  - Keep in sync with polling

---

## Phase 4: Frontend - Link Quality UI (Quality)

**Objective**: Extend Phase 3 UI with quality degradation controls.

**Tasks**:

- [ ] **P4.1** Extend models in `network.models.ts`
  - Add `QosQualityAdvanced` interface
  - Add quality fields to `QosRequest` and `QosStatus`

- [ ] **P4.2** Extend QosDialogComponent
  - Add quality sliders (0–100%) per direction
  - Show preview table: "Quality X% → loss Y%, delay Zms"
  - "Advanced" toggle to show/hide individual params
  - Advanced override fields: loss, delay, jitter, corruption, distribution
  - Validation: if advanced active, disable simple slider for that direction

- [ ] **P4.3** Display quality on NetworkCard
  - "Download quality: 85%" (or "N/A")
  - "Upload quality: 65%" (or "N/A")
  - Color indicator: green (90+), yellow (50–89), red (<50)
  - If advanced override, show resolved params

- [ ] **P4.4** Add quick presets (optional, nice-to-have)
  - Buttons: "Perfect (100%)", "Good (80%)", "Fair (50%)", "Poor (25%)", "Terrible (5%)"
  - Click → auto-fill quality sliders for both directions
