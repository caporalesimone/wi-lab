# Feature: Fast Roaming Between Two Antennas (802.11r/k/v)

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

Two access points with the same SSID on the two antennas, with fast transition
(802.11r), neighbour reports (802.11k) and BSS transition management (802.11v),
to measure how clients roam and how long the handover takes.

## Part 1: Two Antennas in One Reservation

- [ ] A reservation that holds both antennas, or two linked reservations (the API has neither today)
- [ ] One subnet and one DHCP server shared by the two APs (a bridge, or one AP as the gateway)

## Part 2: Roaming Features

- [ ] hostapd `ieee80211r=1`, `mobility_domain`, `ft_over_ds`, R0/R1 key holders between the two BSSes
- [ ] `rrm_neighbor_report=1`, `bss_transition=1`; neighbour list filled with the other AP
- [ ] Endpoint to ask a client to move (`bss_tm_req`)
- [ ] Handover events and timings in the client events

## Testing

- [ ] Unit tests for the configuration of the pair
- [ ] Real radio: a phone moves between the two APs (needs signal control: [attenuation.md](../../testing/attenuation.md))

## Benefits

- **Testing:** Roaming decisions and handover times of clients

## Breaking Changes

- None (new optional mode)

## Success Criteria

- ✅ A client roams between the two antennas with 802.11r
- ✅ Handover times are reported
