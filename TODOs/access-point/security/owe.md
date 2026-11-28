# Feature: OWE (Enhanced Open)

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Open networks with encryption (Opportunistic Wireless Encryption), and the
transition mode that pairs an open SSID with a hidden OWE one for old clients.

## Implementation Tasks

- [ ] Encryption `owe`: `wpa_key_mgmt=OWE`, `ieee80211w=2`
- [ ] Optional transition mode: a second BSS with `owe_transition_ifname` (needs [multi-ssid.md](../network/multi-ssid.md) or two antennas)
- [ ] Check MT7921U support

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "ssid": "lab-open",
    "security": {
      "encryption": "owe",
      "owe_transition": true
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
    "ssid": "lab-open",
    "security": {
      "encryption": "owe",
      "owe_transition": true,
      "transition_ssid": "lab-open-owe"
    }
  }
}
```

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: a recent phone connects with OWE

## Benefits

- **Coverage:** Enhanced Open networks of cafés and public venues

## Breaking Changes

- None (new encryption)

## Success Criteria

- ✅ A phone connects to an OWE network
