# Feature: Several SSIDs on One Antenna

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Run more than one network on one antenna (multi-BSS), for example a guest and a
main network with different security, sharing the channel.

## Implementation Tasks

- [ ] Check that the MT7921U supports several AP interfaces (`iw phy` interface combinations) and how many
- [ ] hostapd: extra `bss=` sections, one per SSID, each with its security and MAC address
- [ ] API design: several networks under one reservation (`/access-point/{reservation_id}/bss/{n}`?) or one create with a list
- [ ] Separate subnet, DHCP and firewall rules per BSS
- [ ] Watchdog: one hostapd process, several BSSes

## Testing

- [ ] Unit tests for the configuration and the per-BSS rules
- [ ] Real radio: two SSIDs visible and usable at the same time

## Benefits

- **Coverage:** Guest and main networks side by side, as in a home or office router

## Breaking Changes

- None if added as a new optional structure

## Success Criteria

- ✅ Two SSIDs run on one antenna, each with its own security and subnet
- ✅ Not offered on adapters that do not support it
