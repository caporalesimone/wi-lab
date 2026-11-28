# Feature: Event Stream (SSE)

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Push what happens to the UI and to other clients instead of making them poll:
reservations, access points, watchdog repairs, quarantines and client events,
as one Server-Sent Events stream.

## Implementation Tasks

- [ ] `GET /api/v2/events` (stream, `text/event-stream`) and `GET /api/v2/events?since=<id>` for backfill
- [ ] Ring buffer of the last events (e.g. 1000) with increasing IDs; `Last-Event-ID` resumes a stream
- [ ] Event types: reservation created/released/expired, access point starting/active/start_failed/stopped, watchdog repair, quarantine, client events ([client-events.md](client-events.md))
- [ ] Filters: `?reservation=`, `?antenna=`
- [ ] Who may read which events depends on the accounts decision ([accounts.md](../frontend/accounts.md))

## API Proposal

### `GET /api/v2/events?reservation={id}&antenna={interface}`

The event stream (`Accept: text/event-stream`).

Request: no body.

Response `200`: no body.

Response `200` (`text/event-stream`), one event per message; `Last-Event-ID` resumes after a disconnect:

```text
id: 1042
event: access_point.active
data: {"time": "2026-11-28T10:00:04Z", "reservation": "a1b2c3d4", "antenna": "wlx7419f8176286", "channel": 36}
```

### `GET /api/v2/events?since=1000&limit=100`

The same events as JSON, for backfill.

Request: no body.

Response `200`:

```json
{
  "events": [
    {
      "id": 1042,
      "type": "access_point.active",
      "time": "2026-11-28T10:00:04Z",
      "reservation": "a1b2c3d4",
      "antenna": "wlx7419f8176286",
      "data": {
        "channel": 36
      }
    }
  ],
  "next": 1043
}
```

Event types: `reservation.created`, `reservation.released`, `reservation.expired`, `access_point.starting`, `access_point.active`, `access_point.start_failed`, `access_point.stopped`, `watchdog.repair`, `antenna.quarantined`, `antenna.recovered`, and the client events of [client-events.md](client-events.md).

## Testing

- [ ] Unit tests for the ring buffer, IDs and resume
- [ ] API tests with several concurrent streams and disconnects

## Benefits

- **UI:** Live updates without polling
- **Integration:** Base for webhooks and reports

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Events arrive in order and a client can resume after a disconnect
- ✅ The frontend can drop most of its polling
