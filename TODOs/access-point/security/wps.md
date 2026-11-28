# Feature: WPS Onboarding

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Wi-Fi Protected Setup (push button and PIN), still used by printers and IoT
devices to join a network without typing the password.

## Implementation Tasks

- [ ] Optional `wifi.wps` (default false): hostapd `wps_state=2`, `eap_server=1`
- [ ] Endpoints to press the virtual button (`wps_pbc`) and to enter a PIN (`wps_pin`), only on WPA2 networks
- [ ] WPS events in the client events

## Testing

- [ ] Unit tests with a mocked control socket
- [ ] Real radio: a device joins with the push button

## Benefits

- **Coverage:** Printer and IoT onboarding

## Breaking Changes

- None (optional field)

## Success Criteria

- ✅ A device joins with WPS push button and with a PIN
