# Feature: Real-Time Events & Webhooks

**Priority:** 7  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Real-time event streaming for network activities through Server-Sent Events (SSE). Enables external integrations and UI updates via push notifications instead of polling.

## Part 1: Server-Sent Events (SSE) Streaming

### Implementation Tasks

- [ ] Create `GET /api/v1/interface/{net_id}/events` SSE endpoint
- [ ] Use FastAPI StreamingResponse for SSE
- [ ] Implement event queue per network (max 100 events in memory)
- [ ] Connection management:
  - Handle client connect/disconnect
  - Cleanup resources on disconnect
  - Timeout inactive connections (30+ minutes)

### Event Types

- [ ] `client_connected` - New client joined network
  - Payload: MAC, IP, hostname, connection_time
- [ ] `client_disconnected` - Client left network
  - Payload: MAC, IP, duration_connected
- [ ] `network_expiring` - Network expiration approaching (5 min warning)
  - Payload: net_id, time_remaining
- [ ] `ap_started` - Access point started
  - Payload: net_id, interface, ssid
- [ ] `ap_stopped` - Access point stopped
  - Payload: net_id, interface, reason
- [ ] `ap_error` - Access point encountered error
  - Payload: net_id, error_message

### Event Storage

- [ ] Implement circular buffer (Ring Buffer) for event history
- [ ] Store last 100 events per network
- [ ] Include: timestamp, event_type, data
- [ ] Serialize to JSON for transmission
- [ ] Implement event retrieval endpoint for client backfill

### Swagger Documentation

- [ ] Document SSE format and encoding
- [ ] Provide curl/JavaScript examples
- [ ] Explain reconnection strategy
- [ ] Document event schemas

### Testing

- [ ] Unit tests for event queue
- [ ] Integration tests for SSE endpoint
- [ ] Test event generation on client connect/disconnect
- [ ] Test multiple concurrent SSE clients
- [ ] Test event buffer wraparound
- [ ] Test connection timeout and cleanup

## Part 2: Client Activity Tracking

### Implementation Tasks

- [ ] Monitor hostapd activity logs for client events
- [ ] Parse hostapd output for:
  - `<MAC> authenticated`
  - `<MAC> associated`
  - `<MAC> deauthenticated`
  - `<MAC> disassociated`
- [ ] Track per client:
  - Connection timestamp
  - Last activity timestamp
  - Authentication method
  - Signal strength (if available)
- [ ] Emit SSE events on state changes

### Client State Machine

- [ ] States: disconnected → authenticating → associated → disconnected
- [ ] Emit events on state transitions
- [ ] Filter spurious state changes (quick connect/disconnect)
- [ ] Include state transition reason

### Integration with Client Info

- [ ] Add to `GET /interface/{net_id}/clients` response:
  - Last activity timestamp
  - Connection duration
  - Authentication state
- [ ] Include in individual client info endpoint

### Testing

- [ ] Unit tests for hostapd log parsing
- [ ] Mock hostapd output scenarios
- [ ] Test state machine transitions
- [ ] Verify events emitted at correct times
- [ ] Test with multiple clients connecting/disconnecting

## Benefits

- **Real-Time UI:** Update UI without polling
- **Webhooks Ready:** Foundation for external notifications
- **Debugging:** Track client behavior through event history
- **Monitoring:** External systems can subscribe to events
- **Reduced Load:** One connection per client instead of polling

## Breaking Changes

- None (new streaming feature)

## Success Criteria

- ✅ SSE endpoint streaming events correctly
- ✅ Client activity tracked and events emitted
- ✅ Event history maintained (last 100 events)
- ✅ Multiple concurrent SSE clients supported
- ✅ Events include relevant data for UI/webhooks
- ✅ Connection management robust (cleanup, timeouts)
- ✅ Fully documented with examples
