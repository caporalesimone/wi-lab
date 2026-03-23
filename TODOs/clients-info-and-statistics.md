# Feature: Clients Info and Statistics (Unified Proposal)

**Priority:** HIGH  
**Status:** IN PROGRESS

## Goal

Unify client visibility and traffic telemetry into a single roadmap:
- extend client-level insights (identity, signal, traffic),
- define whether to keep everything in `GET /api/v1/interface/{net_id}/network` or introduce dedicated client stats APIs.

## Scope Summary

- Analyze and classify requested telemetry by acquisition complexity.
- Implement backend data collection and APIs based on analysis outcome.
- Implement frontend UX for advanced telemetry.

---

## Extra Fields Of Interest (10+)

1. Hostname
2. Connected Since
3. Session Duration
4. Signal Strength (RSSI)
5. Signal Quality Category (Excellent/Good/Fair/Poor)
6. TX Throughput
7. RX Throughput
8. Total TX Bytes
9. Total RX Bytes
10. Vendor/Manufacturer from MAC OUI
11. Last Seen
12. Connection Band (2.4GHz/5GHz)

---

## Data Availability Analysis Baseline

### Usually immediate or cheap

- Hostname (if present in DHCP leases)
- Vendor/OUI lookup from MAC
- Last Seen (if event timestamp already tracked)
- Connection Band (if station info exposes band)

### Requires periodic sampling

- RSSI
- Signal Quality Category (derived from RSSI)
- TX/RX Throughput (needs interval-based delta)

### Requires state tracking and/or persistence

- Connected Since
- Session Duration
- Total TX/RX Bytes per session

### Higher-risk collection areas

- Stable per-client traffic metrics across reconnects
- Data merge consistency across multiple sources (`hostapd_cli`, `iw`, DHCP leases, `/proc/net/dev`)

---

## Phase 2 - Feasibility and API Strategy Analysis

### Phase checklist

- [ ] Produce field-by-field feasibility matrix
- [ ] Classify each field: instant vs sampled vs stateful
- [ ] Identify required data sources and command dependencies
- [ ] Define cache/state requirements
- [ ] Define fallback behavior for missing telemetry
- [ ] Compare endpoint design options (single endpoint vs dedicated client endpoint vs hybrid)
- [ ] Decide target architecture and document rationale

### Backend actions

- [ ] Audit current sources: DHCP leases, hostapd station data, iw, `/proc/net/dev`
- [ ] For each requested field, document acquisition path and limitations
- [ ] Define sampling cadence candidates for signal and throughput
- [ ] Define in-memory structures for client session lifecycle
- [ ] Evaluate need for persistence across service restart
- [ ] Prototype data collection commands in isolation and capture failure modes
- [ ] Define API contract options:
- [ ] Option A: enrich `GET /network`
- [ ] Option B: new endpoint `GET /api/v1/interface/{net_id}/clients/{mac}/stats`
- [ ] Option C: hybrid (recommended candidate)

### Frontend actions

- [ ] Define UX for progressive disclosure (summary row + expandable details)
- [ ] Define loading/partial-data placeholders for optional telemetry
- [ ] Define whether additional endpoint calls can be lazy-loaded per client row
- [ ] Validate expected rendering constraints with larger client lists

---

## Phase 3 - Backend Implementation (Based On Phase 2 Decision)

### Phase checklist

- [ ] Implement selected API architecture (A, B, or C)
- [ ] Implement collectors/parsers needed for telemetry
- [ ] Add cache/state management for sampled and session metrics
- [ ] Expose models and endpoints with full Swagger documentation
- [ ] Add robust tests and observability

### Backend actions

- [ ] Add/extend Pydantic models for client telemetry fields
- [ ] Implement parser/services for each selected source
- [ ] Implement background sampler for time-based metrics
- [ ] Implement state store for session-based metrics
- [ ] Implement API handlers and dependency wiring
- [ ] Add error handling for unavailable commands/data sources
- [ ] Add unit tests for parsers and aggregators
- [ ] Add integration tests for endpoint behavior and schema
- [ ] Add OpenAPI examples and response/error documentation
- [ ] Add logging/metrics for collection health and staleness

### Frontend actions

- [ ] Align frontend interfaces to new backend models
- [ ] Integrate API strategy selected in Phase 2 (single call, lazy client calls, or hybrid)
- [ ] Validate backward compatibility where telemetry is partial/unavailable

---

## Phase 4 - Frontend Implementation and UX Finalization

### Phase checklist

- [ ] Extend client table with approved additional fields
- [ ] Add formatting helpers (duration, throughput, bytes, signal badge)
- [ ] Add detail UX for advanced metrics (expand row or side panel)
- [ ] Add robust empty/loading/error states
- [ ] Validate responsiveness and readability with real data

### Backend actions

- [ ] Support frontend refinements requiring additional response metadata
- [ ] Tune payload size and freshness tradeoff based on UI behavior
- [ ] Ensure stable ordering/identity keys for client rows (MAC as primary key)

### Frontend actions

- [ ] Render base columns + advanced telemetry columns
- [ ] Add reusable formatters/pipes for units and durations
- [ ] Add signal quality visual badges
- [ ] Add client details panel/expansion UX
- [ ] Add component tests for each major state and field rendering
- [ ] Verify AP card performance with multiple connected clients

---

## Traffic Statistics Integration Notes

To preserve the intent of the previous `traffic-statistics.md`, interface-level traffic stats should be modeled as a complementary track and aligned with client telemetry:

- [ ] Keep support for interface-level counters (TX/RX bytes/packets/errors/drops)
- [ ] Keep rolling aggregates (1m/5m/15m) where useful
- [ ] Decide whether interface stats remain separate endpoint (`/stats`) or are partially surfaced in `/network`
- [ ] Ensure interface stats and per-client stats share consistent sampling and timestamp semantics

---

## Decision Record (To Fill During Phase 2)

- [ ] Chosen API strategy: A / B / C
- [ ] Chosen sampling interval for signal and throughput
- [ ] Chosen state persistence policy across restart
- [ ] Chosen frontend interaction model (always-expanded vs expandable)
- [ ] Chosen fallback behavior for unavailable telemetry
