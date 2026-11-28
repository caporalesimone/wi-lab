# Feature: Beacon Interval and DTIM Period

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Let a create set how often the AP sends beacons and how often it delivers
buffered broadcast traffic to sleeping clients (DTIM). Both affect power saving
and delivery delays of battery and IoT devices.

## Implementation Tasks

- [ ] Optional create fields `radio.beacon_interval_tu` (default 100) and `radio.dtim_period` (default 2)
- [ ] hostapd `beacon_int`, `dtim_period`; validate the ranges hostapd accepts
- [ ] Shown in `GET /access-point/{reservation_id}`

## Testing

- [ ] Unit tests for the hostapd lines and the validation
- [ ] Real radio: check the values in the beacon with a scan from the spare antenna

## Benefits

- **Testing:** Power save, IoT and battery devices, multicast delivery delays

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Beacon interval and DTIM period appear in the beacon as requested
