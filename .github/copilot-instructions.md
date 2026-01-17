# Wi-Lab: WiFi Access Point Test Bench

## Project Overview
Wi-Lab is a Python-based REST API system for managing multiple WiFi interfaces in Access Point (AP) mode. It provides programmatic control over WiFi network creation, configuration, and lifecycle management for testing purposes.

**Key Purpose**: Control arbitrary number of WiFi interfaces, dynamically creating/destroying AP networks with specific configurations via REST API.

## System Architecture

### Core Components
1. **Web API Server** (REST API with token authentication, Swagger UI on port 8080)
2. **Configuration Manager** (loads YAML config file defining interfaces and token)
3. **WiFi Interface Controller** (manages hostapd for AP mode)
4. **Network Lifecycle Manager** (handles timeouts and automatic shutdown)
5. **Network Manager** (DHCP server, NAT/Internet forwarding, network isolation)
6. **Systemd Service** (manages application lifecycle and autostart)

### Data Flow
- Config YAML → defines available WiFi interfaces + auth token
- API request (with token) → WiFi Controller → hostapd/dnsmasq/iptables → interface in AP mode + DHCP + NAT
- Automatic timeout → Network Lifecycle Manager → shuts down AP and cleans up network rules
- Internet control API → iptables rules → enable/disable NAT forwarding per network

## Development Environment
- **Target OS**: Ubuntu 25.04 (production deployment)
- **Development**: Can use WSL/Ubuntu on Windows
- **Language**: Python 3.x
- **API Port**: 8080 (with Swagger UI at `/docs`)
- **WiFi Stack**: `hostapd` for AP mode, `iw`/`ip` commands
- **Networking**: `dnsmasq` (DHCP server), `iptables` (NAT/firewall)
- **Deployment**: Python virtual environment with systemd service

## Configuration File Structure
The config file (`config.yaml`) must define:
- `auth_token`: Single token for API authentication
- `api_port`: API server port (default 8080)
- `default_timeout`: Max time (seconds) an AP network stays active
- `max_timeout` / `min_timeout`: Bounds for API-provided overrides
- `dhcp_base_network`: Base network for DHCP (e.g., "192.168.10.0/24")
- `upstream_interface`: "auto" for autodiscovery via default gateway, or a device name (e.g., "eth0") to override
- `dns_server`: DNS server IP address (e.g., "192.168.10.21" for local DNS)
- `internet_enabled_by_default`: Globally enable NAT by default for new networks
- `networks`: Array of WiFi networks managed by the system (each item defines the interface to use; SSID/channel/password/encryption/band/hidden are provided via API at runtime)
  - Each net_id must match regex ^[a-z0-9-]{1,16}$ and be stable across restarts

Example:
```yaml
auth_token: "secret-token-12345"
api_port: 8080
default_timeout: 3600
max_timeout: 86400
min_timeout: 60
dhcp_base_network: "192.168.10.0/24"
upstream_interface: "auto"      # or "eth0" to override
dns_server: "192.168.10.21"         # DNS IP address
internet_enabled_by_default: true

networks:
  - net_id: "ap-01"             # stable identifier used in APIs
    interface: "wlx782051245264" # find via `ip addr`
```

## REST API Endpoints

### Per-Interface Operations
For each network (e.g., `/api/v1/interface/ap-01/`):

- **POST `/network`** - Create/start AP network
  - Parameters: `ssid`, `channel`, `password` (optional), `encryption` (open/wpa2/wpa3/wpa2-wpa3), `band` (2.4ghz/5ghz), `hidden` (bool), `tx_power_level` (1-4), `timeout` (optional override, 60-86400 seconds), `internet_enabled` (bool, default true)
  - Returns: NetworkStatus with net_id, interface, DHCP subnet, expiration time
  
- **DELETE `/network`** - Stop AP network on interface

- **GET `/network`** - Get full network configuration and status (includes password)

- **GET `/status`** - Get minimal network status (net_id, interface, active flag only)

- **GET `/summary`** - Get detailed summary with DHCP info and connected clients

- **POST `/internet/enable`** - Enable Internet access for connected clients

- **POST `/internet/disable`** - Disable Internet access (clients isolated)

- **GET `/clients`** - List connected WiFi clients with MAC and IP addresses

- **GET `/txpower`** - Get current TX power details and hardware capabilities
  - Returns: current_level (1-4), current_dbm, reported_dbm, hardware_warnings

- **POST `/txpower`** - Set transmit power level for active network
  - Parameters: `level` (1-4, where 4 is maximum)
  - Returns: updated TxPowerInfo with applied level

### Global Operations
- **GET `/api/v1/interfaces`** - List all managed interfaces
- **GET `/api/v1/health`** - Comprehensive health check (dnsmasq, iptables, upstream connectivity)
- **GET `/api/v1/status/services`** - Detailed service status (dnsmasq, hostapd, iptables)
- **POST `/api/v1/shutdown-all`** - Stop all active networks

### Authentication
- All requests require `Authorization: Bearer <token>` header
- Token validated against config file

### API Documentation
- **Swagger UI**: Available at `http://localhost:8080/docs`
- **ReDoc**: Available at `http://localhost:8080/redoc`
- FastAPI automatically generates OpenAPI schema

## Code Conventions

### Project Structure
**CRITICAL**: Code must be organized in multiple files with clear separation of concerns. Never create a single monolithic file.

```

### Net ID Guidelines
- Keep `net_id` short and stable (e.g., `ap-01`, `lab-5`).
- Allowed characters: lowercase letters, digits, and dashes.
- Regex rule: ^[a-z0-9-]{1,16}$ (reject invalid identifiers early).
- Define `net_id` in `config.yaml` to keep identity consistent across restarts.
- Map DHCP subnets sequentially by `networks` array order to preserve predictability.

### Config Validation Behavior
- `wilab/config.py` validates the YAML structure and values.
- On validation failure, the service terminates with a descriptive error pointing to the failing field/path.
wi-lab/
├── config.yaml              # Configuration file
├── setup.sh                 # Automated installation script
├── requirements.txt         # Python dependencies
├── wilab/
│   ├── __init__.py          # Package initialization
│   ├── api/                 # REST API endpoints
│   │   ├── __init__.py      # FastAPI app creation and setup
│   │   ├── routes.py        # API route definitions (all endpoints)
│   │   ├── auth.py          # Token authentication middleware
│   │   └── dependencies.py  # Dependency injection for routes
│   ├── wifi/                # WiFi control layer
│   │   ├── __init__.py
│   │   ├── interface.py     # WiFi interface abstraction class
│   │   ├── hostapd.py       # hostapd config generation and process management
│   │   └── manager.py       # Network lifecycle and timeout management
│   ├── network/             # Network management
│   │   ├── __init__.py
│   │   ├── dhcp.py          # DHCP server (dnsmasq) config and management
│   │   ├── nat.py           # NAT/iptables rules for Internet access
│   │   ├── isolation.py     # Network isolation between APs (iptables)
│   │   └── commands.py      # Linux shell command wrappers (ip, iw, etc.)
│   ├── config.py            # YAML config file parsing and validation
│   └── models.py            # Pydantic data models (NetworkConfig, etc.)
├── tests/
│   ├── test_config.py       # Config parsing tests
│   ├── test_api.py          # API endpoint tests
│   └── test_wifi.py         # WiFi operations tests
├── systemd/
│   └── wi-lab.service        # Systemd service file
└── main.py                  # Application entry point (minimal, just startup)
```

### File Ownership & Responsibilities

**main.py**: Application entry point only
- Parse CLI arguments
- Load configuration
- Initialize and start FastAPI server
- Setup signal handlers
- ~20-30 lines maximum

**wilab/config.py**: Configuration management
- Load and parse YAML file
- Validate configuration structure
- Provide Config dataclass/model
- Default values handling

**wilab/models.py**: Data models
- Pydantic models for API requests/responses
- NetworkConfig, InterfaceStatus, ClientInfo classes
- Validation logic and type definitions

**wilab/api/routes.py**: API endpoints
- All FastAPI route handlers
- Request validation and response formatting
- Call appropriate service layer functions
- No business logic, only coordination

**wilab/api/auth.py**: Authentication
- Token validation function
- FastAPI dependency for authentication
- Security utilities

**wilab/wifi/interface.py**: WiFi interface abstraction
- WiFiInterface class managing single interface
- State tracking (active/inactive)
- Interface validation and availability checks

**wilab/wifi/hostapd.py**: hostapd management
- Generate hostapd.conf from parameters
- Start/stop hostapd process
- Process monitoring
- Temp file management

**wilab/wifi/manager.py**: Network lifecycle
- Timeout tracking and enforcement
- Automatic network shutdown
- Background tasks coordination

**wilab/network/dhcp.py**: DHCP server
- Generate dnsmasq config for each interface
- Subnet allocation logic
- Start/stop dnsmasq per interface

**wilab/network/nat.py**: NAT and Internet forwarding
- Enable/disable NAT with iptables
- IP forwarding sysctl management
- Interface-specific forwarding rules

**wilab/network/isolation.py**: Network isolation
- iptables rules to block inter-network traffic
- Subnet isolation configuration

**wilab/network/commands.py**: Linux command wrappers
- Safe subprocess execution
- Command builders for: ip, iw, iptables, sysctl
- Output parsing and error handling
- No direct subprocess.run() calls outside this file

### Python Patterns

**Code Organization** (CRITICAL):
- **Separation of concerns**: Each file has ONE clear responsibility
- **No monolithic files**: Split functionality across multiple focused modules
- **Layered architecture**: API → Service/Manager → System Commands
- **Single Responsibility**: Each class/function does one thing well
- **Module size**: Keep files under 200-300 lines; split if larger

**Type hints**: Use for all function signatures and class attributes
```python
def create_network(interface: str, config: NetworkConfig) -> NetworkStatus:
    ...
```

**Async/await**: Use for API handlers (FastAPI/aiohttp) and concurrent interface management
```python
@router.post("/interface/{interface}/network")
async def start_network(interface: str, config: NetworkConfig) -> dict:
    ...
```

**Error handling**: Catch system command failures, log errors, return appropriate HTTP status codes
```python
try:
    result = await execute_command(["hostapd", config_path])
except CommandError as e:
    logger.error(f"hostapd failed: {e}")
    raise HTTPException(status_code=500, detail=str(e))
```

**Validation**: Use Pydantic models for API request/response validation

**State management**: Track active networks per interface, prevent conflicts

**Command execution**: All subprocess calls go through `network/commands.py`
```python
# GOOD: Use wrapper from commands.py
from wilab.network.commands import execute_iptables
await execute_iptables(["-t", "nat", "-A", "POSTROUTING", "-j", "MASQUERADE"])

# BAD: Direct subprocess calls scattered in code
import subprocess
subprocess.run(["iptables", ...])
```

### WiFi Control Implementation
- Use `subprocess` to call `hostapd`, `iw`, `ip` commands
- Or use NetworkManager D-Bus API for higher-level control
- Generate `hostapd.conf` dynamically based on API parameters
- Clean up temporary configs on shutdown
- **TX Power Control:** Uses `iw dev <iface> set txpower` with fixed mBm values
  - Level 1: ~5 dBm (minimum)
  - Level 2: ~10 dBm (low)
  - Level 3: ~15 dBm (medium)
  - Level 4: ~20 dBm (maximum, default)
  - Actual dBm values depend on hardware capabilities

### Network Management Implementation
- **DHCP**: Use `dnsmasq` with separate config per interface
  - Each interface gets sequential subnet: 192.168.10.0/24, 192.168.11.0/24, etc.
  - Range: .10 to .250, gateway at .1
- **NAT/Internet**: Use `iptables` for forwarding rules
  - Enable: `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE`
  - Disable: Remove forwarding rules for specific interface
- **Network Isolation**: Use `iptables` to block traffic between WiFi subnets
  - Drop packets from 192.168.10.0/24 to 192.168.11.0/24 and vice versa
- **IP Forwarding**: Enable via `sysctl net.ipv4.ip_forward=1`

## Code Anti-Patterns (AVOID)

**DO NOT**:
- ❌ Create a single `wilab.py` or `app.py` with all code (1000+ lines)
- ❌ Mix API routes with business logic in same file
- ❌ Put subprocess calls directly in API handlers
- ❌ Duplicate command execution code across files
- ❌ Mix configuration parsing with application logic
- ❌ Create "utils.py" or "helpers.py" with unrelated functions

**DO**:
- ✅ Separate API layer from WiFi management layer
- ✅ Centralize all shell commands in `network/commands.py`
- ✅ Keep models in dedicated `models.py`
- ✅ One config loader in `config.py`
- ✅ Each module focuses on single domain (wifi, network, api)

## Key Technical Considerations

### Default Behavior
- **On startup**: All interfaces are down, no AP networks active
- **No persistence**: Network configurations are not saved between restarts
- **Automatic shutdown**: Each network has timeout, auto-stops when expired
- **Internet access**: Enabled by default for all new networks (configurable per-network)
- **DHCP**: Automatically started when network is created
- **Network isolation**: All WiFi networks are isolated from each other by default

### Network Parameters Mapping
- **Encryption types**: `open`, `wpa`, `wpa2`, `wpa3`, `wpa2-wpa3` → hostapd `wpa=` and `wpa_key_mgmt=`
- **Bands**: `2.4ghz` → channels 1-14, `5ghz` → channels 36-165
- **Hidden SSID**: `ignore_broadcast_ssid=1` in hostapd config
- **Open networks**: No `wpa_passphrase` in hostapd config
- **DHCP subnets**: Sequential allocation based on interface index (wlan0=.10, wlan1=.11, etc.)
- **Internet control**: Per-interface iptables rules for NAT forwarding

### Concurrency & Safety
- Prevent starting multiple networks on same interface
- Lock/semaphore per interface to serialize operations
- Validate interface exists before operations
- Timeout cleanup runs in background task per network

## Dependencies
```txt
fastapi          # REST API framework
uvicorn          # ASGI server
pydantic         # Data validation
pyyaml           # YAML config file parsing
python-daemon    # Optional: daemonization
```

System tools (Ubuntu packages):
- `hostapd` - AP mode daemon
- `dnsmasq` - DHCP server
- `iptables` - Firewall/NAT rules
- `iw`, `iproute2` - WiFi/network utilities

## Production Deployment
Wi-Lab runs as a systemd service with Python virtual environment:
- **Virtual env**: `/opt/wilab-venv` (created by setup.sh)
- **Service**: `wi-lab.service` (systemd unit file)
- **Config**: `config.yaml` in installation directory
- **Autostart**: Enabled via systemd
- **Logging**: Via journald (`journalctl -u wi-lab.service`)

Installation:
```bash
sudo bash setup.sh
```

The setup script automatically:
- Verifies/installs system dependencies
- Creates Python venv at /opt/wilab-venv
- Installs Python dependencies
- Configures systemd service
- Enables autostart on boot

## Development Workflow

### Initial Setup
1. Create virtual environment: `python3 -m venv venv`
2. Install dependencies: `pip install -r requirements.txt`
3. Create `config.yaml` with test token and available interfaces
4. Run with: `python main.py` or `uvicorn wilab.api:app`

### Testing WiFi Operations
- Test in VM or physical Ubuntu system with WiFi interfaces
- Use `iw dev` to list available interfaces
- Mock hostapd calls in unit tests, use real hardware for integration tests

### API Testing
**Using Swagger UI** (recommended):
- Navigate to `http://localhost:8080/docs`
- Click "Authorize" and enter token
- Test endpoints interactively

**Using curl**:
```bash
# Start network on wlan0 with Internet enabled
curl -X POST http://localhost:8080/api/v1/interface/wlan0/network \
  -H "Authorization: Bearer secret-token-12345" \
  -H "Content-Type: application/json" \
  -d '{"ssid": "TestAP", "channel": 6, "password": "test1234", "encryption": "wpa2", "band": "2.4ghz", "internet_enabled": true}'

# Disable Internet access
curl -X POST http://localhost:8080/api/v1/interface/wlan0/internet/disable \
  -H "Authorization: Bearer secret-token-12345"

# List connected clients
curl -X GET http://localhost:8080/api/v1/interface/wlan0/clients \
  -H "Authorization: Bearer secret-token-12345"

# Get network status
curl -X GET http://localhost:8080/api/v1/interface/wlan0/network \
  -H "Authorization: Bearer secret-token-12345"

# Stop network
curl -X DELETE http://localhost:8080/api/v1/interface/wlan0/network \
  -H "Authorization: Bearer secret-token-12345"
```

## Security Notes
- Token must be strong (use UUID or similar)
- Run API server on localhost or use firewall rules
- Consider HTTPS in production (nginx reverse proxy)
- Validate all API inputs to prevent command injection
- Log all API operations with timestamps

## Implementation Priority

**Status:** All items completed (v1.0.0) ✅

1. Config YAML parsing and validation ✅
2. Basic FastAPI server with token auth + Swagger on port 8080 ✅
3. Simple interface control (start/stop AP with hostapd) ✅
4. DHCP server integration (dnsmasq) with sequential subnet allocation ✅
5. NAT/Internet forwarding setup with iptables ✅
6. Network isolation rules between WiFi APs ✅
7. API endpoints for network creation with all parameters ✅
8. Internet enable/disable API per interface ✅
8b. Transmit power control API per interface (1-4 level scale using iw) ✅
9. Timeout/lifecycle management with background expiry thread ✅
10. Full parameter support (encryption types, bands, hidden SSID) ✅
11. Systemd service with autostart ✅
12. Error handling and logging ✅
13. Unit and integration tests (125 tests) ✅

### Future Enhancement Opportunities

**High Priority (Next Phase)**
- Channel validation per band (prevent invalid combinations)
- Client-level controls (per-MAC rate limiting, blocking)
- Graceful error recovery and orphaned rule cleanup

**Medium Priority**
- Multi-SSID/BSS support per interface
- Bandwidth limiting with traffic control (tc)
- Event webhooks or Server-Sent Events (SSE)
- Persistent network storage (Redis/SQLite option)

**Low Priority (Nice-to-Have)**
- QoS and traffic shaping
- WPA-Enterprise with RADIUS integration
- Prometheus metrics endpoint
- Python client SDK
