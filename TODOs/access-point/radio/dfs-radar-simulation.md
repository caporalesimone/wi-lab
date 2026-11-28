# Feature: Simulated DFS Radar

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Simulate a radar detection on a DFS channel, so the AP leaves the channel as the
rules require, and see how clients react.

## Context

Runtime commands on a running AP (power change, channel switch, reload) have hung the lab VM twice (2026-11-23 and 2026-11-28) and detached the MT7921U from the VM. Try this on a test network first, with the lab owner's consent.

## Implementation Tasks

- [ ] Check the mt76 debugfs radar trigger on the MT7921U (`radar_trigger` or equivalent)
- [ ] Endpoint `POST /access-point/{reservation_id}/radar` (only on DFS channels)
- [ ] Report the channel the AP moved to (`channel` already follows hostapd after a radar event, REV-12)

## Testing

- [ ] Unit tests for the endpoint rules (DFS channels only)
- [ ] Real radio: the AP moves away, `GET /access-point` shows the new channel

## Benefits

- **Testing:** Client behaviour when the AP must leave a DFS channel

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ A simulated radar moves the AP and the API reports it
