# Feature: Client Isolation and Client Limit

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Two settings of one network: whether its clients can reach each other, and how
many clients it accepts. Wi-Lab isolates test networks from each other and from
the host, but clients of the same network always see each other.

## Implementation Tasks

- [ ] Optional create field `wifi.client_isolation` (default false): hostapd `ap_isolate=1`
- [ ] Optional create field `wifi.max_clients` (default: no limit): hostapd `max_num_sta`
- [ ] Both shown in `GET /access-point/{reservation_id}`
- [ ] Same-body check: different values are different settings (409 / 1008)

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: two phones cannot ping each other with isolation; a client beyond the limit is refused

## Benefits

- **Testing:** Devices that must see each other (casting, printers) or must not; a full network

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Isolation on and off verified with two clients
- ✅ The client limit refuses the next client
