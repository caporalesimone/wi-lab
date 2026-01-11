# Wi-Lab Unit Testing Guide

Wi-Lab uses pytest for comprehensive unit and integration testing. This document explains how to run and work with tests.

---

## Quick Start

### Run All Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=wilab --cov-report=html --cov-report=term

# Run quick mode (less verbose)
pytest tests/ -q
```

### Run Specific Tests

```bash
# Run single test file
pytest tests/test_config.py -v

# Run single test class
pytest tests/test_wifi.py::TestNetworkLifecycle -v

# Run single test method
pytest tests/test_api.py::TestAuthenticationEndpoints::test_valid_token -v

# Run tests matching pattern
pytest tests/ -k "test_tx_power" -v
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

The test suite includes:
- **conftest.py** - Shared fixtures and configuration
- **test_config.py** - Configuration loading/validation tests
- **test_api.py** - API endpoint tests
- **test_commands.py** - Shell command wrapper tests
- **test_dhcp.py** - DHCP server tests
- **test_nat.py** - NAT rules tests
- **test_isolation.py** - Network isolation tests
- **test_wifi.py** - WiFi interface/hostapd tests

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
# Python 3.9+
python3 --version

# Virtual environment tools
python3 -m venv --help
```

### Create Development Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt

# Verify pytest is installed
pytest --version
```

### Understanding requirements-dev.txt

The `requirements-dev.txt` file contains testing and development tools:

```
pytest              # Test framework
pytest-cov          # Coverage reporting
pytest-asyncio      # Async test support
pytest-mock         # Mocking utilities
black               # Code formatter
flake8              # Linter
mypy                # Type checker
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
pytest tests/ -v

# Show print statements (use print() for debugging)
pytest tests/ -v -s

# Stop after first failure
pytest tests/ -x

# Fail on first N errors
pytest tests/ --maxfail=3
```

### Coverage Reports

```bash
# Generate coverage report in terminal
pytest tests/ --cov=wilab --cov-report=term

# Generate HTML coverage report
pytest tests/ --cov=wilab --cov-report=html
# Open: htmlcov/index.html

# Coverage for specific module
pytest tests/ --cov=wilab.wifi --cov-report=term
```

### Test Markers

```bash
# Run only fast tests
pytest tests/ -m "not slow" -v

# Run slow tests
pytest tests/ -m "slow" -v

# Skip tests marked as xfail (expected failures)
pytest tests/ --runxfail
```

---

## Understanding Test Output

### Example Verbose Output

```bash
$ pytest tests/test_api.py -v

tests/test_api.py::TestHealthEndpoint::test_health_check PASSED           [  5%]
tests/test_api.py::TestHealthEndpoint::test_health_structure PASSED       [ 10%]
tests/test_api.py::TestAuthenticationEndpoints::test_valid_token PASSED   [ 15%]
tests/test_api.py::TestAuthenticationEndpoints::test_invalid_token FAILED [ 20%]

FAILED tests/test_api.py::TestAuthenticationEndpoints::test_invalid_token
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
wilab/api/routes.py        156     10    94%
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
from unittest.mock import patch, MagicMock
from wilab.wifi.manager import NetworkManager

class TestNetworkCreation:
    """Test suite for network creation functionality."""
    
    @pytest.fixture
    def manager(self):
        """Create manager instance for testing."""
        return NetworkManager()
    
    def test_create_network_success(self, manager):
        """Test successful network creation."""
        result = manager.create_network("wlan0", {
            "ssid": "TestAP",
            "channel": 6,
            "encryption": "wpa2",
            "password": "test1234",
            "tx_power_level": 4
        })
        
        assert result.active is True
        assert result.ssid == "TestAP"
    
    @patch('wilab.wifi.hostapd.execute_hostapd')
    def test_create_network_hostapd_failure(self, mock_hostapd, manager):
        """Test network creation when hostapd fails."""
        mock_hostapd.side_effect = RuntimeError("hostapd failed")
        
        with pytest.raises(RuntimeError):
            manager.create_network("wlan0", {
                "ssid": "TestAP",
                "channel": 6,
                "encryption": "wpa2",
                "password": "test1234",
                "tx_power_level": 4
            })
```

### Common Fixtures

**From conftest.py:**
```python
# Use fixtures provided by conftest.py
@pytest.fixture
def config():
    """Loaded configuration object."""
    
@pytest.fixture
def mock_subprocess():
    """Mocked subprocess for command testing."""
```

---

## CI/CD Integration

### Using run-tests.sh

```bash
# The project includes a test runner script
./run-tests.sh

# This script typically:
# 1. Sets up virtual environment if needed
# 2. Runs pytest with standard options
# 3. Generates coverage reports
# 4. Returns appropriate exit code for CI/CD
```

### Continuous Testing

```bash
# Watch mode (requires pytest-watch plugin)
pip install pytest-watch
ptw  # Reruns tests on file changes

# Or with pytest natively (requires polling)
watch -n 2 pytest tests/
```

---

## Test Debugging

### Print Debugging

```bash
# Show all print() output
pytest tests/test_api.py -v -s

# Print only from failing tests
pytest tests/test_api.py -v -s --tb=short
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
pytest tests/test_something.py -v -s
```

### Verbose Tracebacks

```bash
# Long traceback format
pytest tests/ -v --tb=long

# No traceback
pytest tests/ -v --tb=no

# Line-by-line
pytest tests/ -v --tb=line
```

---

## Common Issues

### Issue: Tests Fail with "Module Not Found"

**Cause:** Virtual environment not activated or dependencies not installed

**Solution:**
```bash
# Activate venv
source venv/bin/activate

# Install requirements
pip install -r requirements-dev.txt

# Try again
pytest tests/
```

### Issue: Tests Timeout

**Cause:** Async operations not completing or infinite loops in test

**Solution:**
```bash
# Set timeout (adjust 10 to appropriate seconds)
pytest tests/ --timeout=10

# Disable specific test
pytest tests/ --deselect tests/test_slow_operation.py::test_takes_forever
```

### Issue: Permission Denied on subprocess Tests

**Cause:** Tests require sudo/root permissions

**Solution:**
```bash
# Run tests with sudo
sudo pytest tests/ -v

# Or skip tests requiring sudo
pytest tests/ -k "not requires_sudo"
```

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
def test_create_network(self, manager):
    # Don't rely on results from other tests
    # Don't modify global state
    manager.create_network(...)
```

### 2. Use Fixtures

```python
# Good: Fixture provides clean state each time
@pytest.fixture
def manager():
    return NetworkManager()

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
pytest tests/ --cov=wilab --cov-report=html

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
pytest tests/test_new_feature.py -v

# 3. Implement feature
# 4. Run test (should pass)
pytest tests/test_new_feature.py -v

# 5. Run all tests to verify no regressions
pytest tests/ -v

# 6. Check coverage
pytest tests/ --cov=wilab --cov-report=term
```

### Before Committing

```bash
# Run complete test suite
pytest tests/ -v --cov=wilab

# Run formatter
black wilab/ tests/

# Run linter
flake8 wilab/ tests/

# Run type checker
mypy wilab/

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
pytest tests/ -v
```
