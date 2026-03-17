# Changelog

All notable changes to Wi-Lab are documented in this file.

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

