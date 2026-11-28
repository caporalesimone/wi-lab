# Feature: Protected Management Frames Choice

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Choose Protected Management Frames (PMF, 802.11w) on WPA2 networks: off,
optional or required. Today WPA2 has none, WPA3 requires it and WPA2/WPA3
makes it optional.

## Implementation Tasks

- [ ] Optional `wifi.security.pmf`: `off`, `optional`, `required`; hostapd `ieee80211w=0/1/2`
- [ ] Validation: WPA3 always `required`; open and WPA1 always `off`
- [ ] Shown in `GET /access-point/{reservation_id}`

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
      "pmf": "required"
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

Errors: `422 validation_error` with the field path (`wifi.security.pmf: wpa3 requires required`).

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
      "pmf": "required"
    }
  }
}
```

`pmf`: `off`, `optional`, `required`. Default: `off` for WPA2, `required` for WPA3, `optional` for WPA2/WPA3.

## Testing

- [ ] Unit tests for the hostapd lines and the validation
- [ ] Real radio: a client without PMF is refused with `required`

## Benefits

- **Testing:** Clients without PMF support, or that refuse it

## Breaking Changes

- None (optional field, default unchanged)

## Success Criteria

- ✅ The three PMF modes work on WPA2
- ✅ Invalid combinations answer 422
