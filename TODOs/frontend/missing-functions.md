# Feature: API Functions Missing from the UI

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

Functions the API offers and today's UI does not use (Fable REV-15). The new UI
must have them; some can go into today's UI meanwhile.

## Implementation Tasks

- [ ] Cancel a start: the API accepts `DELETE /access-point/{reservation_id}` (and the release) during `starting`; a "Cancel start" button that stops the polling, calls the stop, then reads the state
- [ ] Watchdog restarts: `restarts` of `GET /access-point` ("AP restarts n, DHCP m, last <reason> at <time>") when `ap + dhcp > 0`
- [ ] Start errors: `error.message` and `error.stage` of `start_failed` under the state, on every card and after a reload (today only a toast)
- [ ] Choose the antenna: send `interface` in `POST /reservations`, offering the free antennas of `GET /antennas`
- [ ] Antenna health: `health` of `GET /antennas/{interface}` (budgets, quarantines, USB resets) on an antenna detail page

## Testing

- [ ] Frontend specs for each function

## Benefits

- **Usability:** Testers use everything the API offers

## Breaking Changes

- None

## Success Criteria

- ✅ Each listed function is available in the UI
