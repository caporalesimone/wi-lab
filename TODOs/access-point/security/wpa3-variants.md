# Feature: WPA3 Variants

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Choose how WPA3 (SAE) derives its password element and which groups it uses.
Today `sae_pwe=2` (both methods) and the default groups.

## Implementation Tasks

- [ ] Optional `wifi.security.sae_pwe`: `hunting_and_pecking` (0), `hash_to_element` (1), `both` (2, default)
- [ ] Optional `wifi.security.sae_groups` (e.g. 19, 20, 21)
- [ ] Only with `wpa3` and `wpa2-wpa3`

## Testing

- [ ] Unit tests and validation
- [ ] Real radio: an old WPA3 client fails with H2E only

## Benefits

- **Testing:** WPA3 compatibility of clients; Wi-Fi 6E requires H2E

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Each SAE variant works or fails as expected with real clients
