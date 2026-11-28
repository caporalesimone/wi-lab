# Feature: Client Event Log

**Priority:** 2 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Record what happens to clients on a network: authentications, associations,
refusals with their reason code, disconnections, DHCP leases. Today the only
trace is hostapd's syslog lines, and refusals are only at debug level.

## Context

On 2026-11-27 a Wi-Fi 6-only network (`enable_generation_fallback: false`) was not
joined by a phone, and hostapd logged nothing at its normal level: the reason had
to be inferred. This feature makes such refusals visible.

## Implementation Tasks

- [ ] Read hostapd events from the control socket (`AP-STA-CONNECTED`, `AP-STA-DISCONNECTED`, `AP-STA-POSSIBLE-PSK-MISMATCH`, EAP events)
- [ ] Refusals at association with their status code (e.g. generation required, PMF required), from hostapd's debug output or a monitor capture
- [ ] DHCP events from dnsmasq (lease, renew, release)
- [ ] `GET /access-point/{reservation_id}/events` (last N per network) and the same events in the stream ([event-stream.md](event-stream.md))

## Testing

- [ ] Parser tests with captured hostapd and dnsmasq output
- [ ] Real radio: wrong password, refused generation and a normal connection each produce the right events

## Benefits

- **Diagnosis:** Why a client cannot connect, without reading the journal

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Wrong password, refused association and DHCP lease are visible per network
