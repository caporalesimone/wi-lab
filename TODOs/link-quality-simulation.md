# Feature: Link Quality Simulation - Packet Loss & Latency

**Priority:** 2 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~2.5 hours  

## Description

Add ability to simulate poor network conditions (packet loss, high latency) on individual networks through admin tools. Useful for testing client behavior under adverse network conditions.

### Use Cases

1. **QA Testing:** Verify application behavior with high latency or packet loss
2. **Network Simulation:** Simulate poor WiFi conditions without actual degradation
3. **Edge Case Testing:** Test graceful degradation in client applications
4. **Performance Testing:** Benchmark client performance under stress

## Implementation Tasks

### Backend Implementation

- [ ] Create new admin endpoint: `POST /api/v1/admin/interface/{net_id}/simulate-quality`
- [ ] Parameters:
  - `packet_loss_percent` (0-100, default 0)
  - `latency_ms` (0-5000, default 0)
  - `latency_variance_ms` (0-1000, optional jitter)
  - `bandwidth_mbps` (1-1000, optional throttling)
- [ ] Use Linux `tc` (traffic control) with netem qdisc
- [ ] Store simulation state per network in memory
- [ ] Add simulation status to `GET /interface/{net_id}/status` response
- [ ] Implement `POST /api/v1/admin/interface/{net_id}/clear-simulation` to reset

### Linux tc Implementation

- [ ] Script to apply netem rules: `tc qdisc add dev {iface} root netem loss {x}% latency {y}ms`
- [ ] Script to clear rules: `tc qdisc del dev {iface} root`
- [ ] Error handling for insufficient privileges
- [ ] Validation of parameters (ranges, types)
- [ ] Logging of all simulation changes

### API Documentation

- [ ] Swagger documentation with examples
- [ ] Explain tc/netem limitations and accuracy
- [ ] Include usage examples for QA/testing workflows

### Testing

- [ ] Unit tests for parameter validation
- [ ] Integration tests for tc command execution
- [ ] Mock tc command for safety in test environment
- [ ] Test state persistence across multiple simulations
- [ ] Test clearing simulations

### Frontend (Optional)

- [ ] Admin UI to configure link quality per network
- [ ] Real-time display of active simulations
- [ ] Quick presets: "Good", "Moderate", "Poor", "Terrible"

## Benefits

- **QA Automation:** Test client behavior without manual setup
- **Reproducible Testing:** Consistent network conditions
- **Safe Simulation:** No actual network degradation required
- **Development:** Developers can test locally with realistic conditions

## Breaking Changes

- None (new admin feature)

## Success Criteria

- ✅ Can configure packet loss per network
- ✅ Can configure latency with jitter per network
- ✅ Can enable bandwidth throttling per network
- ✅ Simulation status visible in API responses
- ✅ All existing networks unaffected by feature
- ✅ Comprehensive test coverage
- ✅ Clear error messages on misconfiguration
