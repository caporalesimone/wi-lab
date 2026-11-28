# Feature: PATCH for Access Point Changes

**Priority:** 8  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Replace the action paths `POST /access-point/{reservation_id}/internet/enable`
and `.../internet/disable` (Fable API-7) with one
`PATCH /access-point/{reservation_id}` that takes the same sections as the
create body, e.g. `{"internet": {"enabled": false}}`. Postponed on 2026-11-25.

## Implementation Tasks

- [ ] `PATCH /access-point/{reservation_id}`: only the sections that can change on a running AP (`internet` today)
- [ ] Refuse other sections with 422 and the reason
- [ ] Keep the old paths for one version, deprecated in Swagger, then remove them
- [ ] Frontend: use the PATCH

## Testing

- [ ] The same tests as the internet actions, through PATCH
- [ ] 422 for a section that cannot change

## Benefits

- **Consistency:** One way to change a running AP, the same shape as the create

## Breaking Changes

- Yes, when the old paths are removed

## Success Criteria

- ✅ Internet on and off through PATCH
- ✅ The old paths are deprecated, then removed
