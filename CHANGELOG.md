# Changelog

All notable changes to Wi-Lab are documented in this file.

---

## [3.0.0] - 2026-04-18

### ✨ Features

- **QoS bandwidth throttling** – New `POST/GET/DELETE /api/v1/interface/{reservation_id}/qos` endpoints for per-reservation download/upload speed limiting via Linux `tc` HTB + IFB. Supports partial updates (omit = keep, `null` = reset, value = apply).
- **QoS link quality degradation** – Simulated link impairment via `netem` (packet loss, latency, jitter, corruption). Controllable through a 0–100% quality score (formula-mapped) or advanced per-parameter overrides (`QosQualityAdvanced`). Both download and upload directions independently configurable.

---

## [2.5.1] - 2026-04-18

### 🔧 Maintenance

- **Non-interactive version bump support** – `update_version.sh` now accepts `--bump-to X.Y.Z`, while preserving the interactive prompt when no argument is provided.

### 🐛 Bug Fixes

- **Aligned frontend typing with unlimited reservation responses** – The frontend `NetworkStatus` model now accepts `expires_at: null` and `expires_in: null`, matching the backend contract for unlimited reservations on `GET /api/v1/interface/{reservation_id}/network`.

### ✅ Tests

- **Added explicit unlimited reservation API coverage** – New tests verify that both `GET /api/v1/device-reservation/{reservation_id}` and `GET /api/v1/interface/{reservation_id}/network` return `expires_at: null` and `expires_in: null` for unlimited reservations.

## [2.5.0] - 2026-04-16

### 🔧 Maintenance

- **Removed `default_timeout` config parameter** – Reservation duration is now always required explicitly via `duration_seconds` in the API. The legacy fallback in `NetworkManager.start_network()` was dead code (never triggered by the reservation flow) and has been removed.
- **Updated documentation** – README rewritten: concise structure, current config format, API usage example, Makefile-based workflow. Removed outdated `net_id` references, duplicate sections, and obsolete curl examples.

### 🐛 Bug Fixes

- **Fixed `TypeError` on unlimited reservations** – `_expires_at_timestamp` `None` comparisons in `NetworkManager` (get_status, enable/disable internet) now handle unlimited reservations correctly.
- **Fixed missing ANSI colors in `start-service.sh`** – URL lines were using `echo` without `-e`, printing raw escape codes instead of colored output.

### ✨ Features

- **Swagger UI & ReDoc links in toolbar** – Two icon buttons (`description`, `menu_book`) added to the frontend toolbar, separated from the auth lock button by a vertical divider. Each opens the corresponding API docs in a new tab.
- **Reservation policy API** – `GET /api/v1/status` now returns a `reservation_policy` object with `min_seconds`, `max_seconds`, and `allow_unlimited`, replacing the flat `allow_unlimited_reservation` field.
- **Dynamic reservation dialog** – The frontend fetches reservation policy from the API and uses server-configured min/max for validation. Duration is shown as a live `00h 00m 00s` badge in the dialog title bar, with a human-readable valid range hint below the input.

---

## [2.4.0] - 2026-04-16

### ✨ Features

- **Token-based login dialog** – The frontend no longer stores the auth token in environment files. On first load, a dialog prompts the user to enter a Bearer token, which is saved in `localStorage` and used for all API requests. A lock icon button in the toolbar allows changing the token at any time.

### 🔒 Security

- **Removed hardcoded `authToken`** from both `environment.ts` and `environment.prod.ts`. The token is now provided at runtime by the user, eliminating secrets from the source code.
- **Removed hardcoded IP** from the development environment file. Both environments now use the relative path `/api/v1`.
- **401 auto-detection** – An HTTP interceptor detects unauthorized responses, clears the invalid token, and re-prompts the user immediately.

### 🔧 Maintenance

- **New `AuthService`** – Centralized service for token management via `localStorage`.
- **New `TokenDialogComponent`** – Angular Material dialog for entering/updating the auth token.

---

## [2.3.0] - 2026-04-01

### 🐛 Bug Fixes

- **Auto-stop network on reservation release** – Releasing a reservation (single or bulk delete) now automatically stops any active WiFi network on the associated device. Previously, the network remained running until its expiry timeout, leaving orphaned AP/DHCP/NAT resources.

---

## [2.2.0] - 2026-03-31

### ✨ Features

- **Unlimited reservations** – When `allow_unlimited_reservation: true` in config, users can create reservations with no expiry by sending `duration_seconds: 0`. The reservation stays active until explicitly released.
- **Duration validation** – `POST /device-reservation` now validates `duration_seconds` against `min_timeout` and `max_timeout` from config (previously only enforced client-side)
- **Hardcoded `min_timeout` floor** – `min_timeout` can never be set below 10 seconds in config

### 🔧 Maintenance

- **Frontend unlimited UX** – Reservation dialog shows an "Unlimited" checkbox when allowed. Owned cards show "∞ Unlimited" instead of countdown; occupied cards show "Occupied — No expiry"

### 🔌 API Changes

#### `POST /api/v1/device-reservation`

- `duration_seconds: 0` creates an unlimited reservation (requires `allow_unlimited_reservation: true` in config)
- `duration_seconds` is now validated server-side against `min_timeout` / `max_timeout`; returns 422 if out of bounds
- Response fields `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### `GET /api/v1/device-reservation/{reservation_id}`

- Response fields `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### `GET /api/v1/status`

- New field: `allow_unlimited_reservation` (boolean) — reflects the server config
- Each network entry now includes `reserved` (boolean) — distinguishes "available" from "occupied unlimited" when `reservation_remaining_seconds` is `null`
- `reservation_remaining_seconds` is `null` for unlimited reservations (previously only `null` when not reserved)

#### `GET /api/v1/interface/{reservation_id}/network`

- `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### New config parameter

```yaml
# Set to true to allow unlimited reservations (duration_seconds: 0)
allow_unlimited_reservation: false
```

---

## [2.1.0] - 2026-03-28

### 🔧 Maintenance

- **Reorganized `scripts/` folder** – Removed 10 obsolete API helper scripts; split `restart-service.sh` into `scripts/stop-service.sh` and `scripts/start-service.sh`
- **Makefile service targets** – Added `make stop`, `make start`, `make restart`; removed duplicate `build-release`/`run-release` targets
- **Test suite decoupled from host config** – Tests now use a dedicated `tests/test.config.yaml` so they pass regardless of the host `config.yaml`

### ✨ Features

- **Available WiFi Channels API**
  - New endpoint to query all WiFi channels supported by a reserved device, split by band
- **Channel cache warm-up at startup** – WiFi channel info is pre-fetched in a background thread so the first API call is served from cache
- **Centralized channel validation** – Static and hardware-aware channel validation, with 5 GHz channels 169/173/177 now recognized. Network creation rejects unsupported or disabled channels with a clear 422 error
- **Configurable country code** – WiFi regulatory domain (`country_code`) moved from hardcoded value to `config.yaml` (default: `IT`)
- **Regulatory domain enforcement at startup** – `iw reg set` is called with the configured country code before cache warm-up, ensuring the kernel reports correct channel flags. Channels marked `No IR` (no initiate radiation) are now detected and treated as disabled

### 🔌 API Changes

#### New endpoint

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/interface/{reservation_id}/network/available-channels` | List supported WiFi channels for the reserved device |

Response body:
```json
{
  "interface": "wlxbc071dc527d6",
  "channels_24ghz": [
    { "channel": 1, "frequency_mhz": 2412, "max_power_dbm": 20.0, "disabled": false },
    { "channel": 14, "frequency_mhz": 2484, "max_power_dbm": 0.0, "disabled": true }
  ],
  "channels_5ghz": [
    { "channel": 36, "frequency_mhz": 5180, "max_power_dbm": 23.0, "disabled": false },
    { "channel": 169, "frequency_mhz": 5845, "max_power_dbm": 0.0, "disabled": true }
  ]
}
```

Each channel includes frequency in MHz, maximum TX power in dBm, and a disabled flag. Disabled channels (blocked by regulatory domain) are reported with `max_power_dbm = 0.0` by convention. Channel data is resolved from `iw phy` on first request and cached in memory for subsequent calls.

---

## [2.0.0] - 2026-03-27 - ⚠️ Unreleased version ⚠️

Major release introducing a reservation-based device lifecycle. Users must now acquire a time-limited reservation token before performing any network operation. The frontend has been redesigned around this workflow, showing all physical interfaces as cards with real-time status and allowing multiple simultaneous reservations.

### ⚠️ Breaking Changes

- **`net_id` removed from configuration.** Each device is now identified internally by its physical interface name (`device_id`). A new required field `display_name` replaces the old `net_id` label.
  ```yaml
  # Before
  networks:
    - net_id: "ap-01"
      interface: "wlxbc071dc527d6"

  # After
  networks:
    - interface: "wlxbc071dc527d6"
      display_name: "bench-antenna-1"
  ```
- **All network, internet, and txpower routes now use `{reservation_id}` as path parameter** instead of the old `{net_id}`. A valid reservation token is required for every operation.
- **The `timeout` parameter on network creation has been removed.** Reservation `duration_seconds` is the only lifetime source; WiFi auto-stops when the reservation expires.

### ✨ Features

- **Device Reservation System**
  - Reservation-first workflow: a time-limited token must be acquired before any network operation
  - Devices are allocated automatically — the API assigns the first available interface
  - Token is an 8-character hex string, cryptographically generated
  - At reservation expiry the network is stopped, the device is released, and the token is invalidated
  - When all devices are occupied, the API returns the estimated wait time until the next device becomes free

- **Frontend Reservation UX**
  - All physical interfaces are displayed as cards, polled every 10 seconds from the status API
  - Each card shows one of three states: owned (with full WiFi controls), occupied by another user (with live countdown), or available
  - Users can hold multiple reservations simultaneously; cards appear with a countdown progress bar and `hh:mm:ss` label
  - "Release All" button with destructive-action confirmation dialog to free all owned devices at once
  - Reservations persist to `localStorage` and are validated on page reload — surviving browser refresh
  - When capacity is full, an inline error shows a live countdown to the next available slot

- **Shared Installation State Contract**
  - Installer stages now share a persistent state contract, propagated across precondition checks, install stages, and post-install tests

### 🔌 API Changes

#### New endpoints — Reservation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/device-reservation` | Reserve the first available device. Body: `{ "duration_seconds": <int> }`. Returns `reservation_id`, `display_name`, `interface`, `expires_at`, `expires_in`. |
| `GET` | `/api/v1/device-reservation/{reservation_id}` | Query reservation status. Returns same fields as create. `404` if expired or unknown. |
| `DELETE` | `/api/v1/device-reservation/{reservation_id}` | Release a single reservation. `404` if not found. |
| `DELETE` | `/api/v1/device-reservation` | Release all active reservations at once. Returns `{ "released": <count> }`. |

When all devices are reserved, `POST` returns `409 Conflict`:
```json
{
  "detail": {
    "error": "No device available",
    "next_available_at": "2026-03-27 14:30:00",
    "next_available_in": 120
  }
}
```

#### Changed endpoints

- **`POST /api/v1/network/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`; `timeout` field removed from request body.
- **`GET /api/v1/network/{reservation_id}`** — always returns `expires_at` (ISO 8601 UTC) and `expires_in` (seconds), even when WiFi is off.
- **`DELETE /api/v1/network/{reservation_id}`** — stops the network but does not release the reservation.
- **`POST|DELETE /api/v1/internet/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`.
- **`GET|PUT /api/v1/txpower/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`.
- **`GET /api/v1/status`** — each device now includes `reservation_remaining_seconds` (integer or `null` when unreserved) and `display_name`.
- **`GET /api/v1/debug`** — each network entry includes `reservation_id` and `display_name`.

### 📝 Documentation

- Configuration example updated: `interface` + `display_name`, no `net_id`
- Networking docs: "Secure Timeout Configuration" section replaced with "Reservation-Driven Timeout"
- Developer guide updated with new config format and Makefile workflow

---

## [1.5.0] - 2026-03-24

### 📚 Documentation

- **Consolidated Troubleshooting Documentation**
  - Merged troubleshooting content from `networking.md` into centralized `docs/troubleshooting.md`
  - Removed redundant troubleshooting sections from `networking.md`
  - Added disclaimer about interface name alignment for diagnostics scripts
- **Removed Obsolete Installation Guide**
  - Deleted `docs/installation-guide.md` (content migrated to README.md and troubleshooting.md)
  - Updated all documentation references to point to current resources
- **Simplified API Documentation**
  - Removed hardcoded API endpoint examples from `docs/swagger.md`
  - Directed users to Swagger UI at `http://localhost:8080/docs` as single source of truth
- **Updated Development Guide**
  - `docs/readme-dev.md` now prioritizes Makefile targets over manual commands
  - Added `make venv` and `make test-local*` examples
  - Removed references to old setup patterns
  - Added `make type-check` to development workflow documentation

### 🔧 Tool Integration

- **Added Ruff Linter to Build System**
  - Integrated `ruff>=0.3.0` as primary code quality tool
  - Added `make lint` target to check code style
  - Added `make lint-fix` target to auto-fix code style issues
  - Updated development workflow to include linting step in pre-commit checklist
  - Documented ruff usage in `docs/readme-dev.md`
- **Added MyPy Static Type Checking**
  - Integrated `mypy>=1.8.0` for static type validation
  - Added `make type-check` target to run type checker
  - Type checking included in pre-commit guidelines (warnings expected during type hint migration)
  - Updated Makefile and documentation to reflect type-checking workflow

### 🧹 Code Quality

- **Applied Ruff Fixes Across Codebase**
  - Removed 14 unused imports: `AppConfig`, `tempfile` (3x), `pytest`, `MagicMock`, `Body`, `Optional`, `datetime`, `execute_iptables`
  - Removed unused exception variables in except clauses
  - Fixed 3 f-strings without placeholders (unnecessary `f` prefix)
  - Files improved: 12 files across tests/, wilab/api/routes/, wilab/network/, wilab/wifi/
  - All 151 tests pass successfully

---

## [1.4.0] - 2026-03-23

### 🔒 Security

- **Fixed unauthenticated access to `/api/v1/debug` endpoint**
  - `GET /api/v1/debug` now requires a valid Bearer token, consistent with all other protected endpoints
  - Previously, the endpoint exposed full system debug information (services, interfaces, diagnostics) without authentication

### 🧪 Testing

- Added `test_debug_requires_auth`: verifies `GET /api/v1/debug` returns `401` without a token
- Added `test_debug_with_invalid_token`: verifies `GET /api/v1/debug` returns `401` with an invalid token
- Updated existing `TestDebugEndpoint` tests to supply the valid Bearer token header

### 🔧 Refactoring & Infrastructure

- **Network Lifecycle API Response Simplification**
  - `POST /api/v1/interface/{net_id}/network` now returns a compact success payload: `{"detail": "Network {net_id} created successfully"}`
  - `DELETE /api/v1/interface/{net_id}/network` now returns a consistent payload: `{"detail": "Network {net_id} stopped successfully"}`
  - `POST /api/v1/interface/{net_id}/internet/enable` now returns: `{"detail": "Network {net_id} internet enabled successfully"}`
  - `POST /api/v1/interface/{net_id}/internet/disable` now returns: `{"detail": "Network {net_id} internet disabled successfully"}`
  - Full network details are now retrieved only via `GET /api/v1/interface/{net_id}/network`
- **Validation Error Payload Simplification**
  - Request validation errors are exposed with a simple string payload: `{"detail": "..."}`
  - Removed dependency on verbose Pydantic-style validation lists for API clients
- **DELETE Network State Semantics**
  - `DELETE /api/v1/interface/{net_id}/network` now enforces proper state transitions:
    - `404` for unknown `net_id`
    - `409` when the network is already inactive

### 🧪 Testing

- Added coverage for simplified POST network success response payload
- Added coverage that `422` validation responses expose a string `detail`
- Added deterministic coverage for DELETE network behavior:
  - stop active network succeeds (`200`)
  - stop inactive network returns `409`
  - stop unknown network returns `404`
- Added coverage for internet enable/disable success cases:
  - `test_enable_internet_success`: validates POST returns detail message with net_id
  - `test_disable_internet_success`: validates POST returns detail message with net_id
- Hardened internet-control tests by isolating manager state per test

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

