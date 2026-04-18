# QoS (Quality of Service)

QoS lets you control **bandwidth** and **link quality** on a per-reservation basis. Download and upload are configured independently. Settings persist until you clear them or stop the network.

> **Prerequisite:** the network must be **active** on the reservation before applying QoS.

---

## Endpoints

| Method   | Path                                      | Description                  |
|----------|-------------------------------------------|------------------------------|
| `POST`   | `/api/v1/interface/{reservation_id}/qos`  | Apply or update QoS settings |
| `GET`    | `/api/v1/interface/{reservation_id}/qos`  | Get current QoS status       |
| `DELETE` | `/api/v1/interface/{reservation_id}/qos`  | Remove all QoS rules         |

All endpoints require `Authorization: Bearer <token>`.

---

## Update Semantics

Every `POST` is a **partial update**. Each field can be in one of three states:

| Field state              | Behaviour                                     |
|--------------------------|-----------------------------------------------|
| **Omitted** from body    | Keep the current value (no change)             |
| **Set to a value**       | Apply/update to that value                     |
| **Set to `null`**        | Reset that specific setting to inactive        |

`DELETE /qos` removes **everything** (speed + quality) at once.

---

## Parameters

### Speed (bandwidth throttling)

| Field                | Type           | Range           | Description                            |
|----------------------|----------------|-----------------|----------------------------------------|
| `download_speed_kbit`| `integer\|null`| 1 – 1 000 000   | Download cap in kbit/s (`null` = unlimited) |
| `upload_speed_kbit`  | `integer\|null`| 1 – 1 000 000   | Upload cap in kbit/s (`null` = unlimited)   |

### Quality (link impairment simulation)

| Field                       | Type           | Range  | Description                                     |
|-----------------------------|----------------|--------|-------------------------------------------------|
| `download_quality`          | `integer\|null`| 0 – 100 | Download link quality score (`null` = disabled) |
| `upload_quality`            | `integer\|null`| 0 – 100 | Upload link quality score (`null` = disabled)   |
| `download_quality_advanced` | `object\|null` | —      | Advanced override for download netem params      |
| `upload_quality_advanced`   | `object\|null` | —      | Advanced override for upload netem params        |

**100 = perfect link, 0 = severely degraded.**

The quality score is mapped to network impairments using a formula that keeps **80-100% nearly imperceptible** and makes degradation harsh below 30%:

| Quality | Packet Loss | Delay     | Jitter   | Corruption | Perceived          |
|---------|-------------|-----------|----------|------------|--------------------|
| 100     | 0%          | 0 ms      | 0 ms     | 0%         | Perfect            |
| 90      | 0.3%        | 10 ms     | 3 ms     | ~0%        | Near-perfect       |
| 75      | 1.9%        | 62 ms     | 19 ms    | 0.002%     | Slightly degraded  |
| 50      | 7.5%        | 250 ms    | 75 ms    | 0.125%     | Noticeable         |
| 25      | 16.9%       | 562 ms    | 169 ms   | 0.42%      | Poor               |
| 0       | 30%         | 1000 ms   | 300 ms   | 1%         | Nearly unusable    |

### Advanced Override

If you need precise control over individual impairment parameters instead of the formula, use the `*_quality_advanced` fields. When provided, the advanced object **replaces** the formula entirely.

| Field                 | Type    | Range       | Default  |
|-----------------------|---------|-------------|----------|
| `packet_loss_percent` | `float` | 0 – 100     | 0        |
| `delay_ms`            | `int`   | 0 – 5000    | 0        |
| `jitter_ms`           | `int`   | 0 – 1000    | 0        |
| `corruption_percent`  | `float` | 0 – 5       | 0        |
| `delay_distribution`  | `string`| `normal`, `pareto`, `paretonormal` | `normal` |

Delay distribution profiles:
- **normal** — Gaussian; typical for stable wired or good WiFi paths.
- **pareto** — Heavy-tail; models bursty wireless conditions.
- **paretonormal** — Mixed; often more realistic for real WiFi links.

---

## Usage Examples

All examples assume:

```
BASE=http://localhost:8080/api/v1
TOKEN=<your_auth_token>
RES=<reservation_id>
```

### 1. Limit download to 8 Mbit/s, upload to 3 Mbit/s

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 8000,
    "upload_speed_kbit": 3000
  }'
```

### 2. Set link quality to 80% download, 65% upload

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_quality": 80,
    "upload_quality": 65
  }'
```

### 3. Speed + quality combined

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download_speed_kbit": 8000,
    "upload_speed_kbit": 3000,
    "download_quality": 80,
    "upload_quality": 65
  }'
```

Response:

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
    "packet_loss_percent": 3.68,
    "delay_ms": 122,
    "jitter_ms": 37,
    "corruption_percent": 0.043,
    "delay_distribution": "normal"
  }
}
```

### 4. Advanced override (precise netem values)

Use this when you need exact impairment parameters instead of the formula mapping:

```bash
curl -X POST "$BASE/interface/$RES/qos" \
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

In this example download uses the formula (`quality=90`), while upload uses the exact values you specified.

### 5. Update only one setting (partial update)

Change download speed without touching anything else:

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"download_speed_kbit": 15000}'
```

### 6. Reset a single setting to unlimited/inactive

Reset download speed to unlimited (upload, quality, etc. stay as-is):

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"download_speed_kbit": null}'
```

Reset upload quality to inactive:

```bash
curl -X POST "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"upload_quality": null}'
```

### 7. Get current status

```bash
curl -X GET "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN"
```

### 8. Clear everything

```bash
curl -X DELETE "$BASE/interface/$RES/qos" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Error Responses

| Status | Cause                              | Example detail                                                    |
|--------|------------------------------------|-------------------------------------------------------------------|
| 401    | Missing or invalid token           | `"Not authenticated"`                                             |
| 404    | Reservation not found / expired    | `"Reservation not found"`                                         |
| 409    | Network not active                 | `"Cannot apply QoS: network is not active for this reservation"`  |
| 422    | Invalid parameter value            | `"download_speed_kbit must be between 1 and 1000000"`             |
| 422    | Empty body                         | `"At least one QoS field must be provided"`                       |

---

## Notes

- **QoS is cleared automatically** when the network is stopped (`DELETE /network`).
- **QoS does not survive a network restart.** After stopping and starting the network you must re-apply settings.
- **Quality is interface-wide**, not per-client. All connected clients on the same AP share the impairment.
- Speed and quality are **independent**: you can use speed-only, quality-only, or both at the same time.
- The `download_netem_params` / `upload_netem_params` fields in the response show the **resolved** impairment values (from the formula or from the advanced override). They are read-only.
