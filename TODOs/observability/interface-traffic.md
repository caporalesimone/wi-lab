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

## Testing

- [ ] Unit tests for the counters and averages

## Benefits

- **Visibility:** Network load over time, for tests and reports

## Breaking Changes

- None (additive section)

## Success Criteria

- ✅ Bytes, packets, errors and averages visible per network
