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
- [ ] `POST /access-point/{reservation_id}/clients/{mac}/steer` asks a client to move (`bss_tm_req`)
- [ ] Handover events and timings in the client events

## API Proposal

### `POST /api/v2/reservations`

Reserve both antennas in one reservation.

Request:

```json
{
  "duration_seconds": 3600,
  "antennas": 2
}
```

Response `200`:

```json
{
  "reservation_id": "a1b2c3d4",
  "interfaces": [
    "wlx7419f8176286",
    "wlx7419f817651c"
  ],
  "expires_at": "2026-11-28T11:00:00Z",
  "expires_in": 3600
}
```

Errors: `409 / 1005 no_device_available` when fewer antennas are free.

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "roaming": {
    "fast_transition": true,
    "neighbor_reports": true,
    "bss_transition": true
  },
  "radios": [
    {
      "interface": "wlx7419f8176286",
      "band": "5ghz",
      "channel": 36
    },
    {
      "interface": "wlx7419f817651c",
      "band": "5ghz",
      "channel": 149
    }
  ],
  "wifi": {
    "ssid": "lab-roam",
    "security": {
      "encryption": "wpa2",
      "password": "testpass123"
    }
  }
}
```

Response `202`:

```json
{
  "runtime_state": "starting",
  "active": false
}
```

Errors: `422` with the field path for an invalid value.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "roaming": {
    "fast_transition": true,
    "neighbor_reports": true,
    "bss_transition": true,
    "mobility_domain": "a1b2"
  },
  "radios": [
    {
      "interface": "wlx7419f8176286",
      "channel": 36,
      "bssid": "74:19:f8:17:62:86"
    },
    {
      "interface": "wlx7419f817651c",
      "channel": 149,
      "bssid": "74:19:f8:17:65:1c"
    }
  ],
  "clients": [
    {
      "mac": "aa:bb:cc:dd:ee:ff",
      "bssid": "74:19:f8:17:62:86"
    }
  ]
}
```

### `POST /api/v2/access-point/{reservation_id}/clients/{mac}/steer`

Ask a client to move to the other access point (BSS transition request).

Request:

```json
{
  "target_bssid": "74:19:f8:17:65:1c"
}
```

Response `200`:

```json
{
  "accepted": true,
  "moved_after_ms": 180
}
```

Errors: `404` with `detail.reason` when the reservation is gone; `404 not_found` for a MAC not connected; `409 / 1017 bss_transition_off` (new code).

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
