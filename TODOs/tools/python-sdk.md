# Feature: Python SDK

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

A Python library for the Wi-Lab API, so test scripts do not build HTTP calls by
hand. The e2e client (`tests/e2e-tests/wilab_e2e.py`) is a starting point.

## Implementation Tasks

- [ ] Package `wilab-client`, generated from the OpenAPI schema or written on top of `httpx`, sync and async
- [ ] Reservations (reserve, release, extend), access point (create, wait for the start, read, stop, Internet), antennas and capabilities, status, QoS
- [ ] Errors as exceptions carrying `code`, `reason` and the client action (retry after `Retry-After` for 1006)
- [ ] The create polling rules of the API (202, poll until not `starting`, 404 reasons) built in
- [ ] Configuration from arguments or `WILAB_URL`, `WILAB_TOKEN`
- [ ] Type hints, docstrings, examples; published on PyPI with the Wi-Lab version

## Testing

- [ ] Unit tests with mocked HTTP; integration tests against the unit-test app
- [ ] mypy clean

## Benefits

- **Automation:** Short, correct test scripts
- **Consistency:** Retry and polling rules implemented once

## Breaking Changes

- None (new package)

## Success Criteria

- ✅ A test script reserves, creates, waits and releases in a few lines
