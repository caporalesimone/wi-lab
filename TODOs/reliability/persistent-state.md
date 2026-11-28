# Feature: Persistent State Across Restarts

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Keep reservations (and optionally running networks) across a service restart.
Today they are in memory: a restart ends every reservation and the clients get
`reservation_not_found`.

## Implementation Tasks

- [ ] Decide what survives: reservations only, or reservations plus the networks restarted from their create request (ARCH-3 already stores it)
- [ ] Storage: a JSON file written atomically, or SQLite, under `/var/lib/wilab`
- [ ] At startup: restore, drop expired reservations, restart networks or mark them stopped
- [ ] Keep the startup cleanup consistent with restored state

## API Proposal

### `GET /api/v2/status`

New check `restored_state` after a restart (shortened).

Request: no body.

Response `200`:

```json
{
  "checks": {
    "restored_state": {
      "restored_at": "2026-11-28T00:15:43Z",
      "reservations": 2,
      "access_points_restarted": 1,
      "dropped_expired": 1,
      "errors": []
    }
  }
}
```

Reservations and access points keep their IDs and answers; no other API change.

## Testing

- [ ] Restart with active reservations: they survive with the right expiry
- [ ] Corrupt or old state file: ignored with a warning

## Benefits

- **Reliability:** A service restart (update, crash) does not end every test

## Breaking Changes

- None

## Success Criteria

- ✅ Reservations survive a restart
- ✅ A broken state file does not stop the service
