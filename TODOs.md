# Wi-Lab Development Roadmap

## Overview

This document outlines the development milestones for Wi-Lab from v1.1.0 through v3.0.0, organized as 10 focused releases with a maximum of 3 hours effort per release. Each release follows semantic versioning across 3 major versions:

- **v1.x** (Releases 1-3): Core Observability & Analysis
- **v2.x** (Releases 4-7): Features & Advanced Capabilities  
- **v3.x** (Releases 8-10): Enterprise & Ecosystem

**Note:** This roadmap is indicative. Space is reserved for unforeseen activities and emerging opportunities.

---

# 🎯 Release 1: v1.1.0 - "Traffic Statistics API"

**Target Release:** Week 1  
**Priority:** CRITICAL  
**Estimated Effort:** ~3 hours  
**Focus:** Add API endpoints returning real-time traffic data per network

### ⭐ PRIMARY TASKS (Must Complete)

#### 1. **Traffic Statistics API Endpoint**
- **Effort:** 2 hours
- **Description:** New endpoint to retrieve real-time network statistics per AP
- **Scope:**
  - `GET /api/v1/interface/{net_id}/stats` endpoint
  - Metrics: TX bytes, RX bytes, TX packets, RX packets, TX errors, RX errors, dropped packets
  - Data source: Parse `/proc/net/dev` for interface stats
  - Response model: `NetworkStats` Pydantic model
  - Include 1-min, 5-min, 15-min averages (if available)
  - Full Swagger documentation with examples
- **Tests:** Unit tests for stat parsing, mock /proc/net/dev, response validation
- **Breaking Changes:** None

#### 2. **API Consolidation & Simplification Pass**
- **Effort:** 1 hour
- **Description:** Analyze and simplify existing APIs to reduce data duplication
- **Scope:**
  - Review all endpoints in `wilab/api/routes.py`
  - Identify duplicate data fields in responses
  - Consolidate response models (reduce redundancy)
  - Document which endpoints can be simplified
  - Plan refactoring without breaking changes
- **Tests:** Response validation, backward compatibility
- **Breaking Changes:** None (analysis only this release)

### Success Criteria
- ✅ Traffic stats API working end-to-end
- ✅ Stats endpoint tested with >90% coverage
- ✅ API consolidation analysis documented
- ✅ All 125 existing tests still passing

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🔧 Release 2: v1.2.0 - "API Refactoring & Response Optimization"

**Target Release:** Week 2  
**Priority:** HIGH  
**Estimated Effort:** ~3 hours  
**Focus:** Simplify and reduce redundant data in existing API responses

### Tasks

#### 1. **Response Model Consolidation**
- **Effort:** 2 hours
- **Description:** Merge redundant fields across response models
- **Scope:**
  - Consolidate `NetworkStatus` and network-related models
  - Remove duplicate `interface` / `net_id` references where applicable
  - Standardize timestamp formats across all responses
  - Create base model `BaseNetworkResponse` for shared fields
  - Update Swagger examples to reflect consolidated structure
- **Tests:** Response schema validation, API backward compatibility
- **Breaking Changes:** MINOR (if any fields removed, deprecate first in v1.3)

#### 2. **Lightweight Status Endpoint**
- **Effort:** 1 hour
- **Description:** Add minimal-overhead endpoint for quick health checks
- **Scope:**
  - `GET /api/v1/interface/{net_id}/status/light` - Minimal JSON (net_id, active, uptime)
  - Use for polling without fetching full data
  - Help reduce API calls for monitoring
- **Tests:** Endpoint validation, performance baseline
- **Breaking Changes:** None (new endpoint)

### Success Criteria
- ✅ Response models consolidated
- ✅ No data duplication across endpoints
- ✅ Lightweight status endpoint available
- ✅ Swagger updated with new structure
- ✅ All tests passing (including compatibility tests)

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 📊 Release 3: v1.3.0 - "Channel Validation & DHCP Insights"

**Target Release:** Week 3  
**Priority:** HIGH  
**Estimated Effort:** ~3 hours  
**Focus:** Improve network creation robustness and provide DHCP information

### Tasks

#### 1. **Channel/Band Validation**
- **Effort:** 1.5 hours
- **Description:** Validate channel against band before creating network
- **Scope:**
  - Add validator in `NetworkCreateRequest` model
  - 2.4GHz: channels 1-14 (region aware)
  - 5GHz: channels 36-165 (specific set)
  - Return 422 with clear error if invalid combination
  - Document supported channels in Swagger
- **Tests:** Valid/invalid channel tests per band
- **Breaking Changes:** None (validation only)

#### 2. **DHCP Lease Information API**
- **Effort:** 1.5 hours
- **Description:** Expose DHCP lease details and client lease status
- **Scope:**
  - New endpoint: `GET /interface/{net_id}/dhcp/leases`
  - Return per-client: MAC, IP, lease duration, remaining time
  - Parse dnsmasq lease file
  - Include renewal schedule info
- **Tests:** Lease parsing, time calculation validation
- **Breaking Changes:** None (new endpoint)

### Success Criteria
- ✅ Invalid channel combinations rejected with clear errors
- ✅ DHCP lease info endpoint working
- ✅ All validation tests passing
- ✅ Swagger documentation complete

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🛡️ Release 4: v2.1.0 - "Startup Recovery & Cleanup"

**Target Release:** Week 4-5  
**Priority:** MEDIUM-HIGH  
**Estimated Effort:** ~3 hours  
**Focus:** Graceful crash recovery and orphaned resource cleanup

### Tasks

#### 1. **Startup Crash Recovery**
- **Effort:** 1.5 hours
- **Description:** Auto-cleanup on startup if previous instance crashed
- **Scope:**
  - Detect orphaned dnsmasq processes
  - Kill and clean up stale processes
  - Verify no conflicting iptables rules
  - Log all recovery actions
  - Add recovery stats to health endpoint
- **Tests:** Orphaned process detection, cleanup verification
- **Breaking Changes:** None

#### 2. **Orphaned iptables Rule Detection**
- **Effort:** 1.5 hours
- **Description:** Identify and provide UI to clean leftover iptables rules
- **Scope:**
  - `POST /api/v1/admin/cleanup-orphaned` endpoint
  - Scan iptables rules with `wilab-*` comment markers
  - Compare against active networks
  - Provide `--dry-run` option
  - Add cleanup logs
- **Tests:** Rule detection, safe deletion verification
- **Breaking Changes:** None (new admin endpoint)

### Success Criteria
- ✅ Can recover from crash automatically
- ✅ Orphaned rules detected and cleaned
- ✅ Health endpoint reports recovery status
- ✅ Cleanup operations well-logged

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🎛️ Release 5: v2.2.0 - "SIGTERM Handling & Graceful Shutdown"

**Target Release:** Week 5-6  
**Priority:** MEDIUM  
**Estimated Effort:** ~3 hours  
**Focus:** Improve shutdown behavior for systemd and containers

### Tasks

#### 1. **Graceful SIGTERM Shutdown**
- **Effort:** 1.5 hours
- **Description:** Improve signal handling for systemd and container shutdown
- **Scope:**
  - Catch SIGTERM and SIGINT signals
  - Stop all active networks gracefully
  - Flush all NAT rules within timeout
  - Stop DHCP servers cleanly
  - Max 10-second shutdown window before force kill
  - Log shutdown sequence
- **Tests:** Signal handling, cleanup verification
- **Breaking Changes:** None

#### 2. **Configuration Validation on Startup**
- **Effort:** 1.5 hours
- **Description:** Validate all config parameters before starting service
- **Scope:**
  - Pre-flight check: DHCP subnet collision with host network
  - Scan existing interfaces with `ip addr`
  - Compare with `dhcp_base_network`
  - Add `--strict-subnet-check` flag to block on collision
  - Result in health check endpoint
- **Tests:** Collision detection, configuration override scenarios
- **Breaking Changes:** None

### Success Criteria
- ✅ SIGTERM handled gracefully
- ✅ All resources cleaned on shutdown
- ✅ DHCP subnet collisions detected
- ✅ Shutdown logs clear and helpful

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🔄 Release 6: v2.3.0 - "Per-Client Controls: Blocking & Rate Limiting"

**Target Release:** Week 6-7  
**Priority:** HIGH  
**Estimated Effort:** ~3 hours  
**Focus:** Fine-grained control over individual client devices

### Tasks

#### 1. **Per-MAC Address Client Blocking**
- **Effort:** 1.5 hours
- **Description:** Block/unblock individual clients by MAC address
- **Scope:**
  - `POST /interface/{net_id}/client/{mac}/block` - Block client
  - `POST /interface/{net_id}/client/{mac}/unblock` - Unblock client
  - Backend: iptables rules to DROP traffic from/to MAC
  - Track blocked clients in memory per network
  - Return 404 if client not connected
- **Tests:** Block/unblock functionality, MAC validation, traffic drop verification
- **Breaking Changes:** None

#### 2. **Per-MAC Basic Rate Limiting**
- **Effort:** 1.5 hours
- **Description:** Apply basic bandwidth limits to individual clients
- **Scope:**
  - `POST /interface/{net_id}/client/{mac}/rate-limit` endpoint
  - Parameters: `rate_mbps` (1-100 Mbps)
  - Backend: Use `tc` (traffic control) HTB qdisc per MAC
  - Return current rate limits in client info
  - Log rate limit applications
- **Tests:** Rate limit application, tc command validation
- **Breaking Changes:** None

### Success Criteria
- ✅ Can block individual clients by MAC
- ✅ Can limit client bandwidth
- ✅ Operations well-tested and logged
- ✅ Client info includes limit status

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🎪 Release 7: v2.4.0 - "Real-Time Events & Webhooks"

**Target Release:** Week 7-8  
**Priority:** MEDIUM  
**Estimated Effort:** ~3 hours  
**Focus:** Real-time event streaming for external integrations

### Tasks

#### 1. **Server-Sent Events (SSE) Streaming**
- **Effort:** 1.5 hours
- **Description:** Real-time event notifications for network activities
- **Scope:**
  - `GET /api/v1/interface/{net_id}/events` SSE endpoint
  - Events: client_connected, client_disconnected, network_expiring, ap_started, ap_stopped
  - Store last 100 events in memory per network
  - Use FastAPI StreamingResponse
  - Full Swagger documentation with examples
- **Tests:** SSE endpoint tests, event emission verification
- **Breaking Changes:** None

#### 2. **Client Activity Tracking**
- **Effort:** 1.5 hours
- **Description:** Track and report client connect/disconnect events
- **Scope:**
  - Monitor hostapd activity for client connections
  - Emit events on client join/leave
  - Track connection time and last activity
  - Include in client info response
  - Trigger SSE notifications
- **Tests:** Activity tracking, event generation
- **Breaking Changes:** None

### Success Criteria
- ✅ SSE endpoint streaming events
- ✅ Client activity tracked accurately
- ✅ Events emitted at right times
- ✅ Real-time UI integration possible

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🚀 Release 8: v3.1.0 - "Python SDK & CLI Tool"

**Target Release:** Week 8-9  
**Priority:** MEDIUM  
**Estimated Effort:** ~3 hours  
**Focus:** Developer tools for programmatic API access and command-line control

### Tasks

#### 1. **Python Client SDK**
- **Effort:** 1.5 hours
- **Description:** Official Python library for API integration
- **Scope:**
  - New package: `wilab-client` (or `wilab/sdk/`)
  - Classes: `WiLabClient`, `Network`, `Client`
  - Methods for all API operations
  - Async support with httpx
  - Full docstrings and type hints
  - Published to PyPI (if separate package)
- **Tests:** SDK functionality, integration with API
- **Breaking Changes:** None (new package)

#### 2. **CLI Tool (wilab-cli)**
- **Effort:** 1.5 hours
- **Description:** Command-line interface for Wi-Lab control
- **Scope:**
  - Executable: `wilab-cli` command
  - Subcommands: list, create, delete, clients, stats, control, block-client
  - Config file: `~/.wilab/config.yml` for server URL and token
  - Output formats: table (default), JSON, CSV
  - Tab completion support
- **Tests:** Command execution, output format validation
- **Breaking Changes:** None (new tool)

### Success Criteria
- ✅ Python SDK functional and documented
- ✅ CLI tool available with all core commands
- ✅ PyPI package published (if separate)
- ✅ Usage examples provided

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 📈 Release 9: v3.2.0 - "Prometheus Metrics & Observability"

**Target Release:** Week 9-10  
**Priority:** MEDIUM  
**Estimated Effort:** ~3 hours  
**Focus:** Metrics export for enterprise monitoring and alerting systems

### Tasks

#### 1. **Prometheus Metrics Endpoint**
- **Effort:** 2 hours
- **Description:** Export metrics for Prometheus and monitoring systems
- **Scope:**
  - New endpoint: `GET /metrics` (standard Prometheus format)
  - Metrics:
    - `wilab_networks_active` - Count of active networks
    - `wilab_clients_connected` - Total connected clients
    - `wilab_network_uptime_seconds` - Per-network uptime
    - `wilab_api_requests_total` - Request count by endpoint/method
    - `wilab_api_request_duration_seconds` - Request latency histogram
    - `wilab_health_check_status` - Service health (1=ok, 0=error)
  - Use `prometheus-client` library
  - Support standard Prometheus scraping
- **Tests:** Metrics endpoint format, counter accuracy
- **Breaking Changes:** None

#### 2. **Health Check Enhancements**
- **Effort:** 1 hour
- **Description:** Extended health check with detailed status information
- **Scope:**
  - Expand `GET /api/v1/health` response
  - Include: dnsmasq status, iptables status, upstream connectivity
  - Add recovery status, orphaned rule count
  - Use for Prometheus health metric
- **Tests:** Health check validation
- **Breaking Changes:** Additive only (backward compatible)

### Success Criteria
- ✅ Prometheus metrics exported correctly
- ✅ Monitoring systems can scrape /metrics
- ✅ Health check comprehensive and accurate
- ✅ Alerting rules can be built on metrics

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

# 🏢 Release 10: v3.3.0 - "Multi-SSID, Docker Support & Beyond"

**Target Release:** Week 10-11  
**Priority:** MEDIUM  
**Estimated Effort:** ~3 hours  
**Focus:** Enterprise features and deployment flexibility

### Tasks

#### 1. **Docker Compose Support**
- **Effort:** 1 hour
- **Description:** Provide docker-compose.yml for containerized deployment
- **Scope:**
  - Create `docker-compose.yml` in project root
  - Services: wilab API, optional nginx reverse proxy
  - Host network mode for WiFi access
  - Volume mounts for config and data
  - Add `.dockerignore` file
  - Documentation: Docker setup guide
- **Tests:** Compose file validation, container startup verification
- **Breaking Changes:** None (optional)

#### 2. **Regulatory Domain Support**
- **Effort:** 1 hour
- **Description:** Support different WiFi regulatory domains
- **Scope:**
  - New parameter: `regulatory_domain` (US, EU, JP, etc.)
  - Backend: Use `iw reg set` to configure
  - Validate domain before application
  - Document channel availability per region
  - Add to health check: current regulatory domain
- **Tests:** Regulatory domain validation, channel tests per region
- **Breaking Changes:** None (optional field)

#### 3. **Advanced Features Foundation**
- **Effort:** 1 hour
- **Description:** Foundation for future enterprise capabilities
- **Scope:**
  - Document multi-SSID architecture (not implementing yet)
  - Prepare for future WPA-Enterprise / RADIUS integration
  - Design persistent network storage interface (Redis/SQLite ready)
  - Identify performance bottlenecks for v3.4+
- **Tests:** Architecture documentation, design review
- **Breaking Changes:** None (planning only)

### Success Criteria
- ✅ Docker Compose deployment working
- ✅ Regulatory domains configurable
- ✅ Enterprise features roadmap clear for next phase
- ✅ System ready for v3.4+ enhancements

### Unplanned Activities Reserved
*Space available for unexpected fixes or enhancements*

---

## 📊 Release Summary

| # | Version | Name | Duration | Effort | Focus |
|---|---------|------|----------|--------|-------|
| 1 | v1.1.0 | Traffic Stats API | Week 1 | ~3h | Traffic data, API analysis |
| 2 | v1.2.0 | API Refactoring | Week 2 | ~3h | Consolidate responses |
| 3 | v1.3.0 | Channel Validation & DHCP | Week 3 | ~3h | Network creation robustness |
| 4 | v2.1.0 | Startup Recovery | Week 4-5 | ~3h | Crash recovery, cleanup |
| 5 | v2.2.0 | Graceful Shutdown | Week 5-6 | ~3h | SIGTERM handling, validation |
| 6 | v2.3.0 | Client Controls | Week 6-7 | ~3h | Per-MAC blocking, rate limit |
| 7 | v2.4.0 | Real-Time Events | Week 7-8 | ~3h | SSE, webhooks, activity |
| 8 | v3.1.0 | SDK & CLI | Week 8-9 | ~3h | Python tools, CLI |
| 9 | v3.2.0 | Prometheus Metrics | Week 9-10 | ~3h | Observability, monitoring |
| 10 | v3.3.0 | Enterprise Features | Week 10-11 | ~3h | Docker, domains, planning |
| | **v3.3.0** | **TOTAL** | **~11 weeks** | **~30h** | **Full platform** |

---

## 🔮 Post-v3.3.0 Opportunities

The following features are candidates for v3.4+ and beyond:

- **Multi-SSID Virtual AP Support** - Multiple networks per interface (8-10h)
- **WPA-Enterprise / RADIUS Integration** - Enterprise authentication (8-10h)
- **Persistent Network Storage** - Redis/SQLite backends (4-6h)
- **Advanced Traffic Shaping** - Full tc/qdisc support (6-8h)
- **Channel DFS / Weather Radar Awareness** - 5GHz compliance (4-6h)
- **Bulk Operations API** - Create/delete multiple networks (2-3h)
- **API Versioning Strategy** - v1 → v2 migration path (2-3h)
- **Request Idempotency** - Safe replay of operations (1-2h)
- **Client SDK Extensions** - Go, Node.js, Rust clients (3-5h each)

---

## 🛠️ Development Best Practices

### Per-Release Process
1. **Planning** - Define exact tasks and effort estimates (this document)
2. **Development** - Implement features with tests (>90% coverage)
3. **Testing** - Unit, integration, and edge case tests
4. **Integration** - Ensure backward compatibility
5. **Documentation** - Update README, Swagger, guides
6. **Release** - Tag version, create GitHub release, changelog

### Quality Gates
- All existing tests must pass
- New code coverage >90%
- Backward compatibility maintained
- Swagger documentation updated
- CHANGELOG entry added

### Parallel Development
After stabilization, releases can overlap:
- Can start Release N+1 while Release N is in testing/documentation phase
- Critical path: Traffic Stats → API Analysis → Recovery/Cleanup

---

## 📝 Notes

- **Effort Estimates:** Based on similar implementations; actual time may vary
- **Unplanned Activities:** Each release reserves ~0.5h buffer for unexpected fixes or refinements
- **Release Timing:** Assumes continuous development; can be parallelized for faster delivery
- **Community Feedback:** Roadmap subject to change based on user priorities
- **Testing:** All releases require >90% code coverage on new code

---

**Last Updated:** 2026-01-11  
**Status:** Ready for development ✅  
**Next Step:** Begin Release 1 (v1.1.0) - Traffic Statistics API
