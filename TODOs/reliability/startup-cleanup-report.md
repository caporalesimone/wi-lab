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

## API Proposal

### `GET /api/v2/status`

New check `startup_cleanup` in `checks` (shortened).

Request: no body.

Response `200`:

```json
{
  "checks": {
    "startup_cleanup": {
      "ran_at": "2026-11-28T00:15:43Z",
      "removed": {
        "processes": 1,
        "firewall_rules": 6,
        "runtime_files": 4,
        "qos_devices": 0
      },
      "failed_steps": []
    }
  }
}
```

## Testing

- [ ] A startup with leftovers of each kind, and one with a failing step

## Benefits

- **Visibility:** Operators see crash leftovers without the journal

## Breaking Changes

- None (additive check)

## Success Criteria

- ✅ `GET /status` shows what the last startup cleaned and what failed
