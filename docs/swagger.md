# Wi-Lab API Documentation

Wi-Lab provides interactive API documentation for testing and exploring endpoints.

---

## Access API Documentation

### Swagger UI (Interactive Testing - Recommended)

**URL:** `http://localhost:8080/docs`

**Features:**
- Interactive endpoint testing with real requests
- Try-it-out functionality with all parameters
- Full schema and model documentation
- Request/response visualization

**How to use:**
1. Open `http://localhost:8080/docs` in your browser
2. Click **"Authorize"** button (top-right)
3. Enter your `auth_token` from `config.yaml`
4. Browse endpoints and test interactively

### ReDoc (Read-Only Documentation)

**URL:** `http://localhost:8080/redoc`

Provides formatted API documentation without interactive testing.

### OpenAPI Specification

**Raw formats:**
- JSON: `http://localhost:8080/openapi.json`
- YAML: `http://localhost:8080/openapi.yaml`

---

## Quick Examples

### Example 1: Health Check (No Authentication)

```bash
# Simple health check
curl http://localhost:8080/api/v1/health
```

### Example 2: Create WiFi Network (With Authentication)

```bash
TOKEN="your-auth-token-from-config"
INTERFACE="wlx782051245264"

curl -X POST "http://localhost:8080/api/v1/interface/$INTERFACE/network" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ssid": "TestAP",
    "channel": 6,
    "band": "2.4ghz",
    "encryption": "wpa2",
    "password": "test1234",
    "tx_power_level": 4
  }'
```

**For all other endpoint examples and full API reference:** See Swagger UI at `http://localhost:8080/docs`

---

## Parameter Values and Enumerations

### Encryption Types

The `encryption` field accepts:
- `"open"` - No password required
- `"wpa2"` - WPA2 only (compatible with most devices)
- `"wpa3"` - WPA3 only (newer, more secure)
- `"wpa2-wpa3"` - WPA2/WPA3 compatible (recommended)

**Note:** When using `"open"` encryption, the `password` field is ignored.

### WiFi Bands

The `band` field accepts:
- `"2.4ghz"` - 2.4 GHz band (longer range, more interference)
  - Typical channels: 1-14 (varies by country/region)
- `"5ghz"` - 5 GHz band (shorter range, less interference)
  - Typical channels: 36-165 (varies by country/region)

### Channel Selection

Valid channels depend on the `band` specified:

**2.4 GHz Band:**
- Allowed channels: 1-14 (some regions only 1-13)
- Non-overlapping channels: 1, 6, 11 (use these when possible for minimal interference)

**5 GHz Band:**
- Allowed channels: 36, 40, 44, 48, 52-64, 100-144, 149-165
- More available channels than 2.4 GHz, typically less congestion
- Specific available channels depend on regulatory domain

**Example usage:**
```bash
# 2.4 GHz on channel 1
"band": "2.4ghz", "channel": 1

# 5 GHz on channel 44
"band": "5ghz", "channel": 44
```

### TX Power Levels

The `tx_power_level` field accepts integer values 1-4:
- `1` - Minimum power (~5 dBm) - shortest range, least interference
- `2` - Low power (~10 dBm) - reduced range for localized testing
- `3` - Medium power (~15 dBm) - balanced range and coverage
- `4` - Maximum power (~20 dBm) - maximum range and coverage

**Note:** Actual dBm values depend on WiFi interface hardware. Exact values reported in `txpower` endpoint response.

### Timeout Values

The `timeout` field specifies network lifetime in seconds:
- **Minimum:** 60 seconds
- **Maximum:** 86400 seconds (24 hours)
- **Default:** 3600 seconds (1 hour)

After timeout expires, the network automatically stops and cleans up.

### Boolean Flags

- `"hidden"` - SSID broadcast control
  - `true` - SSID hidden (clients must know exact name)
  - `false` - SSID visible (default)

- `"internet_enabled"` - Internet access control
  - `true` - NAT enabled (clients can reach Internet via upstream interface)
  - `false` - Isolated (clients can only reach each other and gateway)

---

## Full API Reference

For complete endpoint documentation with all parameters and response schemas, visit:
```
http://localhost:8080/docs
```

The Swagger UI provides:
- All endpoint definitions with detailed parameters
- Real-time interactive testing
- Request/response examples
- Data model schemas

---

## Documentation Links

- **Installation & Setup:** [installation-guide.md](installation-guide.md)
- **Network Management:** [networking.md](networking.md)
- **Troubleshooting:** [troubleshooting.md](troubleshooting.md)
- **Testing Guide:** [unit-testing.md](unit-testing.md)

---

**Interactive API testing available at:** `http://localhost:8080/docs`
