# Feature: Faster Lab Host

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** hypervisor work, ~1 day  

## Description

Raise the throughput of the test networks, limited today by the VM and not by
the radio: 70-90 Mbit/s per network with a 400 Mbit/s PHY link and no retries,
while the VM's two virtual CPUs are 70-88% busy.

## Context

Measured 2026-11-27 on a Wi-Fi 5 network at 40 MHz: download 70-90 Mbit/s, upload
60-85 Mbit/s, CPU 55-88%, softirq up to 35%, 0 retries, PHY link 400 Mbit/s
(VHT-MCS 9, 2 streams, short GI). The host itself downloads at about 630 Mbit/s.
The VM is QEMU with "QEMU Virtual CPU version 2.5+" and USB passthrough of the
two adapters.

## Implementation Tasks

- [ ] Pass a whole USB 3 controller to the VM (PCI passthrough) instead of single USB devices: no USB emulation
- [ ] CPU model `host` and at least 4 virtual CPUs
- [ ] Adapters on USB 3 ports (they run at USB 2.0, 480 Mbit/s, today)
- [ ] Alternatively, Wi-Lab on a physical machine for performance measurements
- [ ] Until then, document the limit for testers: about 80 Mbit/s per network on this installation

## Testing

- [ ] Repeat the 2026-11-27 measurement (speed test plus per-second interface and CPU sampling) after each change

## Benefits

- **Measurement:** Client throughput tests limited by Wi-Fi, not by the host

## Breaking Changes

- None

## Success Criteria

- ✅ Throughput per network well above 80 Mbit/s with CPU headroom
