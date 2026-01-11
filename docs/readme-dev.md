# Wi-Lab Development Guide

This guide explains how to set up a development environment and contribute to Wi-Lab.

---

## Prerequisites

### System Requirements

- **OS:** Ubuntu 20.04+ or Debian 11+
- **Python:** 3.9+
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
git clone https://github.com/your-org/wi-lab.git
cd wi-lab
```

### 2. Create Virtual Environment

```bash
# Create venv
python3 -m venv venv

# Activate it
source venv/bin/activate

# Verify activation (should show (venv) in prompt)
python --version  # Should show Python 3.9+
```

### 3. Install Development Dependencies

```bash
# Install all dependencies including dev tools
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Verify pytest installed
pytest --version
```

**What's in requirements-dev.txt:**
- `pytest` - Testing framework
- `pytest-cov` - Coverage reporting
- `pytest-asyncio` - Async test support
- `pytest-mock` - Mocking utilities
- `black` - Code formatter
- `flake8` - Code linter
- `mypy` - Type checker

### 4. Create Configuration File

```bash
# Minimal config for development
nano config.yaml
```

**Example config:**
```yaml
auth_token: "dev-token-12345"
api_port: 8080
default_timeout: 3600

dhcp_base_network: "192.168.120.0/24"
upstream_interface: "auto"
dns_server: "192.168.10.1"
internet_enabled_by_default: true

networks:
  - net_id: "ap-01"
    interface: "wlx782051245264"  # Your WiFi interface
```

---

## Running Wi-Lab Locally

### Development Server

```bash
# Make sure venv is activated
source venv/bin/activate

# Run directly (simple)
python main.py

# Or with uvicorn for hot reload (advanced)
uvicorn wilab.api:app --reload --host 0.0.0.0 --port 8080
```

### Accessing the API

Once running:
- **API Docs:** `http://localhost:8080/docs`
- **Alternative Docs:** `http://localhost:8080/redoc`
- **Health Check:** `http://localhost:8080/api/v1/health`

See [docs/swagger.md](docs/swagger.md) for complete API testing guide.

---

## Testing

### Running Tests

For complete testing documentation, see [docs/unit-testing.md](docs/unit-testing.md).

Quick commands:

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=wilab --cov-report=term

# Run specific test file
pytest tests/test_api.py -v

# Run specific test
pytest tests/test_api.py::TestHealthEndpoint::test_health_check -v
```

### Using the Makefile

The Makefile provides convenient shortcuts for development tasks:

```bash
# Run tests locally
make test-local

# Quick test run (less output)
make test-local-quick

# Generate coverage report
make test-local-cov

# Create virtual environment
make venv

# Clean up (remove venv)
make clean-venv
```

See [Makefile](Makefile) for complete list of available commands and their descriptions.

---

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/my-new-feature
```

### 2. Make Changes

Edit code in `wilab/` directory:
- `wilab/api/` - REST API endpoints
- `wilab/wifi/` - WiFi interface control
- `wilab/network/` - Network management
- `wilab/config.py` - Configuration
- `wilab/models.py` - Data models

### 3. Test Your Changes

```bash
# Run tests
pytest tests/ -v

# Check code quality
black wilab/ tests/  # Format code
flake8 wilab/ tests/ # Check style
mypy wilab/          # Type check
```

### 4. Verify Manually

```bash
# Run the service
python main.py

# In another terminal, test API
curl http://localhost:8080/api/v1/health

# Test with Swagger UI
# Open: http://localhost:8080/docs
```

### 5. Commit and Push

```bash
git add -A
git commit -m "Add my-new-feature"
git push origin feature/my-new-feature
```

### 6. Create Pull Request

Push branch and create PR on GitHub for review.

---

## Code Structure

The project follows clean separation of concerns:

- **`wilab/config.py`** - Loads and validates `config.yaml`
- **`wilab/models.py`** - Pydantic models for API validation and data types
- **`wilab/version.py`** - Version information
- **`wilab/api/routes.py`** - All REST API endpoints
- **`wilab/api/auth.py`** - Token authentication and security
- **`wilab/api/__init__.py`** - FastAPI app creation and setup
- **`wilab/wifi/interface.py`** - WiFi interface abstraction class
- **`wilab/wifi/hostapd.py`** - hostapd configuration and process management
- **`wilab/wifi/manager.py`** - Network lifecycle management and timeouts
- **`wilab/network/commands.py`** - Subprocess wrapper functions (ip, iw, iptables, etc.)
- **`wilab/network/dhcp.py`** - DHCP server configuration (dnsmasq)
- **`wilab/network/nat.py`** - NAT rules and Internet forwarding (iptables)
- **`wilab/network/isolation.py`** - Network isolation between WiFi APs
- **`wilab/network/safety.py`** - Network safety checks and protections

### Design Principles

**Separation of Concerns:** Each module has a single, well-defined responsibility  
**No Monolithic Files:** Code split across focused modules under 300 lines each  
**Layered Architecture:** API → Service → System Commands  
**Type Hints:** All function signatures and class attributes have type annotations  
**Error Handling:** Clear error messages and appropriate HTTP status codes  

---

## Debugging

### Enable Verbose Logging

```bash
# Set Python verbosity
PYTHONVERBOSE=2 python main.py

# Or add logging in code
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Use Python Debugger

```python
# Add breakpoint in code
def my_function():
    result = something()
    breakpoint()  # Stops here
    return result

# Run with pytest
pytest tests/test_file.py -v -s
```

### Check Service Logs

```bash
# If running via systemd
sudo journalctl -u wilab.service -f

# View recent errors
sudo journalctl -u wilab.service | grep ERROR
```

---

## Documentation

When adding new features, update documentation:

- **API changes:** Update docstrings in `wilab/api/routes.py`
- **Configuration:** Add comments to `config.yaml`
- **User guide:** Update files in `docs/`
- **Development:** Update this file if procedures change

See `docs/` directory for all user-facing documentation.

---

## Contributing Guidelines

### Before Committing

- ✅ All tests pass: `pytest tests/ -v`
- ✅ Code formatted: `black wilab/ tests/`
- ✅ No linting errors: `flake8 wilab/ tests/`
- ✅ Type hints valid: `mypy wilab/`
- ✅ Coverage maintained: `pytest tests/ --cov=wilab`
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

## Documentation Links

- **Installation:** [docs/installation-guide.md](docs/installation-guide.md)
- **Networking:** [docs/networking.md](docs/networking.md)
- **API Testing:** [docs/swagger.md](docs/swagger.md)
- **Unit Testing:** [docs/unit-testing.md](docs/unit-testing.md)
- **Troubleshooting:** [docs/troubleshooting.md](docs/troubleshooting.md)

---

**Development environment ready! 🚀**

Start developing:
```bash
source venv/bin/activate
python main.py
```

Then access API docs at: `http://localhost:8080/docs`
