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
