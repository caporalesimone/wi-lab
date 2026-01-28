# Feature: Graceful SIGTERM Shutdown & Config Validation

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Improve shutdown behavior for systemd and container environments. Handle SIGTERM/SIGINT gracefully with proper cleanup, and validate DHCP subnet configuration on startup.

## Part 1: Graceful SIGTERM Shutdown

### Implementation Tasks

- [ ] Implement signal handlers for SIGTERM and SIGINT
- [ ] On signal reception:
  - Log shutdown initiation
  - Stop accepting new API requests
  - Wait for in-flight requests to complete (max 5 seconds)
  - Stop all active networks gracefully
  - Flush all NAT rules
  - Stop DHCP servers cleanly
  - Cleanup network namespaces
- [ ] Total shutdown window: max 10 seconds before force kill
- [ ] Use `signal.signal()` or `asyncio` signal handling
- [ ] Log shutdown sequence with timestamps

### Systemd Integration

- [ ] Ensure TimeoutStopSec in systemd service ≥ 15 seconds
- [ ] Verify graceful shutdown works with `systemctl stop wilab`
- [ ] Test with `systemctl restart wilab`

### Container Support

- [ ] Test with Docker `docker stop` (sends SIGTERM)
- [ ] Ensure cleanup completes within stop timeout
- [ ] Log helpful messages before shutdown

### Testing

- [ ] Unit tests for signal handling
- [ ] Integration tests: send SIGTERM and verify cleanup
- [ ] Verify all resources cleaned (ps, iptables, ip netns)
- [ ] Test timeout scenario (no graceful cleanup)
- [ ] Verify subsequent start works cleanly

## Part 2: DHCP Subnet Collision Detection

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

- **Graceful Degradation:** Clean shutdown of all components
- **Data Integrity:** Flush rules and cleanup resources properly
- **Container Ready:** Works well with Docker/Kubernetes signals
- **Prevention:** Catch subnet conflicts before service starts
- **Visibility:** Know why service failed to start

## Breaking Changes

- None (new behavior, backward compatible)

## Success Criteria

- ✅ SIGTERM received and handled gracefully
- ✅ All resources cleaned on shutdown
- ✅ Shutdown completes within 10-second timeout
- ✅ DHCP subnet collisions detected
- ✅ Startup blocked if collision detected (with strict flag)
- ✅ Override mechanism for testing scenarios
- ✅ Health check reports subnet validation status
