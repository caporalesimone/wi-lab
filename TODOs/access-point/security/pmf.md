# Feature: Protected Management Frames Choice

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Choose Protected Management Frames (PMF, 802.11w) on WPA2 networks: off,
optional or required. Today WPA2 has none, WPA3 requires it and WPA2/WPA3
makes it optional.

## Implementation Tasks

- [ ] Optional `wifi.security.pmf`: `off`, `optional`, `required`; hostapd `ieee80211w=0/1/2`
- [ ] Validation: WPA3 always `required`; open and WPA1 always `off`
- [ ] Shown in `GET /access-point/{reservation_id}`

## Testing

- [ ] Unit tests for the hostapd lines and the validation
- [ ] Real radio: a client without PMF is refused with `required`

## Benefits

- **Testing:** Clients without PMF support, or that refuse it

## Breaking Changes

- None (optional field, default unchanged)

## Success Criteria

- ✅ The three PMF modes work on WPA2
- ✅ Invalid combinations answer 422
