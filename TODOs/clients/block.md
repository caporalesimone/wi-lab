# Feature: Block and Allow Clients by MAC

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Refuse specific clients on a network, or accept only a list of them. Useful to
test a refused client, controlled onboarding, or to keep a device out of a test.

## Implementation Tasks

- [ ] Optional create field `wifi.mac_filter`: `{mode: allow|deny, macs: [...]}` (hostapd `macaddr_acl`, `accept_mac_file`, `deny_mac_file`)
- [ ] Runtime block and unblock of a connected client: `POST /access-point/{reservation_id}/clients/{mac}/block` and `DELETE` on the same path (hostapd `deny_acl ADD_MAC` and `deauthenticate`)
- [ ] Validate MAC addresses; operations idempotent
- [ ] Block state in the client list; blocked MACs listed in `GET /access-point`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "mac_filter": {
      "mode": "deny",
      "macs": [
        "aa:bb:cc:dd:ee:ff"
      ]
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
  "wifi": {
    "mac_filter": {
      "mode": "deny",
      "macs": [
        "aa:bb:cc:dd:ee:ff"
      ]
    }
  }
}
```

### `POST /api/v2/access-point/{reservation_id}/clients/{mac}/block`

Disconnect a client and refuse it until unblocked.

Request:

```json
{
  "reason": "out of test"
}
```

Response `200`:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "blocked": true,
  "since": "2026-11-28T10:00:00Z"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `422 validation_error` with the field path (invalid MAC).

Idempotent: blocking a blocked MAC answers `200` with the same body.

### `DELETE /api/v2/access-point/{reservation_id}/clients/{mac}/block`

Unblock a client.

Request: no body.

Response `200`:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "blocked": false
}
```

## Testing

- [ ] Unit tests for MAC validation and the hostapd commands
- [ ] Real radio: a blocked phone is disconnected and cannot reconnect; unblocked it can

## Benefits

- **Testing:** Refused clients and controlled onboarding
- **Control:** Keep a misbehaving device out of a test

## Breaking Changes

- None (new optional field and endpoints)

## Success Criteria

- ✅ A client can be blocked and unblocked at runtime
- ✅ Allow and deny lists work at creation
