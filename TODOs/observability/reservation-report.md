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

## Testing

- [ ] Unit tests for the report content of a full reservation cycle

## Benefits

- **Traceability:** Test results with the exact conditions they ran in

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ A finished reservation has a complete report
