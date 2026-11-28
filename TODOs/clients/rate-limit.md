# Feature: Per-Client Rate Limit

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Limit the bandwidth of one client of a network, in download, upload or both.
The QoS profiles shape the whole network; this targets a single device.

## Implementation Tasks

- [ ] `PUT /access-point/{reservation_id}/clients/{mac}/rate-limit` with `download_kbit`, `upload_kbit`; `DELETE` on the same path to clear
- [ ] `tc` HTB class per client (filter on the client's IP or MAC) on the AP interface, and on the IFB device for upload
- [ ] Must coexist with an active QoS profile (same qdisc tree)
- [ ] Limit shown in the client list

## API Proposal

### `PUT /api/v2/access-point/{reservation_id}/clients/{mac}/rate-limit`

Set the rate limit of one client.

Request:

```json
{
  "download_kbit": 2000,
  "upload_kbit": 500
}
```

Response `200`:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "download_kbit": 2000,
  "upload_kbit": 500
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `422 validation_error` with the field path (`download_kbit: 64 to 1000000`); `404 not_found` for a MAC not connected.

### `DELETE /api/v2/access-point/{reservation_id}/clients/{mac}/rate-limit`

Remove the limit.

Request: no body.

Response `200`:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "download_kbit": null,
  "upload_kbit": null
}
```

The limit also appears as `rate_limit` in each client of `GET /api/v2/access-point/{reservation_id}`.

## Testing

- [ ] Unit tests for the `tc` commands and the validation
- [ ] Real radio: two phones, one limited, measured with a throughput test

## Benefits

- **Testing:** One slow client next to normal ones

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A client is limited and the others are not
- ✅ Works together with a QoS profile
