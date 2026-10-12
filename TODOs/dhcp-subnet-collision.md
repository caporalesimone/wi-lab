# Feature: DHCP Subnet Collision Detection

**Priority:** 5  
**Status:** PARTIALLY IMPLEMENTED (see below)  
**Estimated Effort:** part of the original ~1.5 hours (this document was Part 2 of [graceful-shutdown.md](graceful-shutdown.md))  

## Description

Validate the DHCP subnet configuration on startup, so that a `dhcp_base_network` colliding with the host's own networks is caught before the service touches the network.

## Status: what already exists

Part of this proposal is covered by the configuration validator
(`wilab/config_validation.py`, rule `check_dhcp_network_collision`, see
[docs/networking.md](../docs/networking.md#automatic-detection)):

- On every start, and with `python3 main.py --validate-config --check-hardware`, every WiFi subnet Wi-Lab
  would allocate (one `/24` per device, sequential from `dhcp_base_network`) is compared with the host's
  routing table (`ip route`).
- A collision is an **error that blocks startup**, with a readable report naming the conflicting route.
- The check is skipped by a plain `--validate-config` (it needs the real machine) and stays silent when
  `ip route` cannot be read.

Not covered yet (still proposed below): a `--strict-subnet-check` flag with a non-blocking mode,
the `WILAB_IGNORE_SUBNET_CHECK` override, IPv6, and reporting the collision status in the health endpoint.
Review which of these are still wanted before implementing.

## Remaining proposal

### Implementation Tasks

- [ ] On startup, validate configuration parameters
- [ ] Read configured `dhcp_base_network` from config.yaml
- [ ] Scan existing system interfaces with `ip addr`
- [ ] Detect collision with host network or other interfaces
- [ ] Add startup flag `--strict-subnet-check` to block on collision
- [ ] Log detected collision with affected interfaces
- [ ] Add collision status to health check

### Validation Logic

- [ ] Parse CIDR notation: `192.168.1.0/24`
- [ ] Extract network address and netmask
- [ ] Compare against each interface's IP and netmask
- [ ] Handle IPv4 and IPv6 addresses
- [ ] Report specific conflicting interface(s)

### Configuration Override

- [ ] Allow override with env var: `WILAB_IGNORE_SUBNET_CHECK=1`
- [ ] Document override use case (testing only)
- [ ] Always log override in startup messages

### Error Handling

- [ ] On collision with strict checking:
  - Log detailed error with conflicting interfaces
  - Return non-zero exit code
  - Block service startup
- [ ] Without strict checking:
  - Log warning
  - Continue startup
  - Note risk in health endpoint

### Testing

- [ ] Unit tests for subnet collision detection
- [ ] Test with overlapping subnets
- [ ] Test with non-overlapping subnets
- [ ] Test IPv4 and IPv6 separately
- [ ] Test override flag behavior

## Benefits

- **Prevention:** Catch subnet conflicts before service starts
- **Visibility:** Know why service failed to start

## Breaking Changes

- None (new behavior, backward compatible)

## Success Criteria

- ✅ DHCP subnet collisions detected
- ✅ Startup blocked if collision detected (with strict flag)
- ✅ Override mechanism for testing scenarios
- ✅ Health check reports subnet validation status
