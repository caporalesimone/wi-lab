# Feature: DNS Manipulation per Network

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Control DNS answers on a network: override names, answer NXDOMAIN, delay or drop
answers. For application tests (another server, resolution errors).

## Implementation Tasks

- [ ] Create section `dns`: overrides (`name → address`), blocked names (NXDOMAIN)
- [ ] dnsmasq `address=` per network; delays through a small proxy or `tc` on port 53
- [ ] Changes at runtime through [fault-injection.md](fault-injection.md)

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "dns": {
    "overrides": [
      {
        "name": "api.example.com",
        "address": "192.168.120.1"
      }
    ],
    "nxdomain": [
      "ads.example.com"
    ],
    "delay_ms": 0
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
  "dns": {
    "overrides": [
      {
        "name": "api.example.com",
        "address": "192.168.120.1"
      }
    ],
    "nxdomain": [
      "ads.example.com"
    ],
    "delay_ms": 0
  }
}
```

At runtime the same section can be changed with a fault (`type: dns_failure`) or a PATCH ([patch-access-point.md](../api/patch-access-point.md)).

## Testing

- [ ] Unit tests for the dnsmasq configuration
- [ ] Real radio: an overridden name resolves to the given address

## Benefits

- **Testing:** Application behaviour with other servers and DNS errors

## Breaking Changes

- None (optional section)

## Success Criteria

- ✅ Overrides and NXDOMAIN answers work per network
