# Feature: Logs in the API

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Read the service log through the API, filtered by antenna and reservation, for
operators and for the new UI. The records already carry `ant=` and `res=`.

## Implementation Tasks

- [ ] Ring buffer of structured records (time, level, logger, antenna, reservation, message)
- [ ] `GET /api/v2/logs?level=&antenna=&reservation=&since=` and a stream
- [ ] Mask reservation IDs and secrets before exposing records
- [ ] Who may read them depends on [accounts.md](../frontend/accounts.md): logs contain SSIDs, MACs and other testers' reservations

## Testing

- [ ] Unit tests for the buffer, filters and masking

## Benefits

- **Operations:** Diagnosis without access to the host journal

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Logs can be filtered by antenna and reservation
- ✅ No secret is exposed
