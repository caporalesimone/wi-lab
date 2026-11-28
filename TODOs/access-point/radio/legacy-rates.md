# Feature: Legacy Modes and Basic Rates

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Pure 802.11b/g or 802.11a networks without 802.11n, and control over the data
rates the AP supports and requires. Today the oldest mode is `wpa1` (802.11a/g
only because TKIP turns HT off) and the rate set is hostapd's default.

## Implementation Tasks

- [ ] `radio.wifi_generation` value for legacy (e.g. `3`: 802.11a/g, no HT), with any encryption
- [ ] Optional `radio.supported_rates` and `radio.basic_rates` (hostapd `supported_rates`, `basic_rates`)
- [ ] A preset to drop the 802.11b rates on 2.4 GHz (no 1, 2, 5.5, 11 Mbit/s)
- [ ] Validation: basic rates are a subset of supported rates; rates valid for the band

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "radio": {
    "band": "2.4ghz",
    "channel": 6,
    "wifi_generation": 3,
    "supported_rates": [
      6,
      9,
      12,
      18,
      24,
      36,
      48,
      54
    ],
    "basic_rates": [
      6,
      12,
      24
    ]
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

Errors: `422` with the field path for an invalid value.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "radio": {
    "band": "2.4ghz",
    "channel": 6,
    "wifi_generation": 3,
    "supported_rates": [
      6,
      9,
      12,
      18,
      24,
      36,
      48,
      54
    ],
    "basic_rates": [
      6,
      12,
      24
    ]
  }
}
```

`wifi_generation: 3` means 802.11a/g without HT. Rates are in Mbit/s; `basic_rates` must be a subset of `supported_rates`.

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: the beacon shows the rates; an 802.11b-only client is refused when 802.11b is dropped

## Benefits

- **Coverage:** Old and embedded devices; networks without 802.11b

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Legacy networks and custom rate sets work on the real radio
