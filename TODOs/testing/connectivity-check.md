# Feature: Connectivity Check Simulation

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Answer the connectivity checks of Android, iOS and Windows in a controlled way,
to test "connected, no Internet" separately from a captive portal.

## Implementation Tasks

- [ ] Create option `internet.check_answer`: `real` (default), `no_internet`, `captive`, `ok`
- [ ] Local DNS and HTTP answers for `connectivitycheck.gstatic.com`, `captive.apple.com`, `www.msftconnecttest.com` and others
- [ ] `ok` without real Internet: devices believe they are online

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "internet": {
    "enabled": false,
    "check_answer": "no_internet"
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
  "internet": {
    "enabled": false,
    "check_answer": "no_internet"
  }
}
```

`check_answer`: `real` (default), `no_internet`, `captive`, `ok` (devices believe they are online without real Internet).

## Testing

- [ ] Unit tests for the DNS and HTTP answers
- [ ] Real radio: Android and iOS show the expected state for each mode

## Benefits

- **Testing:** Operating system notifications and captive portal handling

## Breaking Changes

- None (optional field)

## Success Criteria

- ✅ Each mode produces the expected state on Android and iOS
