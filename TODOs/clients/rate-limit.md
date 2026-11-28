# Feature: Per-Client Rate Limit

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Limit the bandwidth of one client of a network, in download, upload or both.
The QoS profiles shape the whole network; this targets a single device.

## Implementation Tasks

- [ ] `POST /access-point/{reservation_id}/clients/{mac}/rate-limit` with `download_kbit`, `upload_kbit`; `DELETE` to clear
- [ ] `tc` HTB class per client (filter on the client's IP or MAC) on the AP interface, and on the IFB device for upload
- [ ] Must coexist with an active QoS profile (same qdisc tree)
- [ ] Limit shown in the client list

## Testing

- [ ] Unit tests for the `tc` commands and the validation
- [ ] Real radio: two phones, one limited, measured with a throughput test

## Benefits

- **Testing:** One slow client next to normal ones

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A client is limited and the others are not
- ✅ Works together with a QoS profile
