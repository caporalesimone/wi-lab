# Feature: WMM and U-APSD Settings

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Turn WMM (Wi-Fi QoS) and U-APSD (power save for voice) on or off per network.
Today WMM is always on and U-APSD is hostapd's default.

## Implementation Tasks

- [ ] Optional `radio.wmm` (default true): hostapd `wmm_enabled`; refuse `false` with 802.11n or newer (WMM is mandatory there)
- [ ] Optional `radio.uapsd` (default false): `uapsd_advertisement_enabled`
- [ ] Shown in `GET /access-point/{reservation_id}`

## Testing

- [ ] Unit tests and validation
- [ ] Real radio: the WMM element in the beacon follows the setting

## Benefits

- **Testing:** VoIP and power save; clients without WMM on legacy networks

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ WMM and U-APSD follow the request in the beacon
