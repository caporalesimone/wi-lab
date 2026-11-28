# Feature: Wi-Fi 6E, 160 MHz and Wi-Fi 7 Adapters

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** hardware purchase + ~2 days  

## Description

Support adapters with 6 GHz, 160 MHz channels or Wi-Fi 7, for recent clients.
The MT7921U is a 2.4/5 GHz Wi-Fi 6 adapter: none of this is possible with it.

## Implementation Tasks

- [ ] Choose adapters with good AP-mode support on Linux (e.g. MediaTek MT7922 / MT7925 families; check AP mode on 6 GHz in `iw phy`)
- [ ] Channels: stop dropping 6 GHz in discovery; regulatory rules for 6 GHz (PSC channels, low-power indoor)
- [ ] Band `6ghz`, width 160, generation 7 in the create; WPA3 with H2E required on 6 GHz
- [ ] Capabilities endpoint lists them per adapter

## Testing

- [ ] Parser tests with captured `iw phy` output of the new adapters
- [ ] Real radio with a Wi-Fi 6E client

## Benefits

- **Coverage:** Recent phones and laptops on 6 GHz and wide channels

## Breaking Changes

- None (new values)

## Success Criteria

- ✅ A 6 GHz network works with a Wi-Fi 6E client
