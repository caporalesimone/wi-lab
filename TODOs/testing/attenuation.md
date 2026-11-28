# Feature: Controlled Signal Attenuation

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** hardware purchase + ~1 day  

## Description

Change the signal level between an access point and the clients in a
controlled way, to simulate distance and to drive roaming tests.

## Context

TX power cannot be used for this: measured per level on 2026-11-28, the MT7921U in
AP mode always transmits at its calibration (about 18 dBm) whatever level is set,
and changing the power of a running AP hung the VM. The QoS profiles simulate
loss, latency and bandwidth, not signal level.

## Implementation Tasks

- [ ] Choose hardware: programmable RF attenuators between the antenna connectors and a shielded box, or a shielded box per client
- [ ] Driver for the attenuator (USB/serial/Ethernet API)
- [ ] `POST /access-point/{reservation_id}/attenuation` with dB; in scenarios as a step

## Testing

- [ ] Real hardware: signal seen by the client follows the attenuation

## Benefits

- **Testing:** Distance, signal thresholds, roaming

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Attenuation set through the API changes the signal clients see
