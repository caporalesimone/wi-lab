# Feature: Mixed WPA/WPA2 and Cipher Choice

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Mixed WPA/WPA2 networks (TKIP and CCMP) for old clients, and modern ciphers
such as GCMP-256. Today `wpa1` is TKIP only and WPA2/WPA3 use CCMP.

## Implementation Tasks

- [ ] Encryption `wpa1-wpa2`: `wpa=3`, `wpa_pairwise=TKIP`, `rsn_pairwise=CCMP` (802.11n off when TKIP is the group cipher)
- [ ] Optional `wifi.security.cipher`: `ccmp` (default), `gcmp`, `gcmp-256`, if the MT7921U supports them
- [ ] Read cipher support from `iw phy` (`Supported Ciphers`) and list it in `/capabilities`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "security": {
      "encryption": "wpa2",
      "password": "testpass123",
      "cipher": "gcmp-256"
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

Errors: `422` with the field path for an invalid value.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "wifi": {
    "security": {
      "encryption": "wpa2",
      "password": "testpass123",
      "cipher": "gcmp-256"
    }
  }
}
```

New encryption `wpa1-wpa2` for mixed TKIP/CCMP. `GET /antennas/{interface}/capabilities` adds `"ciphers": ["ccmp", "gcmp", "gcmp-256"]`.

## Testing

- [ ] Unit tests and validation
- [ ] Real radio: a WPA1-only client and a WPA2 client on the same mixed network

## Benefits

- **Coverage:** Old clients on mixed networks; modern ciphers

## Breaking Changes

- None (new options)

## Success Criteria

- ✅ Mixed mode serves WPA1 and WPA2 clients
- ✅ Only supported ciphers are offered
