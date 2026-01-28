# Feature: Traffic Statistics - TX/RX per Interface

**Priority:** 3 (HIGH)  
**Status:** IN_PROGRESS  
**Estimated Effort:** ~2 hours  

## Description

Provide real-time traffic statistics (bytes sent/received, packet counts, errors) for each network interface. Essential for monitoring network usage and performance.

### Metrics Collected

Per interface:
- **TX Bytes** - Total bytes transmitted
- **RX Bytes** - Total bytes received
- **TX Packets** - Total packets transmitted
- **RX Packets** - Total packets received
- **TX Errors** - Transmission errors
- **RX Errors** - Reception errors
- **TX Dropped** - Dropped outgoing packets
- **RX Dropped** - Dropped incoming packets

### Time-based Aggregates

- **1-min average** - Traffic average over last minute
- **5-min average** - Traffic average over last 5 minutes
- **15-min average** - Traffic average over last 15 minutes

## Implementation Tasks

### Data Collection

- [ ] Create `NetworkStats` Pydantic model with all metrics
- [ ] Parse `/proc/net/dev` to extract interface statistics
- [ ] Create parser function to handle Linux netdev format
- [ ] Handle edge cases (interface disappears, wraparound counters)
- [ ] Implement sliding window for time-based averages

### API Endpoint

- [ ] Create `GET /api/v1/interface/{net_id}/stats` endpoint
- [ ] Return: `NetworkStats` with current and averaged metrics
- [ ] Include timestamp of last update
- [ ] Include network uptime calculation
- [ ] Add full Swagger documentation with examples

### Data Storage

- [ ] Store recent samples in circular buffer (last 60 minutes)
- [ ] Calculate 1/5/15 min averages from buffer
- [ ] Handle network restarts (reset statistics)
- [ ] Maintain statistics across API restarts (optional: persistent storage)

### Backend Integration

- [ ] Add background task to collect stats every 10 seconds
- [ ] Handle collection failures gracefully
- [ ] Expose stats in health check endpoint
- [ ] Add debug logging for stat collection

### Testing

- [ ] Unit tests for `/proc/net/dev` parsing
- [ ] Mock netdev file with various scenarios
- [ ] Test average calculations accuracy
- [ ] Integration tests for endpoint
- [ ] Test with actual traffic generation (if possible)

### Frontend (Optional)

- [ ] Display traffic graphs (TX/RX over time)
- [ ] Show current rates (bytes/sec, packets/sec)
- [ ] Display error counts and dropped packets
- [ ] Update charts every 5-10 seconds

## Benefits

- **Visibility:** Monitor network usage in real-time
- **Diagnostics:** Identify network problems via error/drop counts
- **Performance Monitoring:** Track bandwidth utilization
- **Alerting:** Foundation for traffic-based alerts

## Breaking Changes

- None (new feature)

## Success Criteria

- ✅ Stats endpoint returns accurate data
- ✅ `/proc/net/dev` parsing robust and handles edge cases
- ✅ Averages calculated correctly over time windows
- ✅ Stats update with 10-second frequency minimum
- ✅ Endpoint fully documented in Swagger
- ✅ >90% test coverage for statistics module
- ✅ No performance impact on API responses
