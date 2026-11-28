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

## API Proposal

### `POST /api/v2/reservations/{reservation_id}/scenario`

Start a scenario on the reservation.

Request:

```json
{
  "steps": [
    {
      "at_seconds": 30,
      "action": "internet",
      "parameters": {
        "enabled": false
      }
    },
    {
      "at_seconds": 60,
      "action": "qos_profile",
      "parameters": {
        "profile_id": "3g"
      }
    },
    {
      "at_seconds": 90,
      "action": "fault",
      "parameters": {
        "type": "client_disconnect",
        "mac": "aa:bb:cc:dd:ee:ff"
      }
    },
    {
      "at_seconds": 120,
      "action": "internet",
      "parameters": {
        "enabled": true
      }
    }
  ],
  "repeat": 1
}
```

Response `201`:

```json
{
  "scenario_id": "s-5",
  "state": "running",
  "started_at": "2026-11-28T10:00:00Z"
}
```

Errors: `404` with `detail.reason` when the reservation is gone; `409 / 1020 scenario_running` (new code); `422 validation_error` with the field path.

### `GET /api/v2/reservations/{reservation_id}/scenario`

Progress and the result of each step.

Request: no body.

Response `200`:

```json
{
  "scenario_id": "s-5",
  "state": "running",
  "steps": [
    {
      "at_seconds": 30,
      "action": "internet",
      "state": "done",
      "result": 200
    },
    {
      "at_seconds": 60,
      "action": "qos_profile",
      "state": "pending"
    }
  ]
}
```

### `DELETE /api/v2/reservations/{reservation_id}/scenario`

Stop the scenario (steps already applied stay).

Request: no body.

Response `200`:

```json
{
  "scenario_id": "s-5",
  "state": "stopped"
}
```

## Testing

- [ ] Unit tests with a fake clock for timing and failure of a step

## Benefits

- **Automation:** Repeatable tests without a script on the tester's side

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A scenario runs its steps on time and reports each result
