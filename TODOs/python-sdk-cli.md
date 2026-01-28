# Feature: Python SDK & CLI Tool

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Official Python library and command-line interface for programmatic API access and command-line control of Wi-Lab.

## Part 1: Python Client SDK

### Implementation Tasks

- [ ] Create package structure: `wilab/sdk/` or separate `wilab-client` package
- [ ] Main Classes:
  - `WiLabClient` - Main API client
  - `Network` - Network object with methods
  - `Client` - Client device object
  - `Stats` - Statistics object
- [ ] Authentication support:
  - API key/token authentication
  - Optional Bearer token support
  - Session management

### API Wrapper Methods

- [ ] Network operations:
  - `create_network(ssid, band, channel, ...)`
  - `get_network(net_id)`
  - `list_networks()`
  - `delete_network(net_id)`
  - `update_network(net_id, ...)`
- [ ] Client operations:
  - `get_clients(net_id)`
  - `get_client(net_id, mac)`
  - `block_client(net_id, mac)`
  - `unblock_client(net_id, mac)`
  - `rate_limit_client(net_id, mac, rate_mbps)`
- [ ] Statistics:
  - `get_stats(net_id)`
  - `get_clients_stats(net_id)`
- [ ] Health & Admin:
  - `health_check()`
  - `get_server_info()`

### Language Features

- [ ] Full type hints (Python 3.7+)
- [ ] Comprehensive docstrings (Google/NumPy style)
- [ ] Context manager support (with statement)
- [ ] Async support with `httpx`
- [ ] Connection pooling and session reuse
- [ ] Automatic request retry with exponential backoff
- [ ] Request timeout configuration

### Configuration

- [ ] Environment variables:
  - `WILAB_SERVER_URL`
  - `WILAB_API_KEY`
  - `WILAB_TIMEOUT`
- [ ] Config file support: `~/.wilab/config.yml`
- [ ] Per-instance configuration override

### Testing

- [ ] Unit tests for all methods
- [ ] Mock HTTP responses for testing
- [ ] Integration tests against live server (optional)
- [ ] Type checking with mypy
- [ ] >90% code coverage

### Documentation

- [ ] README with examples
- [ ] Full API reference
- [ ] Usage examples (sync and async)
- [ ] Error handling guide
- [ ] Contributing guide

### Publishing

- [ ] Setup.py/pyproject.toml configuration
- [ ] Dependencies: requests or httpx
- [ ] Publish to PyPI
- [ ] Version management

## Part 2: CLI Tool (wilab-cli)

### Implementation Tasks

- [ ] Create CLI using Click or Typer framework
- [ ] Executable: `wilab-cli` command
- [ ] Configuration file: `~/.wilab/config.yml` for server URL and auth

### Main Commands

- [ ] `wilab-cli list [OPTIONS]` - List all networks
  - Options: `--format` (table/json/csv)
- [ ] `wilab-cli create [OPTIONS] SSID` - Create network
  - Options: `--band`, `--channel`, `--password`, `--duration`
- [ ] `wilab-cli delete [OPTIONS] NET_ID` - Delete network
  - Options: `--force` (skip confirmation)
- [ ] `wilab-cli status [OPTIONS] NET_ID` - Show network status
  - Options: `--watch` (refresh every N seconds)
- [ ] `wilab-cli clients [OPTIONS] NET_ID` - List connected clients
  - Options: `--format` (table/json/csv)
- [ ] `wilab-cli stats [OPTIONS] NET_ID` - Show traffic stats
  - Options: `--watch`, `--format`
- [ ] `wilab-cli block [OPTIONS] NET_ID MAC` - Block client
- [ ] `wilab-cli unblock [OPTIONS] NET_ID MAC` - Unblock client
- [ ] `wilab-cli rate-limit [OPTIONS] NET_ID MAC MBPS` - Set rate limit
- [ ] `wilab-cli config [OPTION]` - Show/manage configuration

### Output Formats

- [ ] **table** (default) - Formatted ASCII table with colors
- [ ] **json** - JSON output for scripting
- [ ] **csv** - CSV format for spreadsheets
- [ ] **yaml** - YAML format

### Features

- [ ] Tab completion for bash/zsh
- [ ] Color-coded output (errors red, success green)
- [ ] Progress indicators for long operations
- [ ] Verbose/quiet modes
- [ ] Config file for default options
- [ ] Server URL and token management
- [ ] Help command for all subcommands

### Global Options

- [ ] `--server URL` - Override server URL
- [ ] `--token TOKEN` - Override API token
- [ ] `--format FORMAT` - Output format
- [ ] `--verbose / --quiet` - Logging level
- [ ] `--config PATH` - Config file path

### Interactive Features

- [ ] Confirmation prompts for destructive operations
- [ ] Network selection from list (if ambiguous)
- [ ] Watch mode for continuous monitoring
- [ ] Error recovery suggestions

### Testing

- [ ] Unit tests for all commands
- [ ] Mock API responses
- [ ] Test with various output formats
- [ ] Test error scenarios and help messages
- [ ] Integration tests with CLI runner

### Documentation

- [ ] README with installation and quick start
- [ ] Command reference with examples
- [ ] Configuration guide
- [ ] Output format examples
- [ ] Contributing guide

### Publishing

- [ ] Package setup for distribution
- [ ] Install via: `pip install wilab-cli`
- [ ] Publish to PyPI
- [ ] Shell completion scripts (bash, zsh, fish)

## Benefits

- **Developer Tools:** Programmatic API access from Python
- **Automation:** Script Wi-Lab operations
- **Integration:** Easy to use in existing Python projects
- **DevOps:** CLI for infrastructure automation
- **Type Safety:** Full type hints for IDE support

## Breaking Changes

- None (new tools)

## Success Criteria

- ✅ Python SDK provides all API operations
- ✅ SDK fully type-hinted and documented
- ✅ CLI tool covers main use cases
- ✅ Output formats (table, json, csv) working
- ✅ Configuration management robust
- ✅ Both published to PyPI
- ✅ >90% test coverage for both
