# Feature: Timed Scenarios

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Run a list of timed steps on a reservation (at 30 s Internet off, at 60 s QoS
"3G", at 90 s a client disconnected...), so a test is repeatable and automated.

## Implementation Tasks

- [ ] `POST /reservations/{reservation_id}/scenario` with a JSON list of `{at_seconds, action, parameters}`
- [ ] Actions: the existing ones (Internet, QoS profile) and the faults ([fault-injection.md](fault-injection.md))
- [ ] Progress and results in `GET .../scenario` and in the event stream
- [ ] Stop on reservation end; one scenario per reservation

## Testing

- [ ] Unit tests with a fake clock for timing and failure of a step

## Benefits

- **Automation:** Repeatable tests without a script on the tester's side

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A scenario runs its steps on time and reports each result
