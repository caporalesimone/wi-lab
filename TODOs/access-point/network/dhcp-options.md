# Feature: DHCP Options per Network

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~3 hours  

## Description

Let a create choose the DHCP settings of its network: lease time, address range,
fixed addresses and the DNS server handed to clients. Today they are fixed (the
DNS server is the global `dns_server` of `config.yaml`).

## Implementation Tasks

- [ ] Optional create section `ip.dhcp`: `lease_seconds` (default today's), `range` (start, end inside the /24)
- [ ] `dns_server` per network, overriding the global one
- [ ] Fixed addresses: a list of `{mac, ip}` (`dhcp-host=`)
- [ ] Validation: range inside the subnet, not the gateway, fixed addresses inside the subnet and unique
- [ ] `GET /access-point/{reservation_id}`: the values in use in `ip`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "ip": {
    "dhcp": {
      "lease_seconds": 120,
      "range": {
        "start": "192.168.120.50",
        "end": "192.168.120.99"
      },
      "dns_server": "1.1.1.1",
      "fixed": [
        {
          "mac": "aa:bb:cc:dd:ee:ff",
          "ip": "192.168.120.10"
        }
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

Errors: `422 validation_error` with the field path (e.g. `ip.dhcp.range.start: outside the subnet`).

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "ip": {
    "subnet": "192.168.120.0/24",
    "gateway": "192.168.120.1",
    "dhcp_range": {
      "start": "192.168.120.50",
      "end": "192.168.120.99"
    },
    "dns_server": "1.1.1.1",
    "lease_seconds": 120,
    "fixed": [
      {
        "mac": "aa:bb:cc:dd:ee:ff",
        "ip": "192.168.120.10"
      }
    ]
  }
}
```

## Testing

- [ ] Unit tests for the generated dnsmasq configuration
- [ ] Validation tests (422 with the field path)
- [ ] Real radio: a short lease is renewed; a fixed address is given to its MAC

## Benefits

- **Testing:** Fast lease renewals, predictable addresses, another DNS for one test
- **Compatibility:** Defaults keep today's behaviour

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Lease time, range, fixed addresses and DNS can be set per network
- ✅ Invalid values answer 422 with the field path
- ✅ The values in use are shown by the API
