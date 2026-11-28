# Feature: New Web Application

**Priority:** 3  
**Status:** PROPOSED  
**Estimated Effort:** ~2 weeks  

## Description

Rewrite the web UI as a new application inside the frontend container
([docker-container.md](docker-container.md)), page by page, replacing today's UI.

## Implementation Tasks

- [ ] Framework: React + Vite + TanStack Query (recommended for a rewrite) or Angular brought up to date; decide when the work starts
- [ ] Typed API client generated from Wi-Lab's OpenAPI at build time: a contract change breaks the build, not the UI
- [ ] Push instead of polling: one event stream ([event-stream.md](../events/event-stream.md)); polling only as a fallback
- [ ] Pages: antennas overview; antenna detail (capabilities, health); reservation and access point (settings, clients, restarts, Internet, QoS); events and logs; system (version, `restart_required`, checks)
- [ ] Keep what REV-13/REV-14 fixed in today's UI: create polling rules, reservation IDs kept across reloads, every `404` reason as a sentence
- [ ] Include the API functions today's UI lacks ([missing-functions.md](missing-functions.md))

## Testing

- [ ] Unit tests (Vitest) and end-to-end UI tests (Playwright) against a Wi-Lab with fake radios, in CI

## Benefits

- **Maintainability:** A typed, tested UI built on the current API

## Breaking Changes

- None for the API

## Success Criteria

- ✅ Every page of today's UI is replaced
- ✅ UI tests run in CI
