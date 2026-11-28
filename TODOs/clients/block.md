# Feature: Block and Allow Clients by MAC

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Refuse specific clients on a network, or accept only a list of them. Useful to
test a refused client, controlled onboarding, or to keep a device out of a test.

## Implementation Tasks

- [ ] Optional create field `wifi.mac_filter`: `{mode: allow|deny, macs: [...]}` (hostapd `macaddr_acl`, `accept_mac_file`, `deny_mac_file`)
- [ ] Runtime block and unblock of a connected client: `POST /access-point/{reservation_id}/clients/{mac}/block` and `.../unblock` (hostapd `deny_acl ADD_MAC` and `deauthenticate`)
- [ ] Validate MAC addresses; operations idempotent
- [ ] Block state in the client list; blocked MACs listed in `GET /access-point`

## Testing

- [ ] Unit tests for MAC validation and the hostapd commands
- [ ] Real radio: a blocked phone is disconnected and cannot reconnect; unblocked it can

## Benefits

- **Testing:** Refused clients and controlled onboarding
- **Control:** Keep a misbehaving device out of a test

## Breaking Changes

- None (new optional field and endpoints)

## Success Criteria

- ✅ A client can be blocked and unblocked at runtime
- ✅ Allow and deny lists work at creation
