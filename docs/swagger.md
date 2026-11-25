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

- **Maintenance** groups operations that clients must not use; they appear
  only in this group. **Every Maintenance operation requires the
  `X-Confirm-Password` header** with `protected_commands_password` from the
  server configuration, besides the token, and is disabled (`403`) when that
  setting is missing. `DELETE /api/v1/device-reservation/all` releases
  **every** reservation and may be removed in a future version.
  `GET /api/v1/debug` shows internal state for troubleshooting; it is
  **deprecated** (struck through in Swagger) and will be removed.

⚠️ **Note:** `GET /api/v1/debug` is expensive (150-600ms). Use it only for manual troubleshooting, not for frontend polling.

- **Antennas** comes before **Network**: `GET /api/v1/antennas` lists the
  managed antennas, `GET /api/v1/antennas/{interface}` gives what a network on
  one can use (encryptions, and per band the Wi-Fi generations, widths and
  usable channels). Only the token is needed, no reservation.

## Service health (`degraded`)

Open **System → Read system and adapter status**. Under **Responses → 200 →
Examples** select `standby`, `ok` or `degraded_quarantine`. `status:
"degraded"` means at least one adapter is quarantined
(`networks[].recovery_state`: `recovering` or `unavailable`), a reserved
network is being repaired, lost DHCP or could not be restarted
(`networks[].runtime_state`: `restoring_ap`, `restoring_dhcp`, `dhcp_failed`,
`restore_failed`), a host command is stuck in the kernel
(`checks.commands.stuck` > 0), a background loop stalled
(`checks.loops.stale`), or a
health check in `checks` failed while networks are active. Clients must poll
this endpoint to learn about quarantined adapters: a quarantined adapter can
show `reserved: false` but is not allocatable, and only its former owner is
told directly (`503 / 1003` on the create). See
[AP creation procedure, 2.8](ap-creation-procedure.md#28-service-health-degraded-and-quarantined-antennas).

## Encryption, channel width and Wi-Fi generation

In **Create a network on a reserved adapter**, the body is grouped in
`radio`, `wifi` (with `security`), `internet` and `captive_portal`, like the
answer of **GET .../network**; every example shows all the optional fields
with their defaults. The schema describes each `wifi.security.encryption`
value, `radio.channel_width` and `radio.wifi_generation`; the
examples **5 GHz Wi-Fi 5 network at 80 MHz** and **Legacy WPA (TKIP) network
for old clients** show the new fields. `encryption: "wpa"` is no longer
accepted: the `422` example **encryption wpa is no longer accepted** shows the
message, which points to `wpa2`. The other `422` examples show an antenna that
lacks `wpa1`, a channel that cannot be used at the requested width, and an
unsupported Wi-Fi generation. What each antenna accepts is in
**Antennas → Read what a network on an antenna can use**. See
[AP creation procedure, 2.2.1](ap-creation-procedure.md#221-encryption-channel-width-and-wi-fi-generation).

## Network creation failure

In the **Network** group, open **Create a network on a reserved adapter**.
Its `409` examples distinguish an existing AP from a recoverable radio failure
(`detail.code: 1001`). Only the latter permits retrying creation with the same
ID after `Retry-After`. Under **Responses → 500 → Example Value**, select
**500 - Startup failed; reservation still valid** for a generic error. Under
**Responses → 503**, **503 / 1003 - Adapter quarantined; discard the reservation
ID** is the terminal error (`reservation_invalidated: true`); before API-4 it
was a `500`. Neither includes `Retry-After`. In the **Reservation** group, `503 / 1003` means
all adapters are quarantined and there is no automatic retry recommendation.
In the **Reservation** group, `503 / 1002` instead means that a *new*
reservation request can be retried after `Retry-After`. `503 / 1004` means
cleanup failed; it is not a recovery retry. `409 / 1005` is ordinary
reservation contention and can include `detail.next_available_in`.

`409 / 1007` (`network_not_active`) is the answer of the Internet, TX power
and QoS profile endpoints when the reservation is valid but has no running
network; `404` there always means the reservation is gone.

`503 / 1006` (`device_busy`, example **1006 - adapter busy, retry**) is
documented on every reservation endpoint except the create: another operation
on the same adapter, for example a network start, still held it after 5 s.
Nothing was changed; repeat the request after `Retry-After` (2 s). The create
waits for the adapter instead.

For a complete interactive example:

1. In **Reservation**, execute the timed example for `POST /api/v1/device-reservation`.
2. In **Network**, copy the returned `reservation_id` into the create endpoint
   and choose a channel supported by the adapter. If you get `409 / 1001`,
   wait for `Retry-After` before repeating the same body and ID.
3. Use **Read system and adapter status** to distinguish
   `recovery_state` (quarantine) from `runtime_state` (AP/DHCP restoration).
   During restoration, read status instead of sending another create.
4. When finished, delete the reservation by ID; Wi-Lab stops the network.
   Do not send this request for an ID already invalidated by `503 / 1003`.

See the [AP creation procedure](ap-creation-procedure.md) for the complete
client flow and retry rules, and [Architecture](architecture.md) for USB recovery.

