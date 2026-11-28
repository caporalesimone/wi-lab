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
- [ ] Detailed counters in `GET /access-point/{reservation_id}/clients/{mac}`
- [ ] Fields missing for a driver are null, never invented (e.g. the MT7921U TX power is not a measurement)

## Part 3: Frontend

### Implementation Tasks
- [ ] Client table with generation, rates, signal badge, traffic and connected time
- [ ] Details on expansion for the rest

## API Proposal

### `GET /api/v2/access-point/{reservation_id}`

The client list grows with the cheap fields (shortened answer).

Request: no body.

Response `200`:

```json
{
  "clients": [
    {
      "mac": "12:ee:e6:97:b8:28",
      "ip": "192.168.120.23",
      "hostname": "redmi-note-14",
      "vendor": null,
      "randomized_mac": true,
      "generation": 5,
      "band": "5ghz",
      "signal_dbm": -52,
      "signal_quality": "good",
      "tx_rate_mbps": 156.0,
      "rx_rate_mbps": 130.0,
      "connected_seconds": 39,
      "captive_authorized": null
    }
  ]
}
```

### `GET /api/v2/access-point/{reservation_id}/clients/{mac}`

Everything known about one client.

Request: no body.

Response `200`:

```json
{
  "mac": "12:ee:e6:97:b8:28",
  "ip": "192.168.120.23",
  "ipv6": [],
  "hostname": "redmi-note-14",
  "generation": 5,
  "flags": [
    "HT",
    "VHT",
    "WMM",
    "MFP"
  ],
  "band": "5ghz",
  "channel_width": 40,
  "signal_dbm": -52,
  "signal_avg_dbm": -50,
  "signal_quality": "good",
  "tx": {
    "rate_mbps": 156.0,
    "mcs": 8,
    "nss": 2,
    "short_gi": true,
    "bytes": 164626,
    "packets": 397,
    "retries": 0,
    "failed": 0,
    "throughput_kbit": 820
  },
  "rx": {
    "rate_mbps": 130.0,
    "mcs": 7,
    "nss": 2,
    "bytes": 155144,
    "packets": 463,
    "throughput_kbit": 410
  },
  "connected_seconds": 39,
  "inactive_ms": 3781,
  "sampled_at": "2026-11-28T10:00:05Z"
}
```

Errors: `404` with `detail.reason` when the reservation is gone; `404 not_found` for a MAC not connected.

Null when the driver does not provide a value; never estimated.

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
