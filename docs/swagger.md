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

Every `/api/v1` application error has a JSON `detail` object with an integer
`code`, a stable `reason` and, for generic errors, a human-readable `message`.
Generic codes match the HTTP status (for example `401`, `404`, `422`, `500`).
Use `detail.message` for display, not for control flow. This replaces the old
string form of `detail` on errors only.

API timestamps are RFC 3339 strings in UTC, marked by a `Z` suffix
(for example `2026-11-19T23:00:00Z`). This applies to `expires_at` on
reservation and network responses and to `detail.next_available_at` on
reservation contention. Unlimited reservations still have `expires_at: null`.
Durations and countdowns such as `expires_in`, `next_available_in` and
`Retry-After` remain in seconds.

- Swagger and ReDoc display the same OpenAPI contract. Swagger can execute
  requests; ReDoc is a read-only reference. Both show the lifecycle overview,
  operation-level response examples and the retry rules.
- Prefer interactive testing from Swagger instead of manual endpoint calls in shell snippets.
- Use the `Authorize` button once, then execute requests directly from the UI.
- Device lifecycle operations are serialized to protect reservations. Other independent
  requests can remain responsive while a device operation runs.
- A timeout or lost response to a reservation request does not prove that the server
  rejected it. The API does not provide an idempotency key; avoid blindly retrying.
  If the reservation ID is unknown, the device may remain occupied until expiry;
  an unlimited reservation requires operator intervention.

⚠️ **Note:** debug operations are expensive (150-600ms). Use them only for manual troubleshooting, not for frontend polling.

## Network creation failure

In the **Network** group, open **Create a network on a reserved adapter**.
Its `409` examples distinguish an existing AP from a recoverable radio failure
(`detail.code: 1001`). Only the latter permits retrying creation with the same
ID after `Retry-After`. Under **Responses → 500 → Example Value**, select
**500 - Startup failed; reservation still valid** for a generic error, or
**500 / 1003 - Adapter quarantined; discard the reservation ID** for a terminal
error. Neither `500` includes `Retry-After`. In the **Reservation** group, `503 / 1003` means
all adapters are quarantined and there is no automatic retry recommendation.
In the **Reservation** group, `503 / 1002` instead means that a *new*
reservation request can be retried after `Retry-After`. `503 / 1004` means
cleanup failed; it is not a recovery retry. `409 / 1005` is ordinary
reservation contention and can include `detail.next_available_in`.

For a complete interactive example:

1. In **Reservation**, execute the timed example for `POST /api/v1/device-reservation`.
2. In **Network**, copy the returned `reservation_id` into the create endpoint
   and choose a channel supported by the adapter. If you get `409 / 1001`,
   wait for `Retry-After` before repeating the same body and ID.
3. Use **Read system and adapter status** to distinguish
   `recovery_state` (quarantine) from `runtime_state` (AP/DHCP restoration).
   During restoration, read status instead of sending another create.
4. When finished, delete the reservation by ID; Wi-Lab stops the network.
   Do not send this request for an ID already invalidated by `500 / 1003`.

See the [AP creation procedure](ap-creation-procedure.md) for the complete
client flow and retry rules, and [Architecture](architecture.md) for USB recovery.

