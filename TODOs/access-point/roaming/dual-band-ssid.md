# Feature: One SSID on 2.4 and 5 GHz

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

The same network on 2.4 GHz and 5 GHz at once, one antenna per band, like a
dual-band home router, to test band choice and band steering of clients.

## Implementation Tasks

- [ ] Shares Part 1 of [fast-roaming.md](fast-roaming.md): one reservation for both antennas, one subnet
- [ ] Create body with two `radio` sections (2.4 and 5 GHz), one `wifi` section
- [ ] Optional band steering: refuse 2.4 GHz associations of dual-band clients for a few seconds
- [ ] Client list with the band of each client

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "radios": [
    {
      "band": "2.4ghz",
      "channel": 6
    },
    {
      "band": "5ghz",
      "channel": 36
    }
  ],
  "wifi": {
    "ssid": "lab-dual",
    "security": {
      "encryption": "wpa2",
      "password": "testpass123"
    }
  },
  "band_steering": true
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
  "radios": [
    {
      "interface": "wlx7419f8176286",
      "band": "2.4ghz",
      "channel": 6
    },
    {
      "interface": "wlx7419f817651c",
      "band": "5ghz",
      "channel": 36
    }
  ],
  "band_steering": true,
  "clients": [
    {
      "mac": "aa:bb:cc:dd:ee:ff",
      "band": "5ghz"
    }
  ]
}
```

Needs a reservation with both antennas (see [fast-roaming.md](fast-roaming.md)). `radios` replaces `radio` in this mode.

## Testing

- [ ] Unit tests for the paired configuration
- [ ] Real radio: a phone chooses 5 GHz; with 5 GHz off it moves to 2.4 GHz

## Benefits

- **Coverage:** Band choice and steering, as with real routers

## Breaking Changes

- None (new optional mode)

## Success Criteria

- ✅ One SSID runs on both bands
- ✅ The band of each client is visible
