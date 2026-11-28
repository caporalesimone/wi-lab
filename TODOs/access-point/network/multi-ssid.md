# Feature: Several SSIDs on One Antenna

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Run more than one network on one antenna (multi-BSS), for example a guest and a
main network with different security, sharing the channel.

## Implementation Tasks

- [ ] Check that the MT7921U supports several AP interfaces (`iw phy` interface combinations) and how many
- [ ] hostapd: extra `bss=` sections, one per SSID, each with its security and MAC address
- [ ] API: extra networks added to the running access point with `POST /access-point/{reservation_id}/bss`, removed with `DELETE .../bss/{bss_id}`
- [ ] Separate subnet, DHCP and firewall rules per BSS
- [ ] Watchdog: one hostapd process, several BSSes

## API Proposal

### `POST /api/v2/access-point/{reservation_id}/bss`

Add a second network (BSS) to the running access point of the reservation, on the same channel.

Request:

```json
{
  "wifi": {
    "ssid": "lab-guest",
    "security": {
      "encryption": "open"
    }
  },
  "internet": {
    "enabled": true
  }
}
```

Response `201`:

```json
{
  "bss_id": 1,
  "ssid": "lab-guest",
  "subnet": "192.168.121.0/24"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `409 / 1014 bss_limit` (new code) when the antenna supports no more BSSes; `422 validation_error` with the field path.

### `GET /api/v2/access-point/{reservation_id}`

Every BSS of the access point.

Request: no body.

Response `200`:

```json
{
  "active": true,
  "bss": [
    {
      "bss_id": 0,
      "ssid": "lab-main"
    },
    {
      "bss_id": 1,
      "ssid": "lab-guest",
      "subnet": "192.168.121.0/24"
    }
  ]
}
```

### `DELETE /api/v2/access-point/{reservation_id}/bss/{bss_id}`

Stop one extra BSS (`0`, the main one, is stopped with the access point).

Request: no body.

Response `200`:

```json
{
  "detail": "BSS 1 stopped"
}
```

Errors: `404` with `detail.reason` when the reservation is gone; `404 not_found` for an unknown `bss_id`.

## Testing

- [ ] Unit tests for the configuration and the per-BSS rules
- [ ] Real radio: two SSIDs visible and usable at the same time

## Benefits

- **Coverage:** Guest and main networks side by side, as in a home or office router

## Breaking Changes

- None if added as a new optional structure

## Success Criteria

- ✅ Two SSIDs run on one antenna, each with its own security and subnet
- ✅ Not offered on adapters that do not support it
