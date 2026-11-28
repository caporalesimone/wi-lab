# Feature: Interface Traffic Statistics

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Traffic of each access point interface: bytes, packets, errors and drops in both
directions, with rolling averages, to see the load of a network over time.

## Implementation Tasks

- [ ] Sample `/proc/net/dev` (or sysfs counters) per AP interface in the existing sampling loop
- [ ] Rolling averages over 1, 5 and 15 minutes
- [ ] `traffic` section in `GET /access-point/{reservation_id}`
- [ ] Same timestamps and sampling as the client statistics ([statistics.md](../clients/statistics.md))

## API Proposal

### `GET /api/v2/access-point/{reservation_id}`

New `traffic` section in the answer (shortened).

Request: no body.

Response `200`:

```json
{
  "traffic": {
    "sampled_at": "2026-11-28T10:00:05Z",
    "tx": {
      "bytes": 450105464,
      "packets": 712868,
      "errors": 0,
      "dropped": 0,
      "kbit_1m": 74200,
      "kbit_5m": 31800,
      "kbit_15m": 12100
    },
    "rx": {
      "bytes": 433522625,
      "packets": 925891,
      "errors": 0,
      "dropped": 0,
      "kbit_1m": 2100,
      "kbit_5m": 900,
      "kbit_15m": 400
    }
  }
}
```

`tx` is what the access point sent to its clients (download for them), `rx` what it received.

## Testing

- [ ] Unit tests for the counters and averages

## Benefits

- **Visibility:** Network load over time, for tests and reports

## Breaking Changes

- None (additive section)

## Success Criteria

- ✅ Bytes, packets, errors and averages visible per network
