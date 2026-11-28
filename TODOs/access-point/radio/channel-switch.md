# Feature: Channel Switch on a Running AP

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Move a running AP to another channel with a channel switch announcement (CSA),
to test whether clients follow it, as they must after a radar detection.

## Context

Runtime commands on a running AP (power change, channel switch, reload) have hung the lab VM twice (2026-11-23 and 2026-11-28) and detached the MT7921U from the VM. Try this on a test network first, with the lab owner's consent.

## Implementation Tasks

- [ ] Endpoint `POST /access-point/{reservation_id}/channel-switch` with channel and width
- [ ] `hostapd_cli chan_switch <count> <freq> ...`; validate the target like a create
- [ ] Update the network's channel, subnet rules unchanged; the watchdog must not take the switch for a fault
- [ ] Report clients that did not follow (gone after the switch)

## Testing

- [ ] Unit tests with a mocked control socket
- [ ] Real radio, on a test network only: a phone stays connected after the switch

## Benefits

- **Testing:** Client behaviour on channel changes and radar-driven moves

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ A running AP moves channel and a phone follows it
- ✅ The watchdog does not restart the AP during the switch
