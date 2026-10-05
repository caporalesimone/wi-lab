# Wi-Lab API Documentation

## Interactive API Documentation

Access interactive API testing and documentation at:

**Swagger UI:** `http://localhost:8080/docs`

**How to use:**
1. Open `http://localhost:8080/docs`
2. Click "Authorize" button (top-right)
3. Enter your `auth_token` from `config.yaml`
4. Test endpoints interactively

**Alternative formats:**
- ReDoc (read-only): `http://localhost:8080/redoc`
- OpenAPI JSON: `http://localhost:8080/openapi.json`

---

## Usage Guidance

- Use Swagger UI as the single source of truth for all available operations, schemas, and responses.
- Prefer interactive testing from Swagger instead of manual endpoint calls in shell snippets.
- Use the `Authorize` button once, then execute requests directly from the UI.

⚠️ **Note:** debug operations are expensive (150-600ms). Use them only for manual troubleshooting, not for frontend polling.

---

## Device Capabilities (4.0.0)

Every managed device declares its capabilities in `config.yaml` — currently the bands
`2.4ghz` and `5ghz`. Since 4.0.0 a reservation request **must** state what it needs: a
client written against 3.x, which sends only `duration_seconds`, is rejected with `422`.

### `POST /api/v1/device-reservation` — request

| Field | Type | Notes |
|-------|------|-------|
| `duration_seconds` | `int` | **Required.** `0` = unlimited, when allowed by config |
| `required_capabilities` | `string[]` | **Required, at least one.** Capabilities the assigned device must provide: `2.4ghz` and/or `5ghz`. An empty list and `null` are rejected |

Capability ids are case-insensitive and whitespace-tolerant (`"5GHz"` is accepted); the
list is de-duplicated and sorted before use, so the outcome does not depend on the order
the client sent. An unknown id is rejected with `422`.

A request missing either required field is answered with `422` and **every** missing field
at once:

```json
{ "detail": "Missing required field(s): required_capabilities" }
```

### `POST` / `GET /api/v1/device-reservation` — response

| Field | Type | Notes |
|-------|------|-------|
| `capabilities` | `string[]` | What the assigned device actually provides. Only enabled capabilities appear — a `false` one is never listed |

### Reservation error responses

| Status | When | Body |
|--------|------|------|
| `409` | Matching devices exist but are all reserved — **transient**, retry later | `detail` object with `error`, `requested_capabilities`, `next_available_at`, `next_available_in` |
| `422` | Missing required field, invalid duration, unknown capability id, or **no device can ever** provide what was asked — permanent, change the request | `detail` object (see below) or a string for duration errors |

**`next_available_at` and `next_available_in` are nullable.** Both are `null` when every
matching device is held by an unlimited reservation: there is no scheduled release, so
there is nothing to report and a client must not count down to it. `next_available_at` is
rendered in **UTC** (`yyyy-mm-dd HH:MM:SS`), like every other timestamp in the API.

The `422` body for an unsatisfiable request:

```jsonc
// The pool as a whole cannot serve the request
{
  "detail": {
    "error": "No device provides the requested capabilities",
    "requested": ["5ghz"],
    "available_capabilities": ["2.4ghz"]   // union over ALL configured devices
  }
}
```

`409` means *wait*; `422` means *change the request*. A client should only start a retry
countdown on `409`.

### `GET /api/v1/status` and `GET /api/v1/debug`

| Field | Type | Notes |
|-------|------|-------|
| `networks[].capabilities` | `string[]` | Enabled capabilities of that device |
| `capabilities_catalogue` | `object[]` | What the lab as a whole can offer |

Each catalogue entry carries `id`, a human-readable `label`, a `kind`, `total_devices`
and `available_devices` (free right now). A capability that **no** device enables is
omitted from the catalogue — offering a filter that can never match is worse than not
offering it — so a client should drive its UI from this list rather than from a
hard-coded set of ids.

