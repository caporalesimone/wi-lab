# AP creation procedure

This guide is for developers of Wi-Lab API clients. It describes how to reserve
an antenna and start an access point (AP) on it, which responses to expect, and
exactly when a request may be repeated. For the server internals behind each
step, see [Architecture](architecture.md).

All endpoints are under `/api/v1` and require `Authorization: Bearer <token>`.
Every error body has the same envelope:

```json
{"detail": {"code": 1001, "reason": "retry_later", "message": "optional text"}}
```

Use the HTTP status and `detail.code` for control flow. `detail.message` is for
display only and can change between versions.

## 1. Reservation

An AP always runs on a reserved antenna. The reservation decides **which**
antenna you get and **how long** you may use it.

```http
POST /api/v1/device-reservation
Content-Type: application/json

{"duration_seconds": 600}
```

| Response | Meaning | Client action |
|---|---|---|
| `200` | Antenna reserved. Body has `reservation_id`, `interface`, `display_name`, `expires_at`, `expires_in`. | Keep `reservation_id`: every following call uses it. |
| `409 / 1005` | All antennas are reserved. `detail.next_available_at` is the estimated availability in UTC; `detail.next_available_in` is the wait in seconds. Both are `null` when no release is scheduled. | Retry later with backoff, or wait for an unlimited reservation to be released. |
| `503 / 1002` + `Retry-After: 10` | No antenna can be assigned while an antenna is being recovered. | Retry **the reservation** after `Retry-After`. This is a polling interval, not a promise. |
| `503 / 1003` | No antenna has been discovered yet, or none is usable and recovery is not running. | If the pool is empty at startup, allow discovery time and check `/status` before reserving again. If antennas remain unavailable, ask an operator to investigate. |
| `503 / 1004` | Cleanup of an expired reservation failed. | Do not retry automatically. |
| `422` | `duration_seconds` is outside the server limits, or `0` while unlimited reservations are disabled. | Fix the request. |

Rules that matter for the AP:

- The AP lives only as long as the reservation. Creating or restarting an AP
  **never extends** `expires_at`. When the reservation expires, Wi-Lab stops
  the AP and frees the antenna.
- Reservation and network `expires_at` values use RFC 3339 UTC with a `Z`
  suffix (e.g. `2026-11-19T23:00:00Z`). They are `null` for unlimited
  reservations. `expires_in` is a countdown in seconds.
- The server picks the antenna (the first free one). You cannot choose it.
- Release the reservation when you are done:
  `DELETE /api/v1/device-reservation/{reservation_id}`. This also stops the AP;
  a separate network stop is not required. A `503 / 1004` on release means
  cleanup failed and the antenna is still held.
- `GET /api/v1/device-reservation/{reservation_id}` returns the remaining time.
  `404` means the ID is no longer valid (expired, released or invalidated).

## 2. Creating the AP

### 2.1 Choose a channel

Ask which channels the reserved antenna supports:

```http
GET /api/v1/interface/{reservation_id}/network/available-channels
```

The response lists 2.4 GHz and 5 GHz channels. Skip entries with
`"disabled": true`: they are blocked by regulatory restrictions or by the
server's DFS policy. By default (`allow_dfs_channels: false`, including when
omitted), Wi-Lab blocks channels flagged by the radio as requiring radar
detection. A creation request selecting one of those channels returns `422`
without starting the AP or substituting another channel.

To allow DFS channels where permitted, set `allow_dfs_channels: true` in
`config.yaml` and restart Wi-Lab. The radar check (CAC) on a DFS channel
usually takes about 60 seconds; Wi-Lab's current startup timeout for 5 GHz
channels 52–144 is 75 seconds, so longer checks can time out.

### 2.2 Build the request

```http
POST /api/v1/interface/{reservation_id}/network
Content-Type: application/json

{
  "ssid": "lab-test-01",
  "channel": 6,
  "band": "2.4ghz",
  "encryption": "wpa2",
  "password": "testpass123",
  "hidden": false,
  "internet_enabled": true,
  "captive_portal": false,
  "tx_power_level": 4
}
```

| Field | Required | Rules |
|---|---|---|
| `ssid` | yes | Network name. |
| `channel` | yes | Must be valid for `band` and supported and enabled on the antenna. |
| `band` | yes | `2.4ghz` or `5ghz`. An AP uses one band. |
| `encryption` | yes | `open`, `wpa`, `wpa2`, `wpa3` or `wpa2-wpa3`. |
| `password` | unless `open` | 8–63 characters for any WPA mode. |
| `tx_power_level` | yes | `1` (low) to `4` (maximum). |
| `hidden` | no | Default `false`. |
| `internet_enabled` | no | Default from the server configuration. Enables NAT to the upstream network. |
| `captive_portal` | no | Default `false`; omitting it keeps the previous behavior. Puts clients behind a simulated captive portal; see [2.7](#27-captive-portal). |

Validate the body on the client side when possible: an invalid body returns
`422` without touching the antenna.

### 2.3 Send it with the right timeout

Creating an AP is synchronous: the response arrives only when the AP is
broadcasting and DHCP is running, or when startup has failed and been rolled
back. Typical duration is a few seconds. Configure the HTTP client with a long
read timeout so that a slow start is not mistaken for a failure:

| Channel | Suggested read timeout |
|---|---|
| 2.4 GHz and non-DFS 5 GHz | at least 60 s |
| DFS 5 GHz (52–144) | at least 120 s |

These are client recommendations, not server guarantees.

**Send only one create at a time per reservation.** Wi-Lab serializes work per
antenna, so parallel requests for the same reservation only queue up.

### 2.4 Handle the response

| Response | Meaning | Client action |
|---|---|---|
| `200` | The AP is up and DHCP is running. | Done. Stop retrying. |
| `409 / 1001` + `Retry-After` | A **classified radio failure** occurred and was rolled back. The reservation is still valid. | Wait `Retry-After` seconds, then repeat the **same** request with the **same** ID and body. |
| `409` without code `1001`, "already active" | An AP is already running on this reservation. | Do not retry. Read it with `GET .../network`, or stop it first with `DELETE .../network`. |
| `409` without code `1001`, "restoration in progress" | The watchdog is restarting this AP. | Do not create. Poll `GET .../network` until `runtime_state` is gone. |
| `422` | Invalid body, or channel unsupported/disabled on this antenna. | Fix the request. Do not retry the same body. |
| `404` | The reservation is unknown, expired or invalidated. | Stop using the ID. Reserve again if needed. |
| `500 / 1003` | **Terminal failure.** The antenna was quarantined and the reservation **invalidated**. | Discard the ID. Do not retry creation and do not release it. Reserve again if needed. |
| `500 / 500` (generic startup error) | An unclassified startup error (e.g. `hostapd` exited with code 1, gateway or DHCP failure). The rollback succeeded and the reservation is **still valid**. | Do not retry automatically. Show `detail.message`. Release the ID if abandoning this attempt; release it before asking for a fresh reservation. |
| `503 / 1004` | A device cleanup failed. | Do not retry automatically. |
| `401` | Missing or invalid token. | Fix the token. |

After this generic startup `500`, `DELETE /api/v1/device-reservation/{id}`
releases the still-held antenna on `200`. The next reservation may get the same
antenna or a different one. Do not implement release → reserve → create as an
automatic recovery loop: that bypasses the retry budget. In contrast, after
`500 / 1003` the ID is already invalidated and must not be released.

### 2.5 When and how to retry

Only `409 / 1001` explicitly authorizes an automatic retry after a create error
response. Wi-Lab counts classified radio failures per reservation and allows
**three attempts** in a row:

| Attempt | Outcome if it fails with a classified radio failure |
|---|---|
| 1 | `409 / 1001`, `Retry-After: 5` |
| 2 | `409 / 1001`, `Retry-After: 10` |
| 3 | `500 / 1003`: reservation invalidated, antenna quarantined |

A success resets the counter. Further rules:

- **Respect `Retry-After`.** A request sent during the cooldown returns
  `409 / 1001` again with the remaining seconds (rounded up). It does not start
  the radio and does **not** use up an attempt, but it is wasted work.
- **Reuse the same ID and body.** A new reservation would start a new count on
  possibly another antenna and leaves this one held until it expires.
- **Check the remaining reservation time** before waiting. The cooldown does not
  extend the reservation; if it would expire first, release it and start over.
- **Do not count your own retries on top of the server's.** On the first
  attempt Wi-Lab may already retry once internally (a `hostapd` crash on
  2.4 GHz, within about 5 seconds). The client sees only the final result.
- **Transport errors are ambiguous.** If the connection drops or the client
  times out, the server may have finished the AP or still be working on it. Do
  not resend the create blindly; first read the state:

  ```http
  GET /api/v1/interface/{reservation_id}/network
  ```

  The status call can wait for an in-progress create, so use a long timeout.
  During `restoring_ap` or `restoring_dhcp`, wait and read status again.
  Otherwise: `active: true` → the AP is up; `active: false` → you may send the
  create again; `404` → the ID is gone.

### 2.6 After the AP is running

- `GET /api/v1/interface/{reservation_id}/network` returns SSID, channel,
  subnet, DHCP details, connected clients and remaining time.
- Wi-Lab's watchdog checks every running AP about every 5 seconds and can
  restart it **once** with the same settings and reservation. While this
  happens, `GET .../network` and `GET /api/v1/status` report `runtime_state`:

  | `runtime_state` | Meaning | Client action |
  |---|---|---|
  | `restoring_ap` | The AP is being restarted. Clients will need to reconnect. | Wait. Do not send a create. |
  | `restoring_dhcp` | Only DHCP is being restarted. The AP stays up. | Wait. |
  | `dhcp_failed` | DHCP could not restart. The AP is up but new clients cannot get an address. | Release and reserve again if new clients are needed. |

- An AP restart clears traffic shaping and QoS profiles: reapply them after a
  `restoring_ap` phase.
- If the restart fails because of the radio, or the AP fails again later, the
  reservation is invalidated: `GET .../network` returns `404`. Reserve again.
  If it fails for another reason, the reservation stays valid but the AP is
  stopped (`active: false`).
- `GET /api/v1/status` reports `recovery_state` (`recovering` or `unavailable`)
  for quarantined antennas. They can show `reserved: false` but are **not**
  allocatable.
- To stop the AP but keep the antenna: `DELETE .../network`. To finish: release
  the reservation.

### 2.7 Captive portal

With `"captive_portal": true`, each client that joins the AP is held behind a
simple portal until it signs in. Use it to check how a device detects a
captive network. Without the flag, nothing changes.

Until the client signs in:

- DNS queries are answered by the AP with the gateway address, so connectivity
  checks resolve and reach the portal even when `internet_enabled` is `false`.
- HTTP requests on port 80, to any host, are redirected (`302`) to the portal
  page, `http://<gateway>/`.
- Any other forwarded traffic, including HTTPS, is rejected.

The page, titled **WiLab Captive Portal**, shows the SSID, band and channel,
subnet, gateway, DHCP range, the client's IP and MAC address, whether the
network has Internet access, and when the network expires. Its **Sign in**
button releases only the client that pressed it, identified by its MAC and IP
address. Other clients stay on the portal. There is no API to sign a client
in.

After sign-in, the client uses the DNS server from the configuration and the
network's normal Internet setting: with `internet_enabled: false` it stays
offline. `GET .../network` reports `captive_portal`, `captive_portal_url` and,
for each client, `captive_authorized`.

Notes:

- Clients are detected through their HTTP connectivity checks. Wi-Lab does not
  advertise the portal via DHCP option 114 (RFC 8910) and does not intercept
  HTTPS.
- A client that obtains a new IP address, or changes its MAC address, must
  sign in again. Sign-ins are cleared when the AP stops, the reservation ends
  or the watchdog restarts the AP.
- The portal listens on port 80 and dnsmasq answers DNS on port 53, both on
  the AP gateway address only.

## 3. Sequence diagram

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant W as Wi-Lab API

    C->>W: POST /device-reservation {duration_seconds}
    alt 200
        W-->>C: reservation_id, interface, expires_in
    else 409 / 1005
        W-->>C: next_available_in
        Note over C: Retry the reservation later with backoff
    else 503 / 1002 + Retry-After 10
        W-->>C: an antenna is in recovery
        Note over C: Retry the reservation after Retry-After
    else 503 / 1003
        W-->>C: no antenna discovered or usable
        Note over C: Check status after startup discovery or ask an operator
    else 503 / 1004
        W-->>C: cleanup failure
        Note over C: Stop and ask an operator
    end

    C->>W: GET /interface/{id}/network/available-channels
    W-->>C: channels per band (skip disabled ones)

    loop At most 3 attempts with the same ID and body
        C->>W: POST /interface/{id}/network {ssid, channel, band, ...}
        Note over W: Prepare radio, start hostapd, wait for AP ready,<br/>assign gateway, start DHCP. May retry once internally.
        alt 200
            W-->>C: network created
            Note over C: Done. Leave the loop
        else 409 / 1001 + Retry-After (5 then 10)
            W-->>C: classified radio failure, reservation kept
            Note over C: Check remaining reservation time,<br/>wait Retry-After, then repeat
        else 500 / 1003
            W-->>C: reservation invalidated, antenna quarantined
            Note over C: Discard the ID. Do not release it.<br/>Reserve again if needed
        else 500 / 500 from AP startup
            W-->>C: startup failed, reservation kept
            Note over C: No automatic retry. Leave the loop.<br/>Release if abandoning or reserving again
        else 409 (other), 422, 404
            W-->>C: error detail
            Note over C: No automatic retry. Show detail to the user
        else transport timeout or connection error
            C->>W: GET /interface/{id}/network
            W-->>C: active and runtime_state, or 404
            Note over C: Resend only if inactive and not restoring
        end
    end

    loop While the AP is needed
        C->>W: GET /interface/{id}/network
        W-->>C: status, clients, runtime_state
        Note over C: During restoring_ap or restoring_dhcp just wait.<br/>Reapply QoS after restoring_ap. 404 means invalidated
    end

    opt Client is done and still holds a valid reservation
        C->>W: DELETE /device-reservation/{id}
        W-->>C: 200 (AP stopped, antenna freed) or 503 / 1004
    end
```

## 4. Reference client logic

```python
def create_ap(api, reservation_id, body):
    for _ in range(3):
        try:
            r = api.post(f"/interface/{reservation_id}/network", json=body, timeout=120)
        except TransportError:
            state = api.get(f"/interface/{reservation_id}/network", timeout=120)
            if state.status_code == 404:
                raise ReservationLost()
            state.raise_for_status()
            network = state.json()
            if network.get("runtime_state") in ("restoring_ap", "restoring_dhcp"):
                network = wait_for_restoration(api, reservation_id)  # Bounded GET polling.
            if network["active"]:
                return network
            continue  # The previous create did not leave an AP: try again.

        code = r.json().get("detail", {}).get("code") if r.status_code >= 400 else None
        if r.status_code == 200:
            return api.get(f"/interface/{reservation_id}/network").json()
        if r.status_code == 409 and code == 1001:
            wait = int(r.headers["Retry-After"])
            if remaining_seconds(api, reservation_id) <= wait:
                raise ReservationTooShort()
            sleep(wait)
            continue
        if r.status_code == 500 and code == 1003:
            raise ReservationInvalidated()  # Do not release this ID.
        raise CreateFailed(r.status_code, r.json())  # No automatic retry.
    raise CreateFailed("retries exhausted")
```

## 5. What happens on the server

The client sees only the outcome; the following is useful to interpret it.
Details and diagrams are in [Architecture](architecture.md).

- **Classified radio failures** include a `hostapd` crash (segfault), a timeout
  while preparing the radio, and an AP that does not reach the `ENABLED` state
  in time. After successful rollback the first two produce `409 / 1001`; the
  third invalidates the reservation (`500 / 1003`).
- **Unclassified failures** (for example `hostapd` exiting with code 1, a
  gateway, DHCP or captive portal startup error) are rolled back and return a generic `500`. They do not
  count as radio failures and do not invalidate the reservation.
- **Unsafe cleanup**: if Wi-Lab cannot roll back a failed start, it invalidates
  the reservation and quarantines the antenna immediately (`500 / 1003`), even
  on the first attempt.
- **Quarantine and USB recovery**: a quarantined USB antenna may be reset
  automatically in the background. Until it is verified, it is reported as
  `recovering` and cannot be reserved; other antennas stay available. See
  [Architecture](architecture.md#8-quarantine-and-automatic-usb-recovery) and the
  [manual recovery procedure](manual_recovery.md).
