# Feature: Startup Cleanup Report in the API

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Show in the API what the last startup cleaned up and what it could not. The
cleanup itself is done (`wilab/runtime_cleanup.py`, Fable STAB-4): orphan hostapd
and dnsmasq processes, stale firewall rules and captive portal chains, runtime
files and QoS devices are removed and logged, but only the journal shows it.

## Implementation Tasks

- [ ] Record the result of each cleanup step at startup (counts per kind, failures)
- [ ] `checks.startup_cleanup` in `GET /status`: time, counts, failed steps
- [ ] Decide whether a failed step keeps `service.health` `degraded` until a later cleanup succeeds

## Testing

- [ ] A startup with leftovers of each kind, and one with a failing step

## Benefits

- **Visibility:** Operators see crash leftovers without the journal

## Breaking Changes

- None (additive check)

## Success Criteria

- ✅ `GET /status` shows what the last startup cleaned and what failed
