# Feature: Command-Line Tool

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

A `wilab` command for the terminal, built on the Python SDK
([python-sdk.md](python-sdk.md)): reserve, create, watch and release from a shell
or a CI job.

## Implementation Tasks

- [ ] Commands: `status`, `antennas`, `reserve`, `release`, `ap create`, `ap show`, `ap stop`, `ap internet on|off`, `qos`
- [ ] `--watch` for status and access point; `--format table|json`
- [ ] Configuration: `~/.config/wilab/config.yaml`, `WILAB_URL`, `WILAB_TOKEN`, `--url`, `--token`
- [ ] Confirmation for destructive commands; shell completion

## Testing

- [ ] CLI runner tests with a mocked SDK; output formats

## Benefits

- **Usability:** Wi-Lab from a terminal or a CI job without writing code

## Breaking Changes

- None (new tool)

## Success Criteria

- ✅ Every listed command works and has `--help`
