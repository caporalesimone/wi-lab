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

## Testing

- [ ] Unit tests for the metric values after a start, a repair and a quarantine

## Benefits

- **Monitoring:** Dashboards and alerts for the bench and for long runs

## Breaking Changes

- None (new endpoint)

## Success Criteria

- ✅ Prometheus scrapes the bench and the values match the API
