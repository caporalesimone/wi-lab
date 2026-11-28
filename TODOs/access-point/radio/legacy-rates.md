# Feature: Legacy Modes and Basic Rates

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Pure 802.11b/g or 802.11a networks without 802.11n, and control over the data
rates the AP supports and requires. Today the oldest mode is `wpa1` (802.11a/g
only because TKIP turns HT off) and the rate set is hostapd's default.

## Implementation Tasks

- [ ] `radio.wifi_generation` value for legacy (e.g. `3`: 802.11a/g, no HT), with any encryption
- [ ] Optional `radio.supported_rates` and `radio.basic_rates` (hostapd `supported_rates`, `basic_rates`)
- [ ] A preset to drop the 802.11b rates on 2.4 GHz (no 1, 2, 5.5, 11 Mbit/s)
- [ ] Validation: basic rates are a subset of supported rates; rates valid for the band

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: the beacon shows the rates; an 802.11b-only client is refused when 802.11b is dropped

## Benefits

- **Coverage:** Old and embedded devices; networks without 802.11b

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Legacy networks and custom rate sets work on the real radio
