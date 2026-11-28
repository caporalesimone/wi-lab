# Feature: Logs in the API

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Read the service log through the API, filtered by antenna and reservation, for
operators and for the new UI. The records already carry `ant=` and `res=`.

## Implementation Tasks

- [ ] Ring buffer of structured records (time, level, logger, antenna, reservation, message)
- [ ] `GET /api/v2/logs?level=&antenna=&reservation=&since=` and a stream
- [ ] Mask reservation IDs and secrets before exposing records
- [ ] Who may read them depends on [accounts.md](../frontend/accounts.md): logs contain SSIDs, MACs and other testers' reservations

## API Proposal

### `GET /api/v2/logs?level=WARNING&antenna={interface}&reservation={id}&since=2026-11-28T09:00:00Z&limit=200`

Log records, newest last.

Request: no body.

Response `200`:

```json
{
  "records": [
    {
      "time": "2026-11-28T09:12:31Z",
      "level": "WARNING",
      "logger": "wilab.wifi.watchdog",
      "antenna": "wlx7419f8176286",
      "reservation": "a1b2…",
      "message": "AP restore retry on wlx7419f8176286 failed"
    }
  ],
  "next": "2026-11-28T09:12:31.204Z"
}
```

### `GET /api/v2/logs/stream`

The same records as a stream (`text/event-stream`), with the same filters.

Request: no body.

Response `200`: no body.

Reservation IDs are shortened and secrets removed before a record leaves the service.

## Testing

- [ ] Unit tests for the buffer, filters and masking

## Benefits

- **Operations:** Diagnosis without access to the host journal

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Logs can be filtered by antenna and reservation
- ✅ No secret is exposed
