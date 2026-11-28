# Feature: Scheduled Reservations and Queue

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

Book an antenna for a future time slot, or wait in a queue for the next free
one, so several testers share the bench without conflicts.

## Implementation Tasks

- [ ] Bookings with start time and duration; a booked antenna is not given to others in that slot
- [ ] Queue: `POST /reservations` with `wait: true` answers with a position, and the reservation when it is granted
- [ ] Notify the tester when the booking starts ([webhooks.md](../events/webhooks.md))
- [ ] Needs persistent state ([persistent-state.md](../reliability/persistent-state.md)) to survive a restart

## Testing

- [ ] Unit tests for overlaps, queue order and expiry

## Benefits

- **Sharing:** Several testers and CI jobs on one bench

## Breaking Changes

- None (new options)

## Success Criteria

- ✅ Bookings never overlap
- ✅ Queued requests are served in order
