# Feature: Client Details and Statistics

**Priority:** 2 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Show for every client of a network how it is connected and how it is doing:
negotiated generation (HT/VHT/HE), PHY rate in both directions, signal, retries,
traffic, connected time, hostname and vendor. Today the client list has MAC, IP
and the captive portal state.

## Context

On 2026-11-27 finding out why a phone connected as Wi-Fi 5 instead of Wi-Fi 6 took
`hostapd_cli all_sta`, `iw station dump` and a manual beacon scan. All of it is the
data this feature puts in the API.

## Part 1: Data

### Implementation Tasks
- [ ] Per station from `hostapd_cli all_sta` (flags `[HT][VHT][HE]`, capabilities) and `iw dev <if> station dump` (signal, rates, retries, bytes, connected time)
- [ ] Hostname from the DHCP leases; vendor from the MAC prefix (OUI), with a note for randomized MACs
- [ ] Derived: generation, signal quality (excellent/good/fair/poor), throughput from byte deltas
- [ ] One sampling loop per network (e.g. every 5 s), reused by every reader, no command per request

## Part 2: API

### Implementation Tasks
- [ ] Extend `clients` of `GET /access-point/{reservation_id}` with the cheap fields
- [ ] Decide whether detailed counters go to `GET /access-point/{reservation_id}/clients/{mac}`
- [ ] Fields missing for a driver are null, never invented (e.g. the MT7921U TX power is not a measurement)

## Part 3: Frontend

### Implementation Tasks
- [ ] Client table with generation, rates, signal badge, traffic and connected time
- [ ] Details on expansion for the rest

## Testing

- [ ] Parser tests with real `hostapd_cli` and `iw` output captured on the MT7921U
- [ ] API schema tests
- [ ] Real radio: a phone shows `[HE]` or `[VHT]` as hostapd sees it

## Benefits

- **Diagnosis:** Answer "is it on Wi-Fi 6?" or "why is it slow?" without root on the host
- **Testing:** Signal and rate data for every test report

## Breaking Changes

- None (additive fields)

## Success Criteria

- ✅ Generation, rates, signal and traffic visible per client
- ✅ No host command runs per API request
