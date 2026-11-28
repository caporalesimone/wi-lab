# Feature: Fault Injection

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Inject faults into a running network to see how clients recover: disconnect a
client, change the password, make DHCP stop answering or give a wrong gateway,
make DNS fail, restart the AP. Internet on/off and QoS profiles already exist.

## Context

Runtime commands on a running AP (power change, channel switch, reload) have hung the lab VM twice (2026-11-23 and 2026-11-28) and detached the MT7921U from the VM. Try this on a test network first, with the lab owner's consent.

## Implementation Tasks

- [ ] `POST /access-point/{reservation_id}/faults` with a type and parameters, `DELETE` to clear
- [ ] Client disconnect (hostapd `deauthenticate`), password change (hostapd reload), AP restart
- [ ] DHCP: no answer, wrong gateway, wrong DNS (dnsmasq restart with another configuration)
- [ ] DNS failures (see [dns-manipulation.md](dns-manipulation.md))
- [ ] Active faults shown in `GET /access-point`; the watchdog must not repair an injected fault

## Testing

- [ ] Unit tests per fault type, including the watchdog exemption
- [ ] Real radio, test network only: each fault and its clearing

## Benefits

- **Testing:** Client recovery behaviour, repeatable

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Each fault can be injected and cleared
- ✅ The watchdog leaves injected faults alone
