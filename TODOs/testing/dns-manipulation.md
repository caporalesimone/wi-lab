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

## Testing

- [ ] Unit tests for the dnsmasq configuration
- [ ] Real radio: an overridden name resolves to the given address

## Benefits

- **Testing:** Application behaviour with other servers and DNS errors

## Breaking Changes

- None (optional section)

## Success Criteria

- ✅ Overrides and NXDOMAIN answers work per network
