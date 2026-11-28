# Feature: Client Event Log

**Priority:** 2 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Record what happens to clients on a network: authentications, associations,
refusals with their reason code, disconnections, DHCP leases. Today the only
trace is hostapd's syslog lines, and refusals are only at debug level.

## Context

On 2026-11-27 a Wi-Fi 6-only network (`enable_generation_fallback: false`) was not
joined by a phone, and hostapd logged nothing at its normal level: the reason had
to be inferred. This feature makes such refusals visible.

## Implementation Tasks

- [ ] Read hostapd events from the control socket (`AP-STA-CONNECTED`, `AP-STA-DISCONNECTED`, `AP-STA-POSSIBLE-PSK-MISMATCH`, EAP events)
- [ ] Refusals at association with their status code (e.g. generation required, PMF required), from hostapd's debug output or a monitor capture
- [ ] DHCP events from dnsmasq (lease, renew, release)
- [ ] `GET /access-point/{reservation_id}/events` (last N per network) and the same events in the stream ([event-stream.md](event-stream.md))

## API Proposal

### `GET /api/v2/access-point/{reservation_id}/events?type=client&limit=50`

The last client events of the network (also in the event stream).

Request: no body.

Response `200`:

```json
{
  "events": [
    {
      "id": 2001,
      "type": "client.authenticated",
      "time": "2026-11-28T10:01:00Z",
      "mac": "aa:bb:cc:dd:ee:ff"
    },
    {
      "id": 2002,
      "type": "client.association_refused",
      "time": "2026-11-28T10:01:00Z",
      "mac": "aa:bb:cc:dd:ee:ff",
      "status_code": 124,
      "reason": "he_required",
      "message": "Station does not support mandatory HE PHY"
    },
    {
      "id": 2003,
      "type": "client.password_mismatch",
      "time": "2026-11-28T10:02:10Z",
      "mac": "11:22:33:44:55:66"
    },
    {
      "id": 2004,
      "type": "client.connected",
      "time": "2026-11-28T10:03:00Z",
      "mac": "11:22:33:44:55:66",
      "generation": 5
    },
    {
      "id": 2005,
      "type": "client.dhcp_lease",
      "time": "2026-11-28T10:03:01Z",
      "mac": "11:22:33:44:55:66",
      "ip": "192.168.120.23",
      "hostname": "redmi-note-14"
    },
    {
      "id": 2006,
      "type": "client.disconnected",
      "time": "2026-11-28T10:20:00Z",
      "mac": "11:22:33:44:55:66",
      "reason_code": 3,
      "reason": "deauth_leaving",
      "connected_seconds": 1020
    }
  ],
  "next": 2007
}
```

Errors: `404` with `detail.reason` when the reservation is gone.

## Testing

- [ ] Parser tests with captured hostapd and dnsmasq output
- [ ] Real radio: wrong password, refused generation and a normal connection each produce the right events

## Benefits

- **Diagnosis:** Why a client cannot connect, without reading the journal

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Wrong password, refused association and DHCP lease are visible per network
