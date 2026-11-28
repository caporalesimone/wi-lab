# Feature: One SSID on 2.4 and 5 GHz

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

The same network on 2.4 GHz and 5 GHz at once, one antenna per band, like a
dual-band home router, to test band choice and band steering of clients.

## Implementation Tasks

- [ ] Shares Part 1 of [fast-roaming.md](fast-roaming.md): one reservation for both antennas, one subnet
- [ ] Create body with two `radio` sections (2.4 and 5 GHz), one `wifi` section
- [ ] Optional band steering: refuse 2.4 GHz associations of dual-band clients for a few seconds
- [ ] Client list with the band of each client

## Testing

- [ ] Unit tests for the paired configuration
- [ ] Real radio: a phone chooses 5 GHz; with 5 GHz off it moves to 2.4 GHz

## Benefits

- **Coverage:** Band choice and steering, as with real routers

## Breaking Changes

- None (new optional mode)

## Success Criteria

- ✅ One SSID runs on both bands
- ✅ The band of each client is visible
