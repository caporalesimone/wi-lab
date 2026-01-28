# Feature: Per-Client Controls - Blocking & Rate Limiting

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Fine-grained control over individual client devices. Block/unblock specific MAC addresses and apply bandwidth limits per client.

## Part 1: Per-MAC Address Client Blocking

### Implementation Tasks

- [ ] Create `POST /interface/{net_id}/client/{mac}/block` endpoint
- [ ] Create `POST /interface/{net_id}/client/{mac}/unblock` endpoint
- [ ] Validate MAC address format
- [ ] Check if client is currently connected (return 404 if not)
- [ ] Store blocked clients per network in memory
- [ ] Backend Implementation:
  - Use iptables rule: `iptables -A FORWARD -m mac --mac-source {mac} -j DROP`
  - Add rule with `comment "wilab-blocked-{net_id}"`
  - Remove rule on unblock
- [ ] Persist blocked clients across API restarts (optional)

### Block Status Tracking

- [ ] Include block status in client info response
- [ ] Add endpoints:
  - `GET /interface/{net_id}/clients/blocked` - List blocked MACs
  - `GET /interface/{net_id}/client/{mac}/block-status` - Check if blocked
- [ ] Return reason and timestamp of block

### Testing

- [ ] Unit tests for MAC address validation
- [ ] Integration tests for block/unblock
- [ ] Verify iptables rules created/removed
- [ ] Test blocking non-connected client (should fail)
- [ ] Test blocking already blocked client (idempotent)
- [ ] Verify unblocked clients can reconnect

## Part 2: Per-MAC Basic Rate Limiting

### Implementation Tasks

- [ ] Create `POST /interface/{net_id}/client/{mac}/rate-limit` endpoint
- [ ] Parameters:
  - `rate_mbps` (1-100 Mbps range)
  - `direction` (upload, download, both) - optional, default both
- [ ] Backend Implementation:
  - Use `tc` (traffic control) HTB qdisc
  - Create class per MAC with rate limit
  - Rules applied at egress (outgoing) and ingress (incoming)
  - Add identifying marks/comments for tracking
- [ ] Create `POST /interface/{net_id}/client/{mac}/clear-rate-limit` endpoint
- [ ] Validate rate parameters before application

### Rate Limit Status

- [ ] Include rate limit in client info response
- [ ] Add endpoint: `GET /interface/{net_id}/client/{mac}/rate-limit-status`
- [ ] Return current rate limit and direction

### Error Handling

- [ ] Return 422 if rate_mbps out of range
- [ ] Return 422 if client not connected
- [ ] Return 500 if tc command fails with helpful message
- [ ] Log all rate limit applications

### Testing

- [ ] Unit tests for parameter validation
- [ ] Integration tests for tc command application
- [ ] Test rate limit removal
- [ ] Verify traffic actually limited (if possible)
- [ ] Test multiple clients with different limits
- [ ] Test idempotent operations

## Benefits

- **Network Administration:** Control misbehaving clients
- **QoS:** Enforce fair bandwidth allocation
- **Security:** Isolate compromised devices
- **Testing:** Simulate client behavior under restrictions

## Breaking Changes

- None (new admin feature)

## Success Criteria

- ✅ Can block individual clients by MAC
- ✅ Can unblock previously blocked clients
- ✅ Can apply bandwidth limits (1-100 Mbps)
- ✅ Block/rate-limit status visible in API
- ✅ Operations fail gracefully with helpful errors
- ✅ All client controls well-tested and logged
- ✅ >90% test coverage
