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

## API Proposal

### `POST /api/v2/bookings`

Book an antenna for a future slot.

Request:

```json
{
  "start_at": "2026-11-29T09:00:00Z",
  "duration_seconds": 3600,
  "interface": null
}
```

Response `201`:

```json
{
  "booking_id": "b-7f3a",
  "interface": "wlx7419f817651c",
  "start_at": "2026-11-29T09:00:00Z",
  "end_at": "2026-11-29T10:00:00Z"
}
```

Errors: `409 / 1018 slot_taken` (new code) when no antenna is free in the slot; `422 validation_error` with the field path.

### `GET /api/v2/bookings`

The bookings (own ones, or all for an administrator).

Request: no body.

Response `200`:

```json
[
  {
    "booking_id": "b-7f3a",
    "interface": "wlx7419f817651c",
    "start_at": "2026-11-29T09:00:00Z",
    "end_at": "2026-11-29T10:00:00Z",
    "reservation_id": null
  }
]
```

### `DELETE /api/v2/bookings/{booking_id}`

Cancel a booking.

Request: no body.

Response `200`:

```json
{
  "detail": "Booking b-7f3a cancelled"
}
```

### `POST /api/v2/reservations`

Wait in the queue when no antenna is free (`wait: true`).

Request:

```json
{
  "duration_seconds": 1800,
  "wait": true
}
```

Response `202`:

```json
{
  "queue_id": "q-19",
  "position": 2,
  "status_url": "/api/v2/queue/q-19"
}
```

`GET /api/v2/queue/{queue_id}` answers the position, then the reservation (`200`, same body as a normal reserve) when it is granted.

## Testing

- [ ] Unit tests for overlaps, queue order and expiry

## Benefits

- **Sharing:** Several testers and CI jobs on one bench

## Breaking Changes

- None (new options)

## Success Criteria

- ✅ Bookings never overlap
- ✅ Queued requests are served in order
