# Feature: Prometheus Metrics & Observability

**Priority:** 9  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Export metrics in Prometheus format for integration with enterprise monitoring and alerting systems.

## Part 1: Prometheus Metrics Endpoint

### Implementation Tasks

- [ ] Create `/metrics` endpoint (standard Prometheus path)
- [ ] Use `prometheus-client` Python library
- [ ] Implement metrics:

### Metrics to Export

#### Counter Metrics (cumulative, always increase)
- [ ] `wilab_networks_created_total` - Total networks created
- [ ] `wilab_networks_deleted_total` - Total networks deleted
- [ ] `wilab_clients_connected_total` - Total client connections
- [ ] `wilab_api_requests_total` - API requests by endpoint/method
  - Labels: `endpoint`, `method`, `status_code`
- [ ] `wilab_errors_total` - Error count by type
  - Labels: `error_type`

#### Gauge Metrics (can go up/down)
- [ ] `wilab_networks_active` - Currently active networks
- [ ] `wilab_clients_connected` - Currently connected clients per network
  - Labels: `net_id`
- [ ] `wilab_network_uptime_seconds` - Per-network uptime
  - Labels: `net_id`
- [ ] `wilab_service_uptime_seconds` - Service uptime since last restart
- [ ] `wilab_orphaned_processes` - Count of orphaned resources detected
- [ ] `wilab_api_request_in_flight` - Current in-flight API requests

#### Histogram Metrics (request latency distribution)
- [ ] `wilab_api_request_duration_seconds` - API request latency distribution
  - Labels: `endpoint`, `method`
  - Buckets: 0.01, 0.05, 0.1, 0.5, 1.0, 5.0
- [ ] `wilab_network_create_duration_seconds` - Network creation duration
- [ ] `wilab_network_delete_duration_seconds` - Network deletion duration

#### Info/Status Metrics
- [ ] `wilab_health_status` - Service health (1=ok, 0=error)
- [ ] `wilab_config_validation_status` - Config validation status (1=ok, 0=error)
- [ ] `wilab_build_info` - Build metadata (version, commit, etc.)

### Implementation Details

- [ ] Use decorators for automatic metric collection
- [ ] Create middleware for API request metrics
- [ ] Background task to periodically update gauge metrics
- [ ] Namespace all metrics with `wilab_` prefix
- [ ] Include helpful labels for dimensionality
- [ ] Format output per Prometheus text format specification

### Prometheus Text Format

```
# HELP wilab_networks_active Currently active networks
# TYPE wilab_networks_active gauge
wilab_networks_active 3
```

### Testing

- [ ] Unit tests for metric collection
- [ ] Test metric format correctness
- [ ] Verify labels and values
- [ ] Test counter behavior (always increasing)
- [ ] Test gauge behavior (can change)
- [ ] Integration test with Prometheus scraping

## Part 2: Health Check Enhancements

### Implementation Tasks

- [ ] Expand `GET /api/v1/health` response with:
  - `dnsmasq_status` (running / stopped / error)
  - `iptables_status` (accessible / error)
  - `network_interfaces_status` (healthy / degraded)
  - `upstream_connectivity` (reachable / unreachable)
  - `recovery_actions` (list of cleanup actions on startup)
  - `timestamp` (health check time)

### Health Check Frequency

- [ ] Update health metrics every 10 seconds
- [ ] Cache results to avoid performance hit
- [ ] Trigger on-demand updates if health requested

### Response Format

```json
{
  "status": "healthy",
  "version": "1.2.0",
  "uptime_seconds": 3600,
  "networks_active": 3,
  "clients_connected": 12,
  "health_details": {
    "dnsmasq": "running",
    "iptables": "ok",
    "interfaces": "healthy",
    "upstream": "reachable"
  },
  "recovery_actions": [
    {"action": "killed_orphaned_process", "pid": 12345, "timestamp": "2026-01-28T10:00:00Z"}
  ],
  "timestamp": "2026-01-28T10:05:30Z"
}
```

### Testing

- [ ] Unit tests for health check collection
- [ ] Integration tests for endpoint
- [ ] Verify Prometheus can scrape metrics successfully
- [ ] Test with Prometheus instance if available

## Integration with Monitoring Systems

### Prometheus Configuration Example

```yaml
scrape_configs:
  - job_name: 'wilab'
    static_configs:
      - targets: ['localhost:8080']
    metrics_path: '/metrics'
    scrape_interval: 30s
```

### Alert Rules Example

```yaml
groups:
  - name: wilab
    rules:
      - alert: WiLabDown
        expr: up{job="wilab"} == 0
      - alert: HighErrorRate
        expr: rate(wilab_errors_total[5m]) > 0.05
      - alert: TooManyOrphanedResources
        expr: wilab_orphaned_processes > 5
```

## Benefits

- **Enterprise Ready:** Prometheus integration out-of-the-box
- **Visibility:** Comprehensive metrics for monitoring
- **Alerting:** Foundation for automated alerts
- **Performance Analysis:** Understand API performance trends
- **Capacity Planning:** Monitor resource utilization

## Breaking Changes

- None (new endpoint, health endpoint additive)

## Success Criteria

- ✅ `/metrics` endpoint exports Prometheus format correctly
- ✅ All metrics collected and updated regularly
- ✅ Prometheus can scrape endpoint successfully
- ✅ Health endpoint returns detailed status
- ✅ Metrics labels and values accurate
- ✅ Documentation includes example Prometheus config
- ✅ Example alert rules provided
