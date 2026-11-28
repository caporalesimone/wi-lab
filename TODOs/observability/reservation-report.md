# Feature: Report per Reservation

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

A summary of everything that happened during a reservation, downloadable at the
end: settings used, clients and their statistics, events, throughput, watchdog
repairs and failures. Attachable to a test ticket.

## Implementation Tasks

- [ ] Collect per reservation: access point settings, client statistics, events, repairs, start attempts
- [ ] `GET /reservations/{reservation_id}/report` (JSON, optional HTML), available for a while after the end
- [ ] Built on [statistics.md](../clients/statistics.md) and [client-events.md](../events/client-events.md)

## API Proposal

### `GET /api/v2/reservations/{reservation_id}/report`

The report of a reservation, during it or up to 24 h after its end (`Accept: application/json` or `text/html`).

Request: no body.

Response `200`:

```json
{
  "reservation_id": "a1b2c3d4",
  "interface": "wlx7419f8176286",
  "started_at": "2026-11-28T09:00:00Z",
  "ended_at": "2026-11-28T10:00:00Z",
  "end_reason": "released",
  "access_points": [
    {
      "started_at": "2026-11-28T09:01:00Z",
      "stopped_at": "2026-11-28T09:58:00Z",
      "settings": {
        "radio": {
          "band": "5ghz",
          "channel": 36,
          "wifi_generation": 6
        }
      },
      "restarts": {
        "ap": 0,
        "dhcp": 0
      }
    }
  ],
  "clients": [
    {
      "mac": "12:ee:e6:97:b8:28",
      "hostname": "redmi-note-14",
      "generation": 5,
      "connected_seconds": 3300,
      "signal_avg_dbm": -51,
      "tx_bytes": 98000000,
      "rx_bytes": 12000000
    }
  ],
  "events": 42,
  "events_url": "/api/v2/events?reservation=a1b2c3d4"
}
```

Errors: `404` with `detail.reason` when the reservation never existed or its report expired.

## Testing

- [ ] Unit tests for the report content of a full reservation cycle

## Benefits

- **Traceability:** Test results with the exact conditions they ran in

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ A finished reservation has a complete report
