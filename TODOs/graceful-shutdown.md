# Feature: Graceful SIGTERM Shutdown

**Priority:** 5  
**Status:** PROPOSED  
**Estimated Effort:** part of the original ~1.5 hours (this document and [dhcp-subnet-collision.md](dhcp-subnet-collision.md) were one document)  

## Description

Improve shutdown behavior for systemd and container environments. Handle SIGTERM/SIGINT gracefully with proper cleanup of every resource the service created.

## Shutdown

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

## Benefits

- **Graceful Degradation:** Clean shutdown of all components
- **Data Integrity:** Flush rules and cleanup resources properly
- **Container Ready:** Works well with Docker/Kubernetes signals

## Breaking Changes

- None (new behavior, backward compatible)

## Success Criteria

- ✅ SIGTERM received and handled gracefully
- ✅ All resources cleaned on shutdown
- ✅ Shutdown completes within 10-second timeout
