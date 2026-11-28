# Feature: Beacon Interval and DTIM Period

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Let a create set how often the AP sends beacons and how often it delivers
buffered broadcast traffic to sleeping clients (DTIM). Both affect power saving
and delivery delays of battery and IoT devices.

## Implementation Tasks

- [ ] Optional create fields `radio.beacon_interval_tu` (default 100) and `radio.dtim_period` (default 2)
- [ ] hostapd `beacon_int`, `dtim_period`; validate the ranges hostapd accepts
- [ ] Shown in `GET /access-point/{reservation_id}`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "radio": {
    "beacon_interval_tu": 200,
    "dtim_period": 3
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

Errors: `422 validation_error` with the field path (`beacon_interval_tu` 15-65535, `dtim_period` 1-255).

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "radio": {
    "band": "5ghz",
    "channel": 36,
    "beacon_interval_tu": 200,
    "dtim_period": 3
  }
}
```

## Testing

- [ ] Unit tests for the hostapd lines and the validation
- [ ] Real radio: check the values in the beacon with a scan from the spare antenna

## Benefits

- **Testing:** Power save, IoT and battery devices, multicast delivery delays

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Beacon interval and DTIM period appear in the beacon as requested
