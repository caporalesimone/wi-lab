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

## API Proposal

### `PATCH /api/v2/access-point/{reservation_id}`

Change what can change on a running access point, with the sections of the create body.

Request:

```json
{
  "internet": {
    "enabled": false
  }
}
```

Response `200`:

```json
{
  "interface": "wlx7419f8176286",
  "active": true,
  "internet": {
    "enabled": false
  }
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `422 validation_error` with the field path (`radio: cannot change on a running access point`); `404` with `detail.reason` when the reservation is gone.

Replaces `POST /api/v2/access-point/{reservation_id}/internet/enable` and `.../disable`. The answer is the full access point, as `GET` returns it (shortened here).

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
