# Feature: Client Isolation and Client Limit

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Two settings of one network: whether its clients can reach each other, and how
many clients it accepts. Wi-Lab isolates test networks from each other and from
the host, but clients of the same network always see each other.

## Implementation Tasks

- [ ] Optional create field `wifi.client_isolation` (default false): hostapd `ap_isolate=1`
- [ ] Optional create field `wifi.max_clients` (default: no limit): hostapd `max_num_sta`
- [ ] Both shown in `GET /access-point/{reservation_id}`
- [ ] Same-body check: different values are different settings (409 / 1008)

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "client_isolation": true,
    "max_clients": 5
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
    "ssid": "lab-net",
    "hidden": false,
    "client_isolation": true,
    "max_clients": 5,
    "security": {
      "encryption": "wpa2",
      "password": "testpass123"
    }
  }
}
```

## Testing

- [ ] Unit tests for the hostapd lines
- [ ] Real radio: two phones cannot ping each other with isolation; a client beyond the limit is refused

## Benefits

- **Testing:** Devices that must see each other (casting, printers) or must not; a full network

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Isolation on and off verified with two clients
- ✅ The client limit refuses the next client
