# Feature: IPv6 on the Test Networks

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Give the clients of a test network IPv6 as well as IPv4 (dual stack), or IPv6 only.
Today every test network is IPv4 only, so clients and applications are never
tested on IPv6.

## Implementation Tasks

### Addressing
- [ ] New optional create section `ip.ipv6`: `off` (default, today's behaviour), `dual`, `only`
- [ ] Router advertisements and SLAAC with dnsmasq (`enable-ra`, `dhcp-range=::,constructor:<if>,ra-stateless`)
- [ ] Optional stateful DHCPv6 (`dhcp-range` with an IPv6 range)
- [ ] Decide the prefix: a routed prefix delegated by the lab network, or a ULA prefix with NAT66 on the uplink
- [ ] One /64 per antenna, like the IPv4 /24 of `dhcp_base_network`

### Firewall
- [ ] Mirror the IPv4 rules in `ip6tables`: host guard, isolation between test networks, captive portal, Internet block
- [ ] IPv6 forwarding (`net.ipv6.conf.all.forwarding`) only while an IPv6 network runs
- [ ] Startup cleanup of stale `ip6tables` rules, like `NatManager.remove_stale_rules`

### API
- [ ] `GET /access-point/{reservation_id}`: `ip.ipv6` with prefix, gateway and mode
- [ ] Client list: IPv6 addresses of each client (from the neighbour table)

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "ip": {
    "ipv6": {
      "mode": "dual",
      "dhcpv6": false
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
  "ip": {
    "subnet": "192.168.120.0/24",
    "gateway": "192.168.120.1",
    "ipv6": {
      "mode": "dual",
      "prefix": "fd57:1a8b:120::/64",
      "gateway": "fd57:1a8b:120::1",
      "dhcpv6": false
    }
  },
  "clients": [
    {
      "mac": "aa:bb:cc:dd:ee:ff",
      "ip": "192.168.120.23",
      "ipv6": [
        "fd57:1a8b:120::a8bb:ccff:fedd:eeff"
      ]
    }
  ]
}
```

`mode`: `off` (default), `dual`, `only`. With `only` clients get no IPv4 lease; `ip.subnet` stays for the gateway's own IPv4 address.

## Testing

- [ ] Unit tests for the dnsmasq configuration per mode
- [ ] Unit tests for the `ip6tables` rules and their cleanup
- [ ] Real radio: a phone gets an IPv6 address and reaches an IPv6 site; two test networks cannot reach each other over IPv6

## Benefits

- **Coverage:** IPv6-only and dual-stack behaviour of clients and applications
- **Realism:** Many operator and company networks are dual stack

## Breaking Changes

- None (off by default)

## Success Criteria

- ✅ Dual-stack and IPv6-only networks work with a real phone
- ✅ Isolation and host guard hold over IPv6
- ✅ No IPv6 rule is left after a stop or a crash
