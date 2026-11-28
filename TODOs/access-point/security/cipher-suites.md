# Feature: Mixed WPA/WPA2 and Cipher Choice

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Mixed WPA/WPA2 networks (TKIP and CCMP) for old clients, and modern ciphers
such as GCMP-256. Today `wpa1` is TKIP only and WPA2/WPA3 use CCMP.

## Implementation Tasks

- [ ] Encryption `wpa1-wpa2`: `wpa=3`, `wpa_pairwise=TKIP`, `rsn_pairwise=CCMP` (802.11n off when TKIP is the group cipher)
- [ ] Optional `wifi.security.cipher`: `ccmp` (default), `gcmp`, `gcmp-256`, if the MT7921U supports them
- [ ] Read cipher support from `iw phy` (`Supported Ciphers`) and list it in `/capabilities`

## Testing

- [ ] Unit tests and validation
- [ ] Real radio: a WPA1-only client and a WPA2 client on the same mixed network

## Benefits

- **Coverage:** Old clients on mixed networks; modern ciphers

## Breaking Changes

- None (new options)

## Success Criteria

- ✅ Mixed mode serves WPA1 and WPA2 clients
- ✅ Only supported ciphers are offered
