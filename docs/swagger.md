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

Every `/api/v2` application error has a JSON `detail` object with an integer
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
  setting is missing. `DELETE /api/v2/reservations/all` releases
  **every** reservation and may be removed in a future version. The detail
  of the health checks is in **System → Read the detailed health checks**
  (`GET /api/v2/monitoring`).

- **Antennas** comes before **Network**: `GET /api/v2/antennas/{interface}`
  gives what a network on an antenna can use (the antennas are `antennas[]` of
  `GET /api/v2/status`) (encryptions, and per band the Wi-Fi generations, widths and
  usable channels). Only the token is needed, no reservation.

## Service health (`degraded`)

Open **System → Read system and adapter status**. Under **Responses → 200 →
Examples** select `all_free`, `one_reserved` or `degraded_quarantine`. `service.free_antennas`
is how many antennas a reservation would get now; `service.health:
"degraded"` means at least one adapter is quarantined
(`antennas[].recovery_state`: `recovering` or `unavailable`), a reserved
network is being repaired, lost DHCP or could not be restarted
(`antennas[].runtime_state`: `restoring_ap`, `restoring_dhcp`, `dhcp_failed`,
`restore_failed`), a host command is stuck in the kernel, a background loop
stalled, or a health check failed while networks are active: each cause is an
entry of `service.degraded_reasons` with a stable `code`. **System → Read the detailed
health checks** (`GET /api/v2/monitoring`) gives the detail of every check.
Clients must poll
this endpoint to learn about quarantined adapters: a quarantined adapter can
show `reservation: null` but is not allocatable, and only its former owner is
told directly (`404` with `reason: reservation_invalidated` on its next call). See
[AP creation procedure, 2.8](ap-creation-procedure.md#28-service-health-degraded-and-quarantined-antennas).

## Encryption, channel width and Wi-Fi generation

In **Create a network on a reserved adapter (asynchronous)**, the body is grouped in
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

In the **Network** group, open **Create a network on a reserved adapter
(asynchronous)**. It answers `202` with `runtime_state: starting`; then read
**Get network** until the outcome: the network, `runtime_state: start_failed`
with `error` (`1013` and the failed `stage`, reservation still valid), or `404`
whose `detail.reason` is `reservation_invalidated` (every start failed, antenna
quarantined) or `reservation_expired`. Its `409` examples distinguish another
network (`1008`), a watchdog repair (`1009`) and a stop that did not complete
(`1012`). Radio failures are retried by
the server during the start, so no outcome asks the client to repeat the
create. Every code is listed in [Error codes](error-codes.md). In the
**Reservation** group, `503 / 1003` means all adapters are quarantined and
there is no automatic retry recommendation.
In the **Reservation** group, `503 / 1002` instead means that a *new*
reservation request can be retried after `Retry-After`. `409 / 1005` is ordinary
reservation contention and can include `detail.next_available_in`. A release
always answers `200`, even if the server must repeat the cleanup.

`409 / 1007` (`network_not_active`) is the answer of the Internet, TX power
and QoS profile endpoints when the reservation is valid but has no running
network; `404` there always means the reservation is gone.

`503 / 1006` (`device_busy`, example **1006 - adapter busy, retry**) is
documented on **Get network**, the network stop and the Internet, TX power and
QoS profile endpoints: another operation on the same adapter, for example a
network start, still held it after 5 s. Nothing was changed; repeat the
request after `Retry-After` (2 s). The create and the release never answer
it, and **Get network** answers at once while a create is starting.

For a complete interactive example:

1. In **Reservation**, execute the timed example for `POST /api/v2/reservations`.
2. In **Network**, copy the returned `reservation_id` into the create endpoint
   and choose a channel supported by the adapter. Then execute **Get network**
   until `runtime_state` is no longer `starting`.
3. Use **Read system and adapter status** to distinguish
   `recovery_state` (quarantine) from `runtime_state` (AP/DHCP restoration).
   During restoration, read status instead of sending another create.
4. When finished, delete the reservation by ID; Wi-Lab stops the network.
   For an ID already invalidated the answer is `404` (`reservation_invalidated`).

See the [AP creation procedure](ap-creation-procedure.md) for the complete
client flow and retry rules, and [Architecture](architecture.md) for USB recovery.

