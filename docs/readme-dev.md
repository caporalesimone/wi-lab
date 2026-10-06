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

### 2. Create Local Dev Environment

```bash
# Create local virtual environment and runtime dependencies
make venv

# Install development/test dependencies (required once)
<install-dev-dependencies-command>

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
- `pytest-mock` - Mocking utilities
- `ruff` - Fast Python linter and code formatter (replaces flake8, isort, black)
- `mypy` - Static type checker for Python

### 4. Create Local Configuration

```bash
# Create and edit your local configuration
nano <local-config-file>
```

**Example config:**
```yaml
auth_token: "dev-token-12345"
api_port: 8080
cors_origins: []

max_timeout: 86400
min_timeout: 60
allow_unlimited_reservation: false

dhcp_base_network: "192.168.120.0/24"
upstream_interface: "auto"
dns_server: "192.168.10.1"
internet_enabled_by_default: true
country_code: "IT"

networks:
  - interface: "wlx782051245264"  # Your WiFi interface
    display_name: "bench-antenna-1"
    capabilities:
      "2.4ghz": true
      "5ghz": true
```

**Every key is mandatory** — the validator refuses a file with anything missing, and
`load_config()` exits rather than start on one. Check the file before running anything:

```bash
make validate-config                                 # through the venv
python3 main.py --validate-config                    # structure, types and values
python3 main.py --validate-config --check-hardware   # also interfaces and host routes
```

Exit codes are `0` valid, `1` invalid, `2` unreadable. `--validate-config` constructs no
manager, starts no server and touches no interface — that property is asserted by
`tests/test_cli.py`, so it stays safe to run on a production host.

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

# Example with hot reload (adapt module path as needed)
uvicorn wilab.api:app --reload --host 0.0.0.0 --port 8080
```

### Accessing the API

Once running:
- **API Docs:** `http://localhost:8080/docs`
- **Alternative Docs:** `http://localhost:8080/redoc`

See [docs/swagger.md](swagger.md) for complete API testing guide.

### Offline API documentation bundle

To read the API documentation without running the service (and without any adapter),
generate a self-contained bundle:

```bash
python scripts/export_api_docs.py --out api-docs
```

It writes `openapi.json`, `swagger.html`, `redoc.html` and
`wi-lab-api-docs-<version>.zip` containing the three. The HTML files embed the schema and
the Swagger UI / ReDoc code, so they open with a double click and need no network (the
renderers are downloaded once, at generation time, from pinned versions). "Try it out" is
disabled in `swagger.html` because there is no server behind it.

The same bundle is built on every pull request (CI artifact `wi-lab-api-docs-<version>`) and attached to
every GitHub release as `wi-lab-api-docs-<version>.zip`
(`.github/workflows/release-docs.yml`; it can also be run manually from the Actions tab).

**Retention.** The `wi-lab-api-docs-<version>` artifact is kept for 90 days, the longest GitHub allows
(artifacts cannot be kept indefinitely); deleting a run deletes its artifacts too. The release
attachment is a release asset, not an artifact, and never expires. A last job of the CI (`cleanup-runs`, script `scripts/cleanup_pr_runs.py`)
deletes the pull-request workflow runs of each pull request except its 3 most recent ones,
however recent; runs on `main`, releases and manual runs are never touched. It runs only
when a pull request is active, so nothing is scheduled while the project is idle. To see what it
would delete, run `python scripts/cleanup_pr_runs.py --dry-run` with the GitHub CLI logged in.

---

## Testing

### Running Tests

For complete testing documentation, see [docs/unit-testing.md](unit-testing.md).

Preferred commands (via Makefile):

```bash
# Run full test suite
make test-local

# Run quick test suite
make test-local-quick

# Run with coverage report
make test-local-cov
```

Advanced (targeted tests when needed):

```bash
 Run specific test file
.venv/bin/pytest tests/test_api.py -v

# Run a specific test node
.venv/bin/pytest tests/test_api.py::TestNetworkCreateEndpoint::test_network_response_structure -v
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

# Validate config.yaml without starting anything
make validate-config

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
.venv/bin/pytest tests/test_api.py -v
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

---

## Extending the Configuration

### Adding a validation rule

Rules live in `wilab/config_validation.py` and are registered with the `@rule` decorator.
One function, one problem, yielding zero or more `ValidationIssue`s:

```python
@rule(scope="dns_server")
def check_dns_server_is_not_the_gateway(ctx: ValidationContext) -> Iterable[ValidationIssue]:
    value = _get_str(ctx.raw, "dns_server")
    if value is None:
        return                      # presence is already reported elsewhere
    if value == "0.0.0.0":
        yield ValidationIssue(
            path="dns_server",
            message="0.0.0.0 is not a usable DNS server.",
            hint="Use your LAN resolver or a public one such as 208.67.222.222.",
        )
```

Four things to respect:

| Rule | Why |
|------|-----|
| **Be defensive about the input** | Rules run on the raw parsed YAML, so a value may be missing, `None`, or the wrong type entirely. Return quietly instead of raising; another rule already owns "this key is missing" and "this key is the wrong type" |
| **Always give a `hint`** | The report has to be enough on its own. An error without a next action sends the operator to the source |
| **ASCII only** | The report is printed to consoles with legacy code pages and to journald under `LANG=C`. A typographic arrow raises `UnicodeEncodeError` there and passes every test, because pytest captures in UTF-8 |
| **Never echo a secret** | `auth_token` values are scrubbed from the rendered report; do not defeat that by quoting the value back |

Pass `hardware=True` for a rule that inspects the machine — an interface, a route table.
Those run only under `--check-hardware` (and always at startup), which is what keeps
`--validate-config` usable on a laptop and in CI.

**Hardware rules must import their helpers inside the function body, never at module
level:**

```python
@rule(scope="networks[].interface", hardware=True)
def check_interfaces_exist(ctx):
    from ..wifi.interface import validate_interface   # deferred, on purpose
```

This is not a style preference. `tests/conftest.py` monkeypatches `validate_interface` and
`execute_command` so the suite never shells out to `iw` or `ip`; a module-level import
binds the original function at import time and silently defeats that patch, making every
config-loading test hit the real hardware. `test_conftest_monkeypatch_reaches_the_validator`
fails if someone "tidies" the import to the top of the file.

Rules replace the Pydantic `field_validator`s the models used to carry. Keeping both would
mean two reporting paths with different formatting, and Pydantic stops at the first error
per field while the whole point of the validator is to report everything at once.

### Adding a capability

A capability is one enum member plus one registry entry in `wilab/config.py`:

```python
class Capability(str, Enum):
    BAND_24GHZ = "2.4ghz"
    BAND_5GHZ = "5ghz"
    BAND_6GHZ = "6ghz"          # new

CAPABILITY_REGISTRY = {
    ...
    Capability.BAND_6GHZ: CapabilityDef(
        id=Capability.BAND_6GHZ,
        label="6 GHz",
        kind=CapabilityKind.RADIO,
        group="band",
    ),
}
```

Everything else follows automatically: the required-key manifest, the validator's hints,
the reservation request validator, the selection algorithm, the `/status` catalogue and
the frontend picker all read the registry rather than a hard-coded list.

Two consequences to be aware of:

- **It is a breaking configuration change.** Every device must declare every id, so every
  existing `config.yaml` becomes invalid until the new key is added. Announce it in the
  CHANGELOG under `⚠️ Breaking Changes` and lean on `--validate-config` for the upgrade.
- **`group` carries meaning.** A capability in a group listed in `GROUPS_REQUIRING_ONE`
  (currently `band`) participates in the "at least one enabled" check. A future policy
  capability such as `change-ssid` would simply carry no group and be exempt.

Only boolean, matchable capabilities are supported. `CapabilityType.INTEGER` and
`matchable=False` exist in the model as documented extension points, and an import-time
guard in `wilab/config.py` **raises** if either is used — the selection algorithm would
mis-allocate devices otherwise. It raises rather than asserts because `assert` is stripped
under `python -O`.

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

Writers/readers for individual setup stages are intentionally deferred to the
next phase.
- **API Layer** - HTTP routes, auth checks, and handlers
- **Network Layer** - WiFi, DHCP, NAT, and isolation orchestration
- **System Commands Layer** - Controlled wrappers around host networking commands

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
.venv/bin/pytest tests/test_file.py -v -s
```

### Check Service Logs

```bash
# If running via systemd
sudo journalctl -u wi-lab.service -f

# View recent errors
sudo journalctl -u wi-lab.service | grep ERROR
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

- ✅ Configuration still validates: `make validate-config`
- ✅ Code style passes: `make lint` (or auto-fix with `make lint-fix`)
- ✅ Type checking passes: `make type-check` (warnings expected during transition)
- ✅ All tests pass: `make test-local`
- ✅ Coverage maintained: `make test-local-cov`
- ✅ Optional targeted validation: `.venv/bin/pytest tests/test_api.py -v`
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
<your-run-command>
```

Then open your API docs endpoint in the browser (for example: `http://localhost:8080/docs`).
