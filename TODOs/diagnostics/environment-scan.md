# Feature: Environment Scan

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Scan the air with a free antenna: nearby networks, their channels, widths and
signal, and how busy each channel is. Helps to pick a clean channel and to
explain low throughput.

## Implementation Tasks

- [ ] `GET /api/v2/environment` runs a scan on a free antenna (2.4 and 5 GHz), or answers 503 if none is free
- [ ] Per network: SSID, BSSID, channel, width, signal, generation
- [ ] Per channel: number of networks and the strongest signal; suggested channel
- [ ] Restore the antenna afterwards; cache the result for a minute

## Testing

- [ ] Parser tests with captured `iw scan` output

## Benefits

- **Test quality:** Clean channels and explainable results

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Nearby networks and channel use are listed
- ✅ A channel is suggested per band
