# Feature: Several Lab Hosts Behind One Frontend

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~3 days  

## Description

Manage more antennas than one host can carry (CPU and USB limits) by running
Wi-Lab on several hosts and presenting them as one bench.

## Implementation Tasks

- [ ] Measure how many antennas one host serves before CPU or USB limits ([vm-performance.md](vm-performance.md))
- [ ] Frontend or a small gateway that lists antennas of several Wi-Lab hosts and routes calls by antenna
- [ ] Reservation IDs unique across hosts

## Testing

- [ ] Two Wi-Lab hosts behind one frontend, reservations on both

## Benefits

- **Scale:** More antennas and testers on one bench

## Breaking Changes

- None

## Success Criteria

- ✅ Antennas of two hosts can be reserved from one place
