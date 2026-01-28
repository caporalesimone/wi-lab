# Feature: Startup Recovery & Crash Cleanup

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Auto-cleanup on startup if previous instance crashed. Detects and removes orphaned processes, iptables rules, and other leftover resources to ensure clean state.

### Problem Statement

When Wi-Lab crashes or is forcefully terminated:
- Stale dnsmasq processes remain running
- iptables NAT rules remain active
- Network namespaces may not be properly cleaned
- Next startup may encounter port conflicts or rule duplicates

## Implementation Tasks

### Orphaned Process Cleanup

- [ ] On startup, detect orphaned dnsmasq processes
- [ ] Check for processes not owned by current service instance
- [ ] Safely terminate stale processes with SIGTERM then SIGKILL
- [ ] Log all killed processes with PIDs
- [ ] Verify cleanup success before starting new services

### iptables Rule Cleanup

- [ ] Scan iptables rules with `wilab-*` comment markers
- [ ] Compare against active networks in config
- [ ] Identify orphaned rules (comment exists but network not active)
- [ ] Create cleanup report with rules to be removed
- [ ] Safely remove orphaned rules
- [ ] Verify removal success

### Network Namespace Cleanup

- [ ] Detect orphaned network namespaces with `wilab-*` naming pattern
- [ ] Remove unused namespaces
- [ ] Handle namespace dependencies (veth pairs, etc.)
- [ ] Log cleanup actions

### Health Check Integration

- [ ] Add recovery stats to `GET /api/v1/health` response:
  - Orphaned processes found and cleaned
  - Orphaned rules found and cleaned
  - Orphaned namespaces found and cleaned
  - Recovery timestamp
- [ ] Mark recovery status: success/partial/failed

### Testing

- [ ] Unit tests for orphaned process detection
- [ ] Unit tests for iptables rule parsing
- [ ] Integration tests for cleanup sequence
- [ ] Test with manually created orphaned resources
- [ ] Verify health check reports cleanup status

## Benefits

- **Reliability:** Service can recover from crashes automatically
- **Cleanliness:** No accumulated orphaned resources
- **Visibility:** Admin can see what was cleaned up
- **Peace of Mind:** Don't need manual cleanup after crashes

## Breaking Changes

- None

## Success Criteria

- ✅ Orphaned processes detected and cleaned on startup
- ✅ Orphaned iptables rules detected and cleaned
- ✅ Health endpoint reports recovery actions
- ✅ Cleanup operations are idempotent (safe to run multiple times)
- ✅ All cleanup logged with details
- ✅ No false positives (don't kill unrelated processes)
