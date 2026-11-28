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
