# Feature: WPA3 Variants

**Priority:** 6  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Choose how WPA3 (SAE) derives its password element and which groups it uses.
Today `sae_pwe=2` (both methods) and the default groups.

## Implementation Tasks

- [ ] Optional `wifi.security.sae_pwe`: `hunting_and_pecking` (0), `hash_to_element` (1), `both` (2, default)
- [ ] Optional `wifi.security.sae_groups` (e.g. 19, 20, 21)
- [ ] Only with `wpa3` and `wpa2-wpa3`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "security": {
      "encryption": "wpa3",
      "password": "testpass123",
      "sae_pwe": "hash_to_element",
      "sae_groups": [
        19,
        20
      ]
    }
  }
}
```

Response `202`:

```json
{
  "runtime_state": "starting",
  "active": false
}
```

Errors: `422` with the field path for an invalid value.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "wifi": {
    "security": {
      "encryption": "wpa3",
      "password": "testpass123",
      "sae_pwe": "hash_to_element",
      "sae_groups": [
        19,
        20
      ]
    }
  }
}
```

`sae_pwe`: `hunting_and_pecking`, `hash_to_element`, `both` (default).

## Testing

- [ ] Unit tests and validation
- [ ] Real radio: an old WPA3 client fails with H2E only

## Benefits

- **Testing:** WPA3 compatibility of clients; Wi-Fi 6E requires H2E

## Breaking Changes

- None (optional fields)

## Success Criteria

- ✅ Each SAE variant works or fails as expected with real clients
