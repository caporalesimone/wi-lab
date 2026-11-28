# Feature: Packet Capture Download

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Capture the traffic of a network and download it as a pcap file for Wireshark.

## Implementation Tasks

- [ ] `POST /access-point/{reservation_id}/capture` with a duration or size limit; `GET .../capture` downloads the file
- [ ] `tcpdump` on the AP interface, with an optional filter (host, port)
- [ ] Limits: one capture per network, maximum size, removed at the end of the reservation

## Testing

- [ ] Unit tests for the limits and the cleanup
- [ ] Real radio: a capture contains the phone's DHCP and DNS traffic

## Benefits

- **Diagnosis:** Protocol-level analysis of client problems

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A capture can be started, downloaded and is removed at the end
