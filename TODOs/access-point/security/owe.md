# Feature: OWE (Enhanced Open)

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Open networks with encryption (Opportunistic Wireless Encryption), and the
transition mode that pairs an open SSID with a hidden OWE one for old clients.

## Implementation Tasks

- [ ] Encryption `owe`: `wpa_key_mgmt=OWE`, `ieee80211w=2`
- [ ] Optional transition mode: a second BSS with `owe_transition_ifname` (needs [multi-ssid.md](../network/multi-ssid.md) or two antennas)
- [ ] Check MT7921U support

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: a recent phone connects with OWE

## Benefits

- **Coverage:** Enhanced Open networks of cafés and public venues

## Breaking Changes

- None (new encryption)

## Success Criteria

- ✅ A phone connects to an OWE network
