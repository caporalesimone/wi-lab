# Feature: Management Frame Capture with the Spare Antenna

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Put a free antenna in monitor mode on the channel of a running network and
capture its 802.11 management frames (beacons, probes, authentication,
association requests and responses), to see what a client asks for and why the
AP refuses it.

## Context

On 2026-11-27 a manual scan with the spare antenna showed what the AP announced
(Wi-Fi 6 capabilities, `BSS Color Disabled`, the HE membership selector). A
capture of the phone's association request would have shown directly whether it
offered Wi-Fi 6.

## Implementation Tasks

- [ ] Use an antenna that is not reserved; refuse if none is free
- [ ] Monitor interface on the AP's channel and width; `tcpdump` with a management frame filter
- [ ] Download as pcap; decoded summary of association requests (capabilities offered: HT, VHT, HE) in the API
- [ ] Restore the antenna to managed and down at the end

## Testing

- [ ] Unit tests for the setup and the restore
- [ ] Real radio: the association request of a phone shows its capabilities

## Benefits

- **Diagnosis:** Client capabilities and refusal reasons straight from the air

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Association requests of a client are captured and decoded
- ✅ The antenna is back in the pool afterwards
