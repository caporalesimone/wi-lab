# Feature: Environment Scan

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Scan the air with a free antenna: nearby networks, their channels, widths and
signal, and how busy each channel is. Helps to pick a clean channel and to
explain low throughput.

## Implementation Tasks

- [ ] `GET /api/v2/environment` runs a scan on a free antenna (2.4 and 5 GHz), or answers 503 if none is free
- [ ] Per network: SSID, BSSID, channel, width, signal, generation
- [ ] Per channel: number of networks and the strongest signal; suggested channel
- [ ] Restore the antenna afterwards; cache the result for a minute

## API Proposal

### `GET /api/v2/environment?band=5ghz`

Scan with a free antenna (cached for 60 s).

Request: no body.

Response `200`:

```json
{
  "scanned_at": "2026-11-28T10:00:00Z",
  "antenna": "wlx7419f817651c",
  "networks": [
    {
      "ssid": "office",
      "bssid": "aa:bb:cc:00:11:22",
      "band": "5ghz",
      "channel": 36,
      "channel_width": 80,
      "signal_dbm": -61,
      "generation": 6
    }
  ],
  "channels": [
    {
      "band": "5ghz",
      "channel": 36,
      "networks": 3,
      "strongest_dbm": -61
    },
    {
      "band": "5ghz",
      "channel": 149,
      "networks": 0,
      "strongest_dbm": null
    }
  ],
  "suggested": {
    "2.4ghz": 11,
    "5ghz": 149
  }
}
```

Errors: `503 / 1003 device_unavailable` when every antenna is reserved.

## Testing

- [ ] Parser tests with captured `iw scan` output

## Benefits

- **Test quality:** Clean channels and explainable results

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Nearby networks and channel use are listed
- ✅ A channel is suggested per band
