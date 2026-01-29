# Feature: API Simplification - Network Endpoints Consolidation

**Priority:** 1 (CRITICAL)  
**Status:** PROPOSED  
**Estimated Effort:** ~1.5 hours  

## Description

Current API has redundant endpoints for network status retrieval. This feature consolidates overlapping endpoints to reduce API complexity and improve developer experience.

### Current Problem
- `GET /interface/{net_id}/network` - Full status (13 fields) including password & expiration
- `GET /interface/{net_id}/status` - Minimal status (3 fields) for health checks
- `GET /interface/{net_id}/summary` - Extended info (16 fields) with DHCP details & connected clients

**Redundancy:** `/network` and `/summary` overlap ~90% with only minor differences.

### Proposed Solution
Consolidate to 2 endpoints:

1. **`GET /interface/{net_id}/status`** - Keep minimal (3 fields: net_id, interface, active)
   - Use case: Lightweight polling, health checks
   - Response size: ~80 bytes

2. **`GET /interface/{net_id}/network`** - Unified complete endpoint (merge current `/network` + `/summary`)
   - Returns: All configuration + password + expires_in + DHCP details + connected clients
   - Use case: Full network state retrieval
   - Response size: ~600 bytes
   - Clients can ignore unused fields if needed

## Implementation Tasks

- 1 [ ] Update `NetworkStatus` model in `wilab/models.py` to include DHCP and clients fields
- 2 [ ] Modify `get_network()` in `wilab/api/routes/network.py` to return complete data
- 3 [ ] Remove `/interface/{net_id}/summary` endpoint
- 4 [ ] Update Swagger documentation with consolidated endpoint
- 5 [ ] Update frontend to use new consolidated endpoint
- 6 [ ] Update integration tests for new endpoint structure
- 7 [ ] Add deprecation notice in CHANGELOG for `/summary` endpoint
- 8 [ ] Test backward compatibility where possible

## Benefits

- **Simpler API:** From 3 to 2 endpoints (-33%)
- **Better DX:** One call for complete network state
- **Easier maintenance:** Less code duplication
- **Reduced learning curve:** Clearer endpoint purpose

## Breaking Changes

- `/interface/{net_id}/summary` endpoint removed
- Clients using `/summary` should migrate to `/network`
- Migration guide required in documentation

## Success Criteria

- ✅ Only 2 network status endpoints remain
- ✅ No data duplication across endpoints
- ✅ All tests passing with new structure
- ✅ Swagger documentation updated
- ✅ Frontend migrated and tested
