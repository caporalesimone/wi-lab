# Wi-Lab Unit Testing Guide

Wi-Lab uses pytest for comprehensive unit and integration testing. This document explains how to run and work with tests.

The tests live in two folders:

| Folder | What it runs | How |
|---|---|---|
| `tests/unit-tests/` | Unit and API tests with mocked hardware. Run on every change and in CI. | `make test-local` (the default `pytest` path) |
| `tests/e2e-tests/` | End-to-end tests against the running service on the Wi-Lab machine: API calls plus server actions (journal, `iw`, simulated USB unplug). | `make test-e2e`, see [e2e-testing.md](e2e-testing.md) |

This guide covers the unit tests.

---

## Quick Start

### Run All Tests

```bash
# Run all tests
pytest tests/unit-tests/ -v

# Run with coverage report
pytest tests/unit-tests/ --cov=wilab --cov-report=html --cov-report=term

# Run quick mode (less verbose)
pytest tests/unit-tests/ -q
```

### Run Specific Tests

```bash
# Run single test file
pytest tests/unit-tests/test_config.py -v

# Run single test class
pytest tests/unit-tests/test_wifi.py::TestNetworkLifecycle -v

# Run single test method
pytest tests/unit-tests/test_api.py::TestAuthentication::test_request_without_auth -v

# Run tests matching pattern
pytest tests/unit-tests/ -k "test_tx_power" -v
```

### Using the Makefile

```bash
# Run via makefile (uses virtual environment)
make test-local

# Quick test run
make test-local-quick

# Generate coverage report
make test-local-cov

# View coverage report
open htmlcov/index.html
```

---

## Test Structure

### Test Files

The unit test suite in `tests/unit-tests/` has 60 test files, plus:
- **conftest.py** - Shared fixtures and configuration (mocks every host command)
- **test.config.yaml** - Configuration loaded by the tests
- **data/** - Recorded command output (for example `iw phy info`)

The test files, by area:
- **Configuration:** `test_config.py`, `test_config_validation.py`
- **API endpoints and contract:** `test_api.py`, `test_reservation.py`, `test_async_create.py` (202, polling, cancel), `test_strict_types.py`, `test_network_sections.py`, `test_network_not_active.py`, `test_device_busy.py`, `test_error_codes.py` (every code is in `docs/error-codes.md`), `test_openapi_examples.py`, `test_export_api_docs.py`
- **Status and health:** `test_status_checks.py`, `test_status_snapshot.py`, `test_heartbeat.py`, `test_loop_supervision.py`
- **Wi-Fi, hostapd and startup:** `test_wifi.py`, `test_wifi_modes.py`, `test_models.py`, `test_channels.py`, `test_discovery.py`, `test_startup.py`, `test_precheck.py`, `test_startup_classification.py`, `test_startup_firewall.py`, `test_network_creation_recovery.py`
- **Watchdog, recovery and cleanup:** `test_watchdog.py`, `test_network_verify.py`, `test_device_loss.py`, `test_cleanup_backoff.py`, `test_runtime_cleanup.py`, `test_hostapd_ctrl.py` (control connection against a fake hostapd socket), `test_soak.py` (T-20: 14 simulated hours of random faults; `WILAB_SOAK_STEPS` for longer)
- **Network:** `test_dhcp.py`, `test_nat.py`, `test_isolation.py`, `test_host_guard.py`, `test_firewall_lock.py`, `test_captive.py`, `test_subnet.py`, `test_unmanaged.py`, `test_qos.py`, `test_qos_profile.py`
- **Commands and logging:** `test_commands.py`, `test_logging_rules.py` (ARCH-10 levels, context, no f-strings), `test_lifecycle_hygiene.py`
- **Frontend sources and CI:** `test_frontend_api_codes.py`, `test_frontend_captive_portal.py`, `test_frontend_tx_warning.py`, `test_frontend_wifi_modes.py`, `test_frontend_static.py` (T-01: the frontend route stays in its directory), `test_ci_workflow.py`

The frontend's own specs (`frontend/src/**/*.spec.ts`, today the create of `WilabApiService`) run with `make frontend-test`: compiled with the project's `tsc` and run by Node's test runner in the frontend build image, with the RxJS `TestScheduler` for the polling times; no browser, no extra dependency.

### Test Categories

**Configuration Tests:** Validate config file parsing and validation
**API Tests:** Test FastAPI endpoints and request/response handling
**WiFi Tests:** Test hostapd control and interface management
**Network Tests:** Test DHCP, NAT, and iptables rules
**Command Tests:** Test subprocess wrapper functions

---

## Setup for Development

### Prerequisites

```bash
# Python 3.10+ (CI runs 3.12)
python3 --version

# Virtual environment tools
python3 -m venv --help
```

### Create Development Environment

```bash
# Create virtual environment (the Makefile uses .venv; `make venv` does the same)
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt

# Verify pytest is installed
pytest --version
```

### Understanding requirements-dev.txt

The `requirements-dev.txt` file contains testing and development tools:

```
-r requirements.lock # Runtime dependencies, exact versions (STAB-7)
pytest              # Test framework
pytest-cov          # Coverage reporting
httpx               # HTTP client used by the FastAPI test client and the e2e tests
ruff                # Linter
mypy                # Type checker
types-PyYAML, types-jsonschema   # Type stubs for mypy
```

Install all development tools with:
```bash
pip install -r requirements-dev.txt
```

---

## Running Tests

### Basic Test Execution

```bash
# Run all tests with verbose output
pytest tests/unit-tests/ -v

# Show print statements (use print() for debugging)
pytest tests/unit-tests/ -v -s

# Stop after first failure
pytest tests/unit-tests/ -x

# Fail on first N errors
pytest tests/unit-tests/ --maxfail=3
```

### Coverage Reports

```bash
# Generate coverage report in terminal
pytest tests/unit-tests/ --cov=wilab --cov-report=term

# Generate HTML coverage report
pytest tests/unit-tests/ --cov=wilab --cov-report=html
# Open: htmlcov/index.html

# Coverage for specific module
pytest tests/unit-tests/ --cov=wilab.wifi --cov-report=term
```

### Test Markers

```bash
# Run only fast tests
pytest tests/unit-tests/ -m "not slow" -v

# Run slow tests
pytest tests/unit-tests/ -m "slow" -v

# Skip tests marked as xfail (expected failures)
pytest tests/unit-tests/ --runxfail
```

---

## Understanding Test Output

### Example Verbose Output

```bash
$ pytest tests/unit-tests/test_api.py -v

tests/unit-tests/test_api.py::TestStatusEndpoint::test_status_requires_auth PASSED       [  1%]
tests/unit-tests/test_api.py::TestStatusEndpoint::test_status PASSED                     [  2%]
tests/unit-tests/test_api.py::TestStatusEndpoint::test_status_with_every_antenna_free PASSED        [  3%]
tests/unit-tests/test_api.py::TestAuthentication::test_request_without_auth FAILED       [  4%]

FAILED tests/unit-tests/test_api.py::TestAuthentication::test_request_without_auth
```

**Format:** `path/to/test.py::TestClass::test_method STATUS [percentage]`

### Test Outcomes

| Symbol | Meaning |
|--------|---------|
| ✓ PASSED | Test passed |
| ✗ FAILED | Test failed (assertion error or exception) |
| ⊘ SKIPPED | Test skipped (decorator or condition) |
| x XFAIL | Expected to fail, but didn't pass |
| X XPASS | Expected to fail, but passed |

### Coverage Output

```
Name                      Stmts   Miss  Cover
---------------------------------------------
wilab/__init__.py            5      0   100%
wilab/config.py             45      2    96%
wilab/models.py            120      5    96%
wilab/api/routes/network.py 156    10    94%
wilab/wifi/manager.py      203     18    91%
---------------------------------------------
TOTAL                      742     45    94%
```

**Stmts:** Total statements  
**Miss:** Missed statements  
**Cover:** Coverage percentage

---

## Writing Tests

### Test File Structure

```python
import pytest
from wilab.models import NetworkCreateRequest
from wilab.wifi.hostapd import HostapdError
from wilab.wifi.manager import StartupFailure

REQUEST = NetworkCreateRequest(
    ssid="TestAP", channel=6, band="2.4ghz", encryption="wpa2",
    password="test1234", tx_power_level=4,
)


class TestNetworkCreation:
    """Test suite for network creation functionality."""

    def test_start_network_success(self, clean_manager, monkeypatch):
        """Test successful network creation (clean_manager comes from conftest.py)."""
        # conftest.py refuses to launch a real hostapd: mock its start.
        monkeypatch.setattr(clean_manager.hostapd_manager, "start", lambda **kwargs: None)
        device = clean_manager.config.antennas[0].device_id
        result = clean_manager.start_network(device, REQUEST)

        assert result.active is True
        assert result.ssid == "TestAP"

    def test_start_network_hostapd_failure(self, clean_manager, monkeypatch):
        """Test network creation when hostapd fails."""
        def fail(*args, **kwargs):
            raise HostapdError("hostapd failed")
        monkeypatch.setattr(clean_manager.hostapd_manager, "start", fail)

        device = clean_manager.config.antennas[0].device_id
        with pytest.raises(StartupFailure):
            clean_manager.start_network(device, REQUEST)
```

### Common Fixtures

**From conftest.py:**
```python
# Use fixtures provided by conftest.py
@pytest.fixture(scope="session")
def config():
    """Configuration loaded from test.config.yaml."""

@pytest.fixture(autouse=True)
def mock_network_operations(monkeypatch, tmp_path):
    """Mocks ip, iw, hostapd, dnsmasq and the other host commands in every test."""

@pytest.fixture
def clean_manager(config, monkeypatch):
    """A fresh NetworkManager with no active networks and a mocked DHCP server."""
```

Managers take the `DeviceRegistry` of the managed devices (Fable ARCH-4).
`configured_devices(config)` returns a registry with the enabled antennas of the
test configuration, the devices an app built by the tests starts with;
`registry_of("dev0", "dev1")` returns one with the given interfaces:
`NetworkManager(config, configured_devices(config))`,
`ReservationManager(registry_of("dev0"))`.

`network_body(**flat)` builds the sectioned create body (`radio`, `wifi`,
`internet`, `captive_portal`) from flat fields. Every create runs as in
production: the `POST` answers `202` and the start runs in a background job.
`create_network(client, headers, url, body)` sends the `POST` and polls
`GET .../network` until the start ends; it returns the `POST` answer and the
outcome (the network, `runtime_state: start_failed` with `error`, or `404`
with the `reason`). `test_async_create.py` tests the contract itself
(`202`, polling, cancel).

```python
body = network_body(ssid="TestAP", channel=6, band="2.4ghz", encryption="open", tx_power_level=4)
created, outcome = create_network(client, headers, f"/api/v2/reservations/{rid}/network", body)
assert created.status_code == 202 and outcome.json()["active"] is True
```

---

## CI/CD Integration

### In CI and locally

The Makefile is the only entry point: `make test-local` (verbose, with the coverage
report), `make test-local-quick` (no coverage, for every change) and `make test-local-cov`
(HTML report in `htmlcov/`). CI runs `make lint`, `make type-check` and `make test-local`.

### Continuous Testing

```bash
# Watch mode (requires pytest-watch plugin)
pip install pytest-watch
ptw  # Reruns tests on file changes

# Or with pytest natively (requires polling)
watch -n 2 pytest tests/unit-tests/
```

---

## Test Debugging

### Print Debugging

```bash
# Show all print() output
pytest tests/unit-tests/test_api.py -v -s

# Print only from failing tests
pytest tests/unit-tests/test_api.py -v -s --tb=short
```

### Use pdb (Python Debugger)

```python
def test_something():
    result = my_function()
    breakpoint()  # Stops here, opens debugger
    assert result == expected
```

Then run with:
```bash
pytest tests/unit-tests/test_something.py -v -s
```

### Verbose Tracebacks

```bash
# Long traceback format
pytest tests/unit-tests/ -v --tb=long

# No traceback
pytest tests/unit-tests/ -v --tb=no

# Line-by-line
pytest tests/unit-tests/ -v --tb=line
```

---

## Common Issues

### Issue: Tests Fail with "Module Not Found"

**Cause:** Virtual environment not activated or dependencies not installed

**Solution:**
```bash
# Activate venv
source .venv/bin/activate

# Install requirements
pip install -r requirements-dev.txt

# Try again
pytest tests/unit-tests/
```

### Issue: Tests Timeout

**Cause:** Async operations not completing or infinite loops in test

**Solution:**
```bash
# Set timeout (needs the pytest-timeout plugin, not in requirements-dev.txt)
pytest tests/unit-tests/ --timeout=10

# Disable specific test
pytest tests/unit-tests/ --deselect tests/unit-tests/test_slow_operation.py::test_takes_forever
```

### Issue: Permission Denied on subprocess Tests

**Cause:** A test reached a real host command. Unit tests never need root:
`conftest.py` mocks every host command and refuses to launch a real `hostapd`
("hostapd must be mocked in tests").

**Solution:** do not run the unit tests with `sudo`. Mock the command the test
reached (see "Mock Not Working as Expected" below), or use the fixtures of
`conftest.py`.

### Issue: Mock Not Working as Expected

**Cause:** Incorrect patch path or timing

**Solution:**
```python
# Always patch where object is USED, not where defined
# WRONG: @patch('wilab.network.commands.execute_command')
# RIGHT: @patch('wilab.wifi.hostapd.execute_command')

# Patch should target the import in the module being tested
@patch('wilab.wifi.manager.execute_command')  # manager imports execute_command
def test_something(self, mock_execute):
    ...
```

---

## Best Practices

### 1. Isolate Tests

```python
# Each test should be independent
def test_start_network(self, manager):
    # Don't rely on results from other tests
    # Don't modify global state
    manager.start_network(...)
```

### 2. Use Fixtures

```python
# Good: Fixture provides clean state each time
@pytest.fixture
def manager(config):
    return NetworkManager(config, configured_devices(config))

def test_something(self, manager):
    # Fresh manager instance
    ...
```

### 3. Mock External Dependencies

```python
# Good: Mock subprocess calls
@patch('wilab.network.commands.execute_command')
def test_network_rules(self, mock_execute):
    mock_execute.return_value = "success"
    # Test doesn't require actual iptables
    ...
```

### 4. Meaningful Names

```python
# Good: Clear what is being tested
def test_network_expires_after_timeout(self):
    ...

# Bad: Vague
def test_network(self):
    ...
```

### 5. One Assertion Per Test (When Possible)

```python
# Good: Single focus
def test_network_status_returns_active(self):
    assert result.active is True

def test_network_has_correct_ssid(self):
    assert result.ssid == expected

# Less ideal: Multiple concerns
def test_network_status(self):
    assert result.active is True
    assert result.ssid == expected
    assert result.subnet == expected
    # Hard to know which assertion failed
```

---

## Test Coverage Goals

- **Overall target:** >90% coverage
- **Critical paths:** 100% coverage for API endpoints and WiFi control
- **External dependencies:** Mock all subprocess/system calls
- **Error cases:** Test both success and failure paths

### Check Coverage

```bash
# Generate detailed coverage report
pytest tests/unit-tests/ --cov=wilab --cov-report=html

# View report
open htmlcov/index.html

# Find uncovered lines
# Look for lines highlighted in red in HTML report
```

---

## Development Workflow

### Test-Driven Development (TDD)

```bash
# 1. Write test for new feature
# 2. Run test (should fail)
pytest tests/unit-tests/test_new_feature.py -v

# 3. Implement feature
# 4. Run test (should pass)
pytest tests/unit-tests/test_new_feature.py -v

# 5. Run all tests to verify no regressions
pytest tests/unit-tests/ -v

# 6. Check coverage
pytest tests/unit-tests/ --cov=wilab --cov-report=term
```

### Before Committing

```bash
# Run complete test suite
pytest tests/unit-tests/ -v --cov=wilab

# Run linter (auto-fix with: make lint-fix)
make lint

# Run type checker
make type-check

# If all pass: commit!
git add -A && git commit -m "Add feature with tests"
```

---

## Documentation

For more detailed information:
- **pytest documentation:** https://docs.pytest.org/
- **Mocking guide:** https://docs.python.org/3/library/unittest.mock.html
- **Async testing:** https://pytest-asyncio.readthedocs.io/

---

**Testing setup complete! 🧪**

Run tests with confidence:
```bash
pytest tests/unit-tests/ -v
```
