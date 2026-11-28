# Feature: Hotspot 2.0 / Passpoint

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Announce the network as a Hotspot 2.0 (Passpoint) network, so clients with a
matching profile connect by themselves, as on operator Wi-Fi.

## Implementation Tasks

- [ ] Requires 802.1X ([enterprise.md](../security/enterprise.md))
- [ ] hostapd `hs20=1`, `interworking=1`, `roaming_consortium`, `domain_name`, NAI realm
- [ ] Create section `passpoint` with the announced identifiers
- [ ] Document how to install a matching profile on Android and iOS

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "security": {
      "encryption": "wpa2-enterprise"
    },
    "passpoint": {
      "domain": "wilab.lan",
      "nai_realm": "wilab.lan",
      "roaming_consortium": [
        "5a03ba0000"
      ],
      "venue_name": "Wi-Lab"
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

Errors: `422 validation_error` with the field path; Passpoint needs an `*-enterprise` encryption.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "wifi": {
    "passpoint": {
      "domain": "wilab.lan",
      "nai_realm": "wilab.lan",
      "roaming_consortium": [
        "5a03ba0000"
      ],
      "venue_name": "Wi-Lab"
    }
  }
}
```

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: a phone with a profile connects without choosing the SSID

## Benefits

- **Coverage:** Operator and venue Wi-Fi behaviour

## Breaking Changes

- None (new optional section)

## Success Criteria

- ✅ A phone with a Passpoint profile connects automatically
