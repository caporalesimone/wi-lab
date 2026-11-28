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
