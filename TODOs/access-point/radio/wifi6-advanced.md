# Feature: Advanced Wi-Fi 6 Settings

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day (if the driver allows it)  

## Description

Wi-Fi 6 specific settings: BSS color, Target Wake Time (TWT), OFDMA and MU-MIMO
options. Today Wi-Fi 6 networks announce what hostapd reads from the driver.

## Context

Measured on 2026-11-27: the MT7921U announces Wi-Fi 6 in AP mode with `BSS Color
Disabled` (no `BSS_COLOR` feature in `iw phy`) and smaller HE capabilities than in
station mode (no beamforming). A Redmi Note 14 Pro 5G saw the network as Wi-Fi 6
but connected as Wi-Fi 5, and did not try a Wi-Fi 6-only network
(`enable_generation_fallback: false`). Not yet checked with another Wi-Fi 6 client:
do that first, it tells whether this feature is possible on this adapter.

## Implementation Tasks

- [ ] Check which `he_*` options the MT7921U accepts in AP mode (the driver has no BSS color support)
- [ ] Optional `radio.he` section for the supported ones only (`he_bss_color`, `he_twt_*`, `he_mu_*`)
- [ ] Hide the section on adapters that do not support it (from `iw phy`)

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "radio": {
    "wifi_generation": 6,
    "he": {
      "bss_color": 12,
      "twt": true
    }
  }
}
```

Response `202`:

```json
{
  "runtime_state": "starting",
  "active": false
}
```

Errors: `422 validation_error` with the field path (`radio.he.bss_color: not supported by this antenna`).

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "radio": {
    "wifi_generation": 6,
    "he": {
      "bss_color": 12,
      "bss_color_disabled": false,
      "twt": true
    }
  }
}
```

`GET /antennas/{interface}/capabilities` lists the `he` options each antenna supports, e.g. `"he_options": ["twt"]`.

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio with a Wi-Fi 6 client that negotiates HE

## Benefits

- **Coverage:** Wi-Fi 6 power save and multi-user features

## Breaking Changes

- None (optional section)

## Success Criteria

- ✅ Supported options are applied and visible in the beacon
- ✅ Unsupported adapters do not offer them
