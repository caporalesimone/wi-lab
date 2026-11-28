# Feature: Prometheus Metrics

**Priority:** 7  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Expose the state of the bench as Prometheus metrics, for Grafana dashboards and
alerts on long tests.

## Implementation Tasks

- [ ] `GET /metrics` (token or a separate bind address)
- [ ] Gauges: antennas free/reserved/quarantined, running networks, clients per network
- [ ] Counters: reservations, starts and failures, watchdog repairs, USB resets, stuck commands
- [ ] Histograms: start duration, host command duration

## API Proposal

### `GET /metrics`

Prometheus metrics (text format), with the token or on a separate bind address.

Request: no body.

Response `200`: no body.

Response `200` (`text/plain; version=0.0.4`):

```text
wilab_antennas{state="free"} 1
wilab_antennas{state="reserved"} 1
wilab_access_points_running 1
wilab_clients{antenna="wlx7419f8176286"} 2
wilab_starts_total{result="active"} 128
wilab_watchdog_repairs_total{kind="ap_restore"} 3
wilab_usb_resets_total 1
wilab_start_duration_seconds_bucket{le="10"} 120
```

## Testing

- [ ] Unit tests for the metric values after a start, a repair and a quarantine

## Benefits

- **Monitoring:** Dashboards and alerts for the bench and for long runs

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Prometheus scrapes the bench and the values match the API
