# Feature: Hotspot 2.0 / Passpoint

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Announce the network as a Hotspot 2.0 (Passpoint) network, so clients with a
matching profile connect by themselves, as on operator Wi-Fi.

## Implementation Tasks

- [ ] Requires 802.1X ([enterprise.md](../security/enterprise.md))
- [ ] hostapd `hs20=1`, `interworking=1`, `roaming_consortium`, `domain_name`, NAI realm
- [ ] Create section `passpoint` with the announced identifiers
- [ ] Document how to install a matching profile on Android and iOS

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: a phone with a profile connects without choosing the SSID

## Benefits

- **Coverage:** Operator and venue Wi-Fi behaviour

## Breaking Changes

- None (new optional section)

## Success Criteria

- ✅ A phone with a Passpoint profile connects automatically
