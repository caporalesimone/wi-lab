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
