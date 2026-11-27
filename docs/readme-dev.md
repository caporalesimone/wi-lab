# Wi-Lab Development Guide

This guide explains how to set up a development environment and contribute to Wi-Lab.

---

## Prerequisites

### System Requirements

- **OS:** Ubuntu 25+ for the installer and the service (`install.sh` checks it); the unit tests run on any Linux
- **Python:** 3.10+ (CI runs 3.12)
- **RAM:** 2GB minimum (4GB recommended)
- **Disk:** 2GB free space

### Required System Packages

```bash
# WiFi and network management tools
sudo apt-get install -y hostapd dnsmasq iptables iw

# Development tools
sudo apt-get install -y git build-essential python3-dev python3-pip python3-venv
```

---

## Development Environment Setup

### 1. Clone Repository

```bash
git clone https://github.com/caporalesimone/wi-lab
cd wi-lab
```

### 2. Create Local Dev Environment

```bash
# Create local virtual environment and runtime dependencies
make venv

# Install development/test dependencies (required once)
.venv/bin/pip install -r requirements-dev.txt

# Activate it (optional but recommended for manual tools)
source .venv/bin/activate
```

### 3. Verify Tooling

```bash
# Show all development targets
make help

# Quick validation that test tooling is ready
make test-local-quick
```

**What's included in development dependencies:**
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-asyncio` - Async test support
- `httpx` - HTTP client for the API tests and the e2e tests
- `ruff` - Fast Python linter and code formatter (replaces flake8, isort, black)
- `mypy` - Static type checker for Python

### 4. Create Local Configuration

```bash
# Create and edit your local configuration (read from ./config.yaml, or from $CONFIG_PATH)
cp config.example.yaml config.yaml
nano config.yaml
```

**Example config:**
```yaml
auth_token: "dev-token-12345"
api_port: 8080

dhcp_base_network: "192.168.120.0/24"
upstream_interface: "auto"
dns_server: "192.168.10.1"
internet_enabled_by_default: true

antennas:  # Optional: names and DFS choice; interfaces are discovered automatically
  - interface: "wlx782051245264"
    display_name: "bench-antenna-1"
    show_dfs_channels: false
```

---

## Running Wi-Lab Locally

### Development Server

```bash
# Make sure local environment exists
make venv
source .venv/bin/activate

# Start the application with your preferred entry point
# (for example, your standard run command or ASGI server)
python main.py

# Example with hot reload (the app is built by the create_app factory)
uvicorn wilab.api:create_app --factory --reload --host 0.0.0.0 --port 8080
```

### Accessing the API

Once running:
- **API Docs:** `http://localhost:8080/docs`
- **Alternative Docs:** `http://localhost:8080/redoc`

See [swagger.md](swagger.md) for complete API testing guide.

---

## Testing

### Running Tests

For complete testing documentation, see [unit-testing.md](unit-testing.md).

Preferred commands (via Makefile):

```bash
# Run full test suite
make test-local

# Run quick test suite
make test-local-quick

# Run with coverage report
make test-local-cov
```

End-to-end tests (`tests/e2e-tests/`) run on the Wi-Lab machine against the running service and combine
API calls with server actions. They are skipped unless enabled; see [e2e-testing.md](e2e-testing.md).

```bash
make test-e2e        # API + server checks, no USB unplug
make test-e2e-usb    # also simulated USB unplugs (WD-4/WD-5)
```

Advanced (targeted tests when needed):

```bash
# Run specific test file
.venv/bin/pytest tests/unit-tests/test_api.py -v

# Run a specific test node
.venv/bin/pytest tests/unit-tests/test_api.py::TestNetworkCreateEndpoint::test_start_network_invalid_reservation -v
```

### Using Project Automation Targets

Automation targets provide convenient shortcuts for development tasks:

```bash
# One-time local bootstrap
make venv
.venv/bin/pip install -r requirements-dev.txt

# Run tests locally
make test-local

# Quick test run (less output)
make test-local-quick

# Generate coverage report
make test-local-cov

# Check code style with ruff
make lint

# Fix code style issues automatically
make lint-fix

# Type check with mypy
make type-check

# Clean up (remove venv)
make clean-venv
```

Use `make help` to view the complete and always-updated list of available targets.
See [Makefile](../Makefile)

---

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/my-new-feature
```

### 2. Make Changes

Work within the main backend modules:
- API layer
- WiFi and network control layer
- Configuration and validation layer
- Domain models and shared utilities

### 3. Check Code Style

```bash
# Check linting issues with ruff
make lint

# Auto-fix style issues
make lint-fix
```

### 4. Type Check Your Changes

```bash
# Run mypy static type checker
make type-check
```

This checks for type inconsistencies. Note: Wi-Lab is incrementally adding type hints. Some warnings are expected.

### 5. Test Your Changes

```bash
# Run tests (preferred)
make test-local
make test-local-cov

# Optional targeted run during development
.venv/bin/pytest tests/unit-tests/test_api.py -v
```

### 6. Verify Manually

```bash
# Run the service
python main.py

# Validate and test from Swagger UI
# Open: http://localhost:8080/docs
```

### 7. Commit and Push

```bash
git add -A
git commit -m "Add my-new-feature"
git push origin feature/my-new-feature
```

### 8. Create Pull Request

Push branch and create PR on GitHub for review.

---

## Code Structure

The project follows clean separation of concerns:

- **Configuration Layer** - Loads and validates runtime settings
- **Models Layer** - Request/response schemas and domain data types
- **API Layer** - HTTP routes, auth checks, and handlers
- **Network Layer** - WiFi, DHCP, NAT, and isolation orchestration
- **System Commands Layer** - Controlled wrappers around host networking commands

### Design Principles

**Separation of Concerns:** Each module has a single, well-defined responsibility  
**No Monolithic Files:** Code split across focused modules  
**Layered Architecture:** API → Service → System Commands  
**Type Hints:** All function signatures and class attributes have type annotations  
**Error Handling:** Clear error messages and appropriate HTTP status codes  

The modules, threads and locks are described in [architecture.md](architecture.md).

---

## Setup State Contract (Phase 1)

The installer now initializes a shared machine-readable state file for all setup
stages.

### File Path

- Default: `/tmp/wilab-setup-state.env`
- Override: set `WILAB_SETUP_STATE_FILE` before running `install.sh`

### Format

- Bash `KEY=VALUE` lines (sourceable)
- Keys must match: `^[A-Z][A-Z0-9_]*$`
- Values are shell-escaped before write

### Namespace Convention

- `SYSTEM_*`
- `DOCKER_*`
- `CONFIG_*`
- `TOOLS_*`
- `NETWORK_*`
- `INSTALL_*`
- `TEST_*`

### Available Helpers

Defined in [install/common.sh](../install/common.sh):

- `state_init`
- `state_set KEY VALUE`
- `state_get KEY`
- `state_has KEY`

### Current Bootstrap Behavior

At installer start, [install.sh](../install.sh) initializes the state file and sets:

- `INSTALL_RUN_STARTED=1`
- `INSTALL_RUN_STARTED_AT=<UTC ISO timestamp>`

The setup stages under `install/` then write their own keys (for example
`SYSTEM_ROOT_OK`, `DOCKER_PRESENT`, `DOCKER_DAEMON_OK`).

---

## Debugging

### Logging rules

Logging is configured only in [wilab/log.py](../wilab/log.py) (`log.setup()`, called by
`main.py`); modules only do `logger = logging.getLogger(__name__)`. The journal is how the
service's health is read, so the levels follow three rules, checked by
`tests/unit-tests/test_logging_rules.py`:

1. **ERROR means someone must act.** Only a final outcome that the service cannot repair by
   itself: a bug (a `500`), a cleanup that kept failing after its background retries, a
   start that cannot be cancelled. Not an ERROR:
   - a failed attempt that is retried (an AP start attempt, a rollback or a cleanup the
     background repeats): **WARNING**;
   - a check that answers "no", a `503` that tells the client to repeat: **WARNING**;
   - what a user asked for (a cancel, a release, `device_busy`): **INFO**.
2. **A message that repeats for the same cause is written at most once a minute**: use
   `log.every(logger, level, key, message, *args, interval=...)`, which adds how many it held back.
3. **Never format the message yourself**: `logger.info("... %s", value)`, not an f-string
   (ruff `G004`; `make lint` checks it).

Every record carries the antenna and the reservation of the operation running when there
is one (`[ant=wlx... res=1a2b3c4d]`): the API middleware sets them for requests on
`/reservations/{id}`, the create thread and the watchdog bind their own. To follow one
reservation: `journalctl -u wi-lab | grep res=1a2b3c4d`. In a new background thread, call
`log.bind(antenna=...)` first, or wrap the work in `with log.context(antenna=..., reservation=...)`.

Under systemd each line starts with its syslog priority, so `journalctl -p` works:

```bash
sudo journalctl -u wi-lab -p err --since today      # what needs someone
sudo journalctl -u wi-lab -p warning --since today  # also recovered failures
```

### Enable Verbose Logging

```bash
# Set Python verbosity
PYTHONVERBOSE=2 python main.py

# Or, for a quick local run, raise the level of the one configuration
python -c "import logging; from wilab import log; log.setup(logging.DEBUG); import runpy; runpy.run_path('main.py', run_name='__main__')"
```

### Use Python Debugger

```python
# Add breakpoint in code
def my_function():
    result = something()
    breakpoint()  # Stops here
    return result

# Run with pytest
.venv/bin/pytest tests/unit-tests/test_file.py -v -s
```

### Check Service Logs

```bash
# If running via systemd
sudo journalctl -u wi-lab.service -f

# What needs someone (ERROR and above, by journal priority)
sudo journalctl -u wi-lab.service -p err
```

---

## Documentation

When adding new features, update documentation:

- **API changes:** Keep route-level descriptions and examples aligned with behavior
- **Configuration:** Document new or changed runtime settings
- **User guide:** Update relevant user-facing guides
- **Development:** Update this guide if the workflow changes

Keep documentation focused on workflows and behavior rather than internal file paths.

---

## Contributing Guidelines

### Before Committing

- ✅ Code style passes: `make lint` (or auto-fix with `make lint-fix`)
- ✅ Type checking passes: `make type-check` (warnings expected during transition)
- ✅ All tests pass: `make test-local`
- ✅ Coverage maintained: `make test-local-cov`
- ✅ Optional targeted validation: `.venv/bin/pytest tests/unit-tests/test_api.py -v`
- ✅ Documentation updated: Add comments/update docs if needed

### Commit Messages

Use clear, descriptive commit messages:
```
Feature: Add TX power control API endpoint
Fix: Resolve subnet conflict on network creation
Docs: Update installation guide
Test: Add tests for network expiry logic
```

### Pull Request Description

Include:
- What problem does it solve?
- How does it solve it?
- What tests were added?
- Any breaking changes?

---

## Additional Resources

- **FastAPI:** https://fastapi.tiangolo.com/
- **pytest:** https://docs.pytest.org/
- **Pydantic:** https://docs.pydantic.dev/
- **hostapd:** https://w1.fi/hostapd/
- **iw:** https://wireless.wiki.kernel.org/en/users/Documentation/iw

---

## Documentation Areas

- Networking and connectivity
- API testing and validation
- Unit and integration testing
- Troubleshooting and diagnostics

---

**Development environment ready!**

Start developing:
```bash
make venv
source .venv/bin/activate
python main.py
```

Then open your API docs endpoint in the browser (for example: `http://localhost:8080/docs`).
