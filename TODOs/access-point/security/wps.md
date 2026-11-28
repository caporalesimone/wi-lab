# Feature: WPS Onboarding

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Wi-Fi Protected Setup (push button and PIN), still used by printers and IoT
devices to join a network without typing the password.

## Implementation Tasks

- [ ] Optional `wifi.wps` (default false): hostapd `wps_state=2`, `eap_server=1`
- [ ] `POST /access-point/{reservation_id}/wps/push-button` (`wps_pbc`) and `POST .../wps/pin` (`wps_pin`), only on WPA2 networks with WPS on
- [ ] WPS events in the client events

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "wps": true
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
  "wifi": {
    "wps": true
  }
}
```

### `POST /api/v2/access-point/{reservation_id}/wps/push-button`

Press the virtual WPS button: a device can join within 2 minutes.

Request: no body.

Response `200`:

```json
{
  "active_until": "2026-11-28T10:02:00Z"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `409 / 1016 wps_off` (new code) when the network has no WPS.

### `POST /api/v2/access-point/{reservation_id}/wps/pin`

Accept a device's WPS PIN.

Request:

```json
{
  "pin": "12345670"
}
```

Response `200`:

```json
{
  "active_until": "2026-11-28T10:02:00Z"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `422 validation_error` with the field path (invalid PIN checksum).

## Testing

- [ ] Unit tests with a mocked control socket
- [ ] Real radio: a device joins with the push button

## Benefits

- **Coverage:** Printer and IoT onboarding

## Breaking Changes

- None (optional field)

## Success Criteria

- ✅ A device joins with WPS push button and with a PIN
