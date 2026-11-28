# Feature: Extend a Reservation

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Give a reservation more time without releasing it, so a long test does not lose
its antenna and its network.

## Implementation Tasks

- [ ] `PATCH /reservations/{reservation_id}` with `duration_seconds` (new total) or `extend_seconds`
- [ ] Respect `max_seconds` and `allow_unlimited` of `reservation_policy`
- [ ] The running network keeps going; `expires_at` changes everywhere (`/antennas`, `GET /access-point`)
- [ ] Refuse during a USB recovery or after the reservation ended (404 with the reason)

## API Proposal

### `PATCH /api/v2/reservations/{reservation_id}`

Give the reservation more time.

Request:

```json
{
  "extend_seconds": 1800
}
```

Response `200`:

```json
{
  "reservation_id": "a1b2c3d4",
  "interface": "wlx7419f8176286",
  "display_name": "antenna-1",
  "expires_at": "2026-11-28T11:30:00Z",
  "expires_in": 5400
}
```

Errors: `404` with `detail.reason` when the reservation is gone; `422 validation_error` with the field path (`extend_seconds: the total would exceed max_seconds`); `503 / 1002 device_recovering` during a USB recovery.

`duration_seconds` (new total from now) is accepted instead of `extend_seconds`; `0` asks for unlimited when `allow_unlimited` is true.

## Testing

- [ ] Unit tests for the limits and the 404 reasons
- [ ] The network expiry follows the new time

## Benefits

- **Usability:** Long tests without re-reserving and re-creating

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ A reservation is extended within the policy
- ✅ The network stops at the new time
