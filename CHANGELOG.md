# Changelog

All notable changes to Wi-Lab are documented in this file.

---

## [1.3.1] - 2026-03-23

### 🔒 Security

- **Fixed unauthenticated access to `/api/v1/debug` endpoint**
  - `GET /api/v1/debug` now requires a valid Bearer token, consistent with all other protected endpoints
  - Previously, the endpoint exposed full system debug information (services, interfaces, diagnostics) without authentication

### 🧪 Testing

- Added `test_debug_requires_auth`: verifies `GET /api/v1/debug` returns `401` without a token
- Added `test_debug_with_invalid_token`: verifies `GET /api/v1/debug` returns `401` with an invalid token
- Updated existing `TestDebugEndpoint` tests to supply the valid Bearer token header

---

## [1.3.0] - 2026-03-18

### 🐛 Bug Fixes

- **TX Power POST Hardware Mismatch Handling**
  - `POST /api/v1/interface/{net_id}/txpower` now returns HTTP `422 Unprocessable Entity` when the wireless interface reports a different power than the requested one
  - Replaced warning-style success handling with explicit API error semantics for unsupported dynamic TX power changes
- **TX Power POST Out-of-Range Validation**
  - `POST /api/v1/interface/{net_id}/txpower` now always returns HTTP `422 Unprocessable Entity` for out-of-range levels
  - Out-of-range errors now use a short and stable payload: `{"detail": "Requested power out of range. Valid values are 1, 2, 3, 4."}`

### ✨ Features

- **Client Details in Network Cards (Phase 1)**
  - Replaced count-only view with a connected clients table in each active AP card
  - Added client list columns for `IP Address` and `MAC Address`
  - Added empty-state message when no clients are connected
  - Kept polling-based refresh behavior unchanged

- **Network Card Status Visibility Improvements**
  - Added `TX Power` row with descriptive values matching the creation dialog labels
  - Added `Expires in` row with human-readable duration formatting (`h m s`)
  - Dynamic card border state by Internet status:
    - Green when Internet is enabled
    - Yellow when Internet is disabled

- **AP Diagnostic Utility Restoration**
  - Restored the AP diagnostic helper on `main`
  - Moved the script from `scripts/10-diagnose-ap.py` to `diagnostics/diagnose-ap.py`
  - Added clearer command-line usage examples for running diagnostics from the repository root

- **Requested vs Reported TX Power API Model**
  - Added nested `tx_power` payloads exposing `requested_level`, `reported_level`, and `reported_dbm`
  - `GET /api/v1/interface/{net_id}/network` now includes TX power details alongside DHCP and client information
  - `GET /api/v1/interface/{net_id}/txpower` now returns the same requested/reported TX power structure

### 🎨 UI/UX

- Simplified clients summary presentation:
  - Removed duplicate `Clients` row
  - Kept `Connected Clients:` label with right-aligned count
- Improved spacing and readability in network cards:
  - Increased separation between interface subtitle and details section
  - Reduced vertical spacing between detail rows (`SSID`, `Password`, `Channel`, etc.)
- Refined card header layout:
  - Kept WiFi icon, network name, and interface subtitle consistently left-aligned
- Moved Internet status indicator to the top-right corner of the card:
  - Replaced text chip with icon-only rounded rectangular badge
  - Green badge with `cloud_done` when Internet is available
  - Yellow badge with `cloud_off` when Internet is disabled
  - Added hover tooltip text: `Internet available` / `Internet disabled`
- Updated inactive card copy:
  - Replaced `No active network` with `Access point <net_id> disabled.`
  - Network name is emphasized in bold for better visibility
- Updated frontend network cards to display `TX Power requested/reported` instead of a single legacy TX power level

### 🔧 Refactoring & Infrastructure

- **TX Power Response Reshape**
  - Introduced shared backend model for requested/reported TX power data
  - Removed legacy flat TX power fields such as `current_level`, `current_dbm`, and top-level `reported_dbm`
  - Removed the legacy warning field from successful TX power responses

- **OpenAPI Example Alignment**
  - Updated Swagger examples for `GET /api/v1/interface/{net_id}/network`
  - Updated Swagger examples for `GET /api/v1/interface/{net_id}/txpower` to match the nested `tx_power` response shape
  - Added explicit Swagger examples for `POST /api/v1/interface/{net_id}/txpower` success and `422` error variants (out-of-range and hardware mismatch)

### 🧪 Testing

- Added/updated backend API coverage for `GET /api/v1/interface/{net_id}/network` client structure:
  - Validates `clients[]` payload entries include stable `ip` and `mac` fields
  - Confirms correct `clients_connected` count for active networks
- Added manager-level TX power coverage:
  - Validates requested TX power updates keep internal state in sync on success
  - Validates hardware mismatch raises an error and preserves the previous configured TX power level
- Added API coverage for TX power endpoints:
  - Verifies nested `tx_power` serialization on `GET /api/v1/interface/{net_id}/txpower`
  - Confirms legacy warning and flat TX power fields are no longer exposed by the GET response
  - Confirms `POST /api/v1/interface/{net_id}/txpower` returns `422` on hardware mismatch
  - Confirms `POST /api/v1/interface/{net_id}/txpower` returns the simplified `422` out-of-range error message
  - Confirms OpenAPI schema documents `422` examples for both out-of-range and hardware mismatch cases

### 📝 Documentation

- Consolidated client and traffic planning docs into:
  - `TODOs/clients-info-and-statistics.md`
- Removed overlapping legacy planning document:
  - `TODOs/traffic-statistics.md`

---

## [1.2.1] - 2026-03-18

### 🐛 Bug Fixes

- **Hostapd Startup Timeout**: Fixed intermittent hostapd failures on interface transitions
  - Command execution timeout increased from hardcoded 1s to configurable 8s default
  - Minimum timeout floor enforced at 5s to prevent accidental timeouts
  - Resolves "Failed to start hostapd" errors during AP initialization
  - Added comprehensive test coverage for timeout enforcement

### ✨ Features

- **Dynamic WiFi Network Names**: SSID now generated based on AP identifier
  - Format: `test-network-ap-01`, `test-network-ap-02`, `test-network-ap-03`
  - Each AP card displays unique, recognizable network name
  - Prevents duplicate network names across multiple access points
  - Frontend dynamically generates SSID from AP ID parameter

### 🔧 Refactoring & Infrastructure

- **Setup → Install Terminology Migration**:
  - Renamed `install/02-setup-stages/` → `install/02-install-stages/`
  - Updated variable naming: `SETUP_DIR` → `INSTALL_DIR`, `setup_common_vars()` → `install_common_vars()`
  - Consistent terminology across all installation scripts and documentation
  - Removed backward compatibility alias (internal scripts only)

- **API Response Documentation**:
  - Explicitly documented 401 Unauthorized responses in OpenAPI/Swagger schema
  - All authentication-protected endpoints now properly reflected in API documentation
  - Improved API contract clarity for client implementations

- **Development Tooling**:
  - Added `restart-service.sh` utility script for rapid development iteration
  - Simplified restart flow: stop (10s → 5s) → wait → start
  - Removed unnecessary Docker container check (frontend served as static files)

### 📝 Testing

- Enhanced timeout behavior validation:
  - Test coverage for default 8s timeout enforcement
  - Test coverage for 5s minimum timeout clamping
  - Added custom timeout configuration tests
  - All 136+ tests passing

### 📦 Dependencies & Build

- Frontend build optimization: reduced bundle size analysis and warnings review
- Docker multi-stage build for frontend compilation remains unchanged

---

## [1.2.0] - 2026-01-29

### 🚀 Major API Simplification

- **Unified Network Endpoints** (Breaking Change):
  - Consolidated 4 redundant endpoints into single `GET /interface/{net_id}/network`
  - **Removed endpoints**: `/interface/{net_id}/status`, `/interface/{net_id}/summary`, `/interface/{net_id}/clients`
  - New unified endpoint returns complete network state: configuration, DHCP info, connected clients
  - 75% reduction in API surface area (4→1 endpoints)
  - Enhanced `NetworkStatus` model with `dhcp`, `clients`, `clients_connected` fields
  - Frontend migrated to use unified endpoint (1 call instead of 3)

### ✨ Features

- **Version Display**: Software version (1.2.0) now displayed in frontend page title
- **Enhanced Swagger UI**: Added example values (`ap-01`) precompiled in all `net_id` parameters
- **System Health Monitoring**:
  - Added `/api/v1/status` endpoint (renamed from `/health`) with comprehensive health checks
  - Standby mode when no networks active
  - Checks: dnsmasq status, iptables NAT, upstream interface connectivity
  - Status levels: `ok`, `standby`, `degraded`
  
- **Debug Endpoint**: New `/api/v1/debug` endpoint for troubleshooting
  - System info: OS, kernel, Python version, uptime
  - Network diagnostics: active networks, DHCP leases, iptables rules
  - Service status: hostapd, dnsmasq processes
  - ~600ms response time for comprehensive diagnostics

### 🔒 Security

- **Authentication Enforcement**: `/api/v1/status` endpoint now requires authentication token
- All system status endpoints protected behind auth layer

### 🔧 Refactoring & Code Quality

- **API Route Organization**:
  - Renamed `health.py` → `status.py` for semantic clarity
  - Removed `clients.py` route file (functionality merged into network endpoint)
  - Deleted `ClientsResponse` model (no longer needed)
  - Cleaner route structure and reduced code duplication

- **JSON Response Optimization**:
  - Reordered `/status` endpoint fields: `version` → `status` → `networks` → `active_networks` → `checks`
  - More logical field ordering for better API ergonomics

- **Code Reduction**:
  - Removed `get_summary()` method from NetworkManager
  - Eliminated 251 lines of redundant code across backend and frontend
  - Simplified frontend service: removed `getClients()` and `loadClients()` methods

### 🧪 Testing

- **Test Suite Optimization**: Reduced from 33 to 29 tests (removed redundant endpoint tests)
- **Enhanced Coverage**: Added comprehensive test for unified network endpoint with DHCP and clients validation
- All tests passing with new consolidated structure

### 📚 Documentation

- **API Simplification**: Updated `TODOs/api-simplification.md` to COMPLETED status
- **Swagger Documentation**: Updated OpenAPI specs with consolidated endpoint structure
- Improved endpoint descriptions and response examples

### ⚡ Performance

- Frontend efficiency: Single API call replaces 2-3 previous calls for network status
- Reduced network overhead and improved page load times

---

## [1.1.0] - 2026-01-29

### 🔧 Refactoring & Infrastructure Improvements

- **Modularized Setup Infrastructure**:
  - Centralized common functions in `install/common.sh` (9 reusable functions)
  - Split setup into 15 modular stages (5 preconditions + 5 setup + 5 tests)
  - Eliminated all code duplication across setup scripts
  - 60% reduction in install.sh size (from 436 to 76 lines)

- **Dynamic Stage Discovery**:
  - Setup stages automatically discovered at runtime from `install/` directory
  - Numerical sorting ensures correct execution order
  - Add new stages without modifying install.sh
  - Each stage independent and reusable

- **Setup Orchestrator Pattern**:
  - Replaced monolithic install.sh with slim orchestrator
  - Complex logic moved to individual `install/*` stage scripts
  - User confirmation flow and dynamic config extraction
  - Added `install/99-final-test.sh` for comprehensive verification

- **API Routes Refactoring**:
  - Split monolithic `routes.py` into modular domain-based structure
  - Separate modules: clients, health, internet, network, txpower
  - Improved maintainability and testability

- **Make Scripts Executable**:
  - Ensured all install.sh and uninstall.sh scripts have execute permissions
  - Improved CI/CD pipeline compatibility

### 🐛 Bug Fixes

- **Fix Homepage Test**: Updated to use GET request for reliable HTTP detection
- **Prevent Duplicate iptables Rules**: Enhanced rule creation logic to prevent duplicates
- **Fix Gateway Assignment**: Corrected gateway assignment logic
- **Fix Client Count Reporting**: Fixed reported number of connected clients calculation
- **Test Hardware Independence**: Made tests hardware-independent for better CI/CD compatibility
- **Improve NAT Test Mocks**: Enhanced mocks in `test_enable_nat_auto_upstream` to distinguish between commands
- **Extract Docker IMAGE_NAME**: Improved DRY principle by extracting `IMAGE_NAME` from `deploy_frontend.sh` in uninstall script

### 📖 Documentation & Configuration

- **API Documentation**: Added HTTP status codes to Swagger/OpenAPI responses
- **Configuration Management**: Improved config.yaml handling with example file
- **Development Guidelines**: Updated copilot instructions for development best practices
- **Service Naming**: Renamed service from `wilab.service` to `wi-lab.service` for consistency

### 🔐 Security & CORS

- **CORS Support**: Enhanced frontend integration with proper Cross-Origin Resource Sharing configuration
- **Allowed Origins**: Updated configuration for cross-domain requests between frontend and backend

---

## [1.0.0] - Initial Release

### 🎯 Core Features

- **WiFi Network Management**:
  - Create and manage WiFi networks with customizable SSID and security settings
  - Network lifecycle management (create, activate, deactivate, delete)
  - Support for WPA2 authentication

- **Client Management**:
  - Real-time client connection monitoring
  - Client device tracking and identification
  - Connection history and statistics

- **DHCP Server**:
  - Integrated DHCP server with configurable subnet allocation
  - Automatic IP assignment to connected clients
  - Lease management and renewal

- **NAT & Internet Access**:
  - Network Address Translation (NAT) for client internet connectivity
  - Upstream connection handling
  - Automatic upstream detection and configuration

- **Traffic Control**:
  - Linux `tc` (traffic control) integration for advanced network management
  - TX power management for WiFi interface control

- **REST API**:
  - Full-featured REST API for network operations
  - Comprehensive health check endpoint
  - Swagger/OpenAPI documentation

- **Frontend Application**:
  - Angular-based web frontend for network management
  - Real-time network status monitoring
  - Client device management interface
  - Production-ready Docker build

- **Systemd Service**:
  - Linux systemd service integration
  - Automatic service startup on boot
  - Service lifecycle management

- **Docker Support**:
  - Docker containerization for easy deployment
  - Docker Compose for multi-service orchestration
  - Frontend build integrated in Docker pipeline

### 🛠️ System Requirements

- Linux OS with WiFi support (hostapd, dnsmasq)
- Python 3.8+
- Docker & Docker Compose
- Network interface management capabilities

### 📚 Documentation

- Comprehensive setup and installation guide
- API documentation with examples
- Network configuration guide
- Troubleshooting documentation
- Development guidelines for contributors

### 🔐 Security Features

- HTTPS support for API endpoints
- Configuration validation on startup
- Security checks for network isolation
- Safe cleanup of system resources

### 🚀 Setup & Installation

- Automated setup script for quick deployment
- Multi-stage installation with verification
- Service registration and auto-start configuration
- Health checks and validation

---

