# AP creation procedure

This guide is for developers of Wi-Lab API clients. It describes how to reserve
an antenna and start an access point (AP) on it, which responses to expect, and
exactly when a request may be repeated. For the server internals behind each
step, see [Architecture](architecture.md).

All endpoints are under `/api/v2` and require `Authorization: Bearer <token>`.
Every error body has the same envelope:

```json
{"detail": {"code": 1006, "reason": "device_busy", "message": "optional text"}}
```

Use the HTTP status and `detail.code` for control flow. `detail.message` is for
display only and can change between versions.

Every answer leads to **one of six actions** (done, wait, repeat, fix, reserve
again, stop). The complete list, for every call, is in
[3.1 What to do with each answer](#31-what-to-do-with-each-answer); radio
failures such as a hostapd crash are explained in
[3.2](#32-radio-failures-such-as-a-hostapd-crash).
Every error code, with its HTTP status and action, is also listed in
[Error codes](error-codes.md).

## 1. Reservation

An AP always runs on a reserved antenna. The reservation decides **which**
antenna you get and **how long** you may use it.

```http
POST /api/v2/reservations
Content-Type: application/json

{"duration_seconds": 600}
```

`duration_seconds: 0` asks for an unlimited reservation. It is accepted only
when the server allows it: `GET /api/v2/status` reports
`reservation_policy.allow_unlimited` (with `min_seconds` and `max_seconds`).
When it is `false`, `0` returns `422`.

To reserve a given antenna, add its `interface` (from `GET /api/v2/antennas`):

```json
{"duration_seconds": 600, "interface": "wlx7419f8176286"}
```

Without `interface` (or with `null`) the server picks the first free antenna.
With it, the server reserves that antenna or answers an error; it never gives
you another one. The answers below then concern that antenna only: `409 / 1005`
means it is reserved (`next_available_*` is the expiry of its reservation,
`null` if unlimited), `503 / 1002` and `503 / 1003` that it is being recovered
or quarantined. Leave `interface` out unless you need that antenna: you wait
less.

| Response | Meaning | Client action |
|---|---|---|
| `200` | Antenna reserved. Body has `reservation_id`, `interface`, `display_name`, `expires_at`, `expires_in`. | Keep `reservation_id`: every following call uses it. |
| `409 / 1005` | All antennas are reserved (an antenna whose cleanup failed counts as reserved until the server's next cleanup attempt). `detail.next_available_at` is the estimated availability in UTC; `detail.next_available_in` is the wait in seconds. Both are `null` when no release is scheduled. | Retry later with backoff, or wait for an unlimited reservation to be released. |
| `503 / 1002` + `Retry-After: 10` | No antenna can be assigned while an antenna is being recovered. | Retry **the reservation** after `Retry-After`. This is a polling interval, not a promise. |
| `503 / 1003` | No antenna has been discovered yet, or none is usable and recovery is not running. | If the pool is empty at startup, allow discovery time and check `/status` before reserving again. If antennas remain unavailable, ask an operator to investigate. |
| `422` | `duration_seconds` is outside the server limits, or `0` while unlimited reservations are disabled; or `interface` is not a managed antenna. | Fix the request. |

Rules that matter for the AP:

- The AP lives only as long as the reservation. Creating or restarting an AP
  **never extends** `expires_at`. When the reservation expires, Wi-Lab stops
  the AP and frees the antenna.
- Reservation and network `expires_at` values use RFC 3339 UTC with a `Z`
  suffix (e.g. `2026-11-19T23:00:00Z`). They are `null` for unlimited
  reservations. `expires_in` is a countdown in seconds.
- Without `interface`, the server picks the antenna (the first free one).
- Release the reservation when you are done:
  `DELETE /api/v2/reservations/{reservation_id}`. This also stops the AP;
  a separate network stop is not required. **The release never fails**: `200`
  means the ID is gone. If the server cannot clean the antenna (for example
  hostapd stuck in the kernel), it keeps the antenna out of the pool and
  repeats the cleanup by itself; the client does nothing.
- `GET /api/v2/reservations/{reservation_id}` returns the remaining time.
  `404` means the ID is no longer valid (expired, released or invalidated).

## 2. Creating the AP

### 2.1 Read what the antenna can use

The reservation answer names the antenna (`interface`). Ask what a network on
it can use; no reservation is needed, so a GUI can also show free antennas:

```http
GET /api/v2/antennas                 → every antenna: display_name, interface
GET /api/v2/antennas/{interface}     → device, encryptions, and per band the
                                       Wi-Fi generations, widths and channels
```

```json
{
  "display_name": "antenna-1",
  "interface": "wlx7419f8176286",
  "device": {"bus": "usb", "address": "2-1", "driver": "mt7921u"},
  "encryptions": ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"],
  "bands": {
    "2.4ghz": {
      "wifi_generations": [
        {"wifi_generation": 4, "channel_widths": [20, 40]},
        {"wifi_generation": 6, "channel_widths": [20, 40]}
      ],
      "channels": [
        {"channel": 1, "frequency_mhz": 2412, "max_power_dbm": 20.0, "dfs": false, "channel_widths": [20, 40]}
      ]
    },
    "5ghz": {
      "wifi_generations": [
        {"wifi_generation": 4, "channel_widths": [20, 40]},
        {"wifi_generation": 5, "channel_widths": [20, 40, 80]},
        {"wifi_generation": 6, "channel_widths": [20, 40, 80]}
      ],
      "channels": [
        {"channel": 36, "frequency_mhz": 5180, "max_power_dbm": 23.0, "dfs": false, "channel_widths": [20, 40, 80]},
        {"channel": 165, "frequency_mhz": 5825, "max_power_dbm": 13.0, "dfs": false, "channel_widths": [20]}
      ]
    }
  }
}
```

Fill a form in this order: band, then a generation of that band, then one of
its `channel_widths`, then a channel whose `channel_widths` contains that
width. Every combination built this way is accepted by the create. The only
extra rule is `wpa1`: 802.11n (`wifi_generation` 4) at 20 MHz only.

- **Only usable channels are listed.** Channels disabled by the regulatory
  domain, No-IR channels and 6 GHz channels (reported by some Wi-Fi 6E
  antennas; Wi-Lab cannot create a 6 GHz network) are not in the list.
- **`device`** says where the antenna is attached: `bus` is `usb`, `pci` (also
  cards built into the motherboard) or `sdio`; `address` is the USB port
  (`2-1.3`) or the PCI address (`0000:02:00.0`); `driver` is the kernel driver.
  It is `null` when sysfs does not show the device.
- **DFS channels** (5 GHz 52–144, shared with radar) are listed, with
  `dfs: true`, only when the antenna has `show_dfs: true` in `config.yaml`
  (`antennas[].show_dfs`, required for every listed antenna; antennas not
  listed in the configuration behave as `true`). When `false` they are not
  listed and a create asking for one returns `422`. Before transmitting on a
  DFS channel the radio listens for radar (CAC), usually about 60 seconds;
  Wi-Lab's startup timeout for 5 GHz channels 52–144 is 75 seconds, so longer
  checks can time out.
- **`404`**: no managed antenna has this interface. **`503`**: the radio
  cannot be read now (unplugged or being reset); retry later.

### 2.2 Build the request

```http
POST /api/v2/reservations/{reservation_id}/network
Content-Type: application/json

{
  "radio": {
    "band": "2.4ghz",
    "channel": 6,
    "channel_width": 20,
    "wifi_generation": 4,
    "tx_power_level": 4
  },
  "wifi": {
    "ssid": "lab-test-01",
    "hidden": false,
    "security": {"encryption": "wpa2", "password": "testpass123"}
  },
  "internet": {"enabled": true},
  "captive_portal": {"enabled": false}
}
```

The body has the same sections as `GET .../network`. Only `radio` and `wifi`
are required; `internet` and `captive_portal` can be omitted.

| Field | Required | Rules |
|---|---|---|
| `radio.band` | yes | `2.4ghz` or `5ghz`. An AP uses one band. |
| `radio.channel` | yes | Must be valid for `band` and supported and enabled on the antenna. |
| `radio.channel_width` | no | `20`, `40` or `80` MHz. Default `20`, the previous behavior. See [2.2.1](#221-encryption-channel-width-and-wi-fi-generation). |
| `radio.wifi_generation` | no | `4` (802.11n), `5` (802.11ac, 5 GHz only) or `6` (802.11ax). Default `4`, the previous behavior. |
| `radio.tx_power_level` | yes | `1` (low) to `4` (maximum). |
| `wifi.ssid` | yes | Network name: 1–32 bytes in UTF-8 (non-ASCII characters count as more than one byte), no control characters such as line breaks or tabs. |
| `wifi.hidden` | no | Default `false`. |
| `wifi.security.encryption` | yes | `open`, `wpa1`, `wpa2`, `wpa3` or `wpa2-wpa3`; see [2.2.1](#221-encryption-channel-width-and-wi-fi-generation). `wpa` is no longer accepted (`422`): use `wpa2`. |
| `wifi.security.password` | unless `open` | 8–63 bytes in UTF-8 for any WPA mode, no control characters. |
| `internet.enabled` | no | Default from the server configuration. Enables NAT to the upstream network. |
| `captive_portal.enabled` | no | Default `false`. Puts clients behind a simulated captive portal; see [2.7](#27-captive-portal). |

Validate the body on the client side when possible: an invalid body returns
`422` without touching the antenna. The message starts with the path of the
refused field, written with dots, for example `radio.channel_width: Input should
be 20, 40 or 80` or `wifi.security.password: wpa2 requires a password of 8 to 63
bytes (got 5)`. Rules between fields name the field they refuse (the password
for a short password, `radio.channel` for a channel outside the band,
`radio.channel_width` for a width the channel or the antenna cannot use), and
so do the antenna checks made before starting the AP.

#### 2.2.1 Encryption, channel width and Wi-Fi generation

Each antenna reports what it supports in `GET /api/v2/antennas/{interface}`
(see [2.1](#21-read-what-the-antenna-can-use)), read from the radio (`iw phy`).
A create that asks for anything else returns `422` without touching the
antenna.

| `wifi.security.encryption` | What hostapd runs | Notes |
|---|---|---|
| `open` | No encryption. | |
| `wpa2` | WPA2-Personal: PSK, CCMP. | What `wpa` used to create. |
| `wpa3` | WPA3-Personal: SAE, PMF required. | SAE accepts both hunting-and-pecking and H2E. |
| `wpa2-wpa3` | Mixed mode: PSK and SAE, CCMP. | WPA3 clients must use PMF, WPA2 clients do not. |
| `wpa1` | Legacy WPA: PSK, TKIP. | Only to test legacy clients. Insecure; TKIP forbids 802.11n, so the network is 802.11a/g at 20 MHz, at most 54 Mbit/s. Some recent clients warn or refuse to connect. Accepted only on antennas that list it (the driver must support TKIP). |

`wpa` is no longer accepted: it silently created WPA2, so a client that wanted
to test WPA1 was actually testing WPA2. It returns `422` with a message that
points to `wpa2` (same network as before) or `wpa1` (real legacy WPA).

**Channel width and Wi-Fi generation** are optional; the defaults (20 MHz,
802.11n) are the behaviour before 4.0.0, so existing clients do not change.

- `radio.wifi_generation: 5` (802.11ac) exists only on 5 GHz.
  `radio.channel_width: 80` exists only on 5 GHz and needs `wifi_generation` 5
  or 6. With `wpa1` only
  20 MHz and generation 4 are accepted.
- On 5 GHz a wide channel is a fixed block of 20 MHz channels: at 40 MHz
  36+40, 44+48, 52+56, ..., at 80 MHz 36–48, 52–64, 100–112, 116–128,
  132–144, 149–161, 165–177. `channel` is the primary channel inside the block.
  **Every channel of the block** must be enabled on the antenna: 165 at 80 MHz
  usually returns `422` because 169–177 are not allowed, and a block with DFS
  channels follows the antenna's `show_dfs`.
- On 2.4 GHz `channel_width: 40` is accepted: the second channel is 4 above
  (or 4 below when above is not available). It occupies most of the band, and
  hostapd falls back to 20 MHz when it sees neighbouring networks (20/40
  coexistence), which is common with several APs on. `GET .../network` reports
  the width the radio actually uses in `radio.channel_width.reported`.
- `wifi_generation: 6` (802.11ax) is accepted where the antenna supports
  802.11ax in AP mode. On 5 GHz it is announced together with 802.11ac.

### 2.3 Send it with the right timeout

Creating an AP is synchronous: the response arrives only when the AP is
broadcasting and DHCP is running, or when startup has failed and been rolled
back. A start normally takes about 0.5 s. If the radio fails (for example a
hostapd crash), Wi-Lab rolls it back and starts it again **inside the same
request**:

1. up to 3 starts, 1 s apart, within 20 s: about 3 s with one retry, 5–6 s
   with two;
2. if they all failed, one more start after a 5 s pause;
3. if that failed too, a last start after a 10 s pause.

**The client does nothing during these starts**: it only waits for the
answer. A pause is skipped, and the create answers `503 / 1003`, only when the
reservation would expire before the next start ends. Configure the HTTP client
with a long read timeout so that a slow start is not mistaken for a failure:

| Channel | Usual answer | Worst case | Suggested read timeout |
|---|---|---|---|
| 2.4 GHz and non-DFS 5 GHz | 0.5–6 s | about 80 s | at least 120 s |
| DFS 5 GHz (52–144) | about 60 s (radar check) | about 4 min | at least 300 s |

These are client recommendations, not server guarantees.

**Send only one create at a time per reservation.** Wi-Lab serializes work per
antenna, so parallel requests for the same reservation only queue up.

### 2.4 Handle the response

The actions for every call, in one place, are in [3.1](#31-what-to-do-with-each-answer).

| Response | Meaning | Client action |
|---|---|---|
| `200` | The AP is up and DHCP is running. The body is the network, as `GET .../network` returns it. | Done. Stop retrying. |
| `409 / 1008` (`network_already_active`) | An AP with **different** settings is already running on this reservation (the same create again answers `200`). | Do not retry. Read it with `GET .../network`, or stop it first with `DELETE .../network`. |
| `409 / 1009` (`restoration_in_progress`) | The watchdog is restarting this AP. | Do not create. Poll `GET .../network` until `runtime_state` is gone. |
| `422` | Invalid body (including `encryption: wpa`), channel unsupported/disabled on this antenna, or an encryption, channel width or Wi-Fi generation the antenna does not support. | Fix the request. Do not retry the same body. |
| `404` | The reservation is unknown, expired or invalidated. | Stop using the ID. Reserve again if needed. |
| `503 / 1003` | **Terminal failure.** Every start failed (the antenna was quarantined), or the reservation expires too soon for another start; the reservation is **invalidated**. | Discard the ID. Do not retry creation and do not release it. Reserve again if needed. |
| `500 / 1013` (`startup_failed`) | A non-radio startup error. `detail.stage` says what failed: `hostapd` (e.g. exit code 1), `interface`, `gateway`, `dhcp`, `captive_portal`, `nat`, `internet_block`, `isolation` or `host_guard`. The rollback succeeded and the reservation is **still valid**. | Do not retry automatically. Show `detail.message`. Release the ID if abandoning this attempt; release it before asking for a fresh reservation. |
| `401` | Missing or invalid token. | Fix the token. |

The create waits for the adapter if another request on it is running, so it
never returns `503 / 1006`; the other reservation endpoints do (see
[2.6](#26-after-the-ap-is-running)).

After `500 / 1013`, `DELETE /api/v2/reservations/{id}`
releases the still-held antenna on `200`. The next reservation may get the same
antenna or a different one. Do not implement release → reserve → create as an
automatic recovery loop. In contrast, after
`503 / 1003` the ID is already invalidated and must not be released.

### 2.5 When and how to retry

**No create error authorizes an automatic retry.** Radio failures are retried
by the server inside the request (2.3); the client never repeats a create
because of them. Further rules:

- **Reuse the same ID.** A new reservation while this one is held leaves this
  antenna held until it expires.
- **Do not count your own retries on top of the server's.** The answer is
  already the final result of every start the server tried.
- **After a transport error, send the same create again.** If the connection
  drops or the client times out, the server may have finished the AP or still
  be working on it. Repeating the **same** create (same ID, same body) is safe:
  it waits for a create still in progress, and if the AP already runs with
  exactly those settings it answers `200` with the network instead of starting
  it twice. Then handle the answer as usual (`404`: the ID is gone, the
  previous create invalidated it).

### 2.6 After the AP is running

- **No network: `409 / 1007`.** Internet, TX power and QoS profile requests
  on a valid reservation that has no running network return `409` with
  `detail.code: 1007` (`network_not_active`). Create a network first. A `404`
  on these endpoints always means the reservation itself is unknown, expired
  or invalidated.
- **Adapter busy: `503 / 1006`.** Every request on a reservation other than
  the create (`GET`/`DELETE .../network`, Internet,
  TX power, QoS profile) waits at most **5 s** for another operation on the
  same adapter, such as a network start (up to 20 s, 75 s on a DFS channel).
  After that it returns `503` with `detail.code: 1006`,
  `reason: device_busy` and `Retry-After: 2`. Nothing was changed: repeat the
  same request after `Retry-After`. A create never returns `1006`: it waits
  for the adapter.

  ```json
  HTTP/1.1 503 Service Unavailable
  Retry-After: 2

  {"detail": {"code": 1006, "reason": "device_busy",
              "message": "Another operation on this adapter is still running; retry after Retry-After"}}
  ```

- `GET /api/v2/reservations/{reservation_id}/network` returns the network in
  sections:

  ```json
  {
    "interface": "wlx7419f8176286", "active": true, "runtime_state": null,
    "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 3471},
    "radio": {
      "band": "5ghz", "channel": 36,
      "channel_width": {"requested": 80, "reported": 80},
      "wifi_generation": 5,
      "tx_power": {"requested_level": 4, "reported_level": 4, "reported_dbm": 20.0}
    },
    "wifi": {"ssid": "lab-test-01", "hidden": false,
             "security": {"encryption": "wpa2", "password": "testpass123"}},
    "ip": {"subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
           "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"},
           "dns_server": "192.168.10.21"},
    "internet": {"enabled": true},
    "captive_portal": {"enabled": false, "url": null},
    "clients": [{"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.10"}]
  }
  ```

  | Section | Content |
  |---|---|
  | `reservation` | `expires_at` (UTC) and `expires_in` (seconds); always present. |
  | `radio` | Band, channel, channel width (`requested`, and `reported` by the radio: lower when hostapd fell back to 20 MHz on 2.4 GHz), Wi-Fi generation, TX power. |
  | `wifi` | SSID, hidden flag, `security` (encryption and password, returned so test devices can be connected). |
  | `ip` | Subnet, gateway, DHCP range and the DNS server announced to clients. |
  | `internet`, `captive_portal` | Whether NAT is enabled; whether the portal is on, and its URL. |
  | `clients` | Connected clients (`mac`, `ip`, and `captive_authorized` with a portal). The count is the list length. |

  While the network is not running, or while the watchdog restores it, only
  `interface`, `active`, `runtime_state` and `reservation` are set; the other
  sections are `null`.
- Wi-Lab's watchdog checks every running AP about every 5 seconds and restarts
  it with the same settings and reservation, up to 3 times per hour per
  antenna; a fourth failure within the hour quarantines the antenna. While this
  happens, `GET .../network` and `GET /api/v2/status` report `runtime_state`:

  | `runtime_state` | Meaning | Client action |
  |---|---|---|
  | `restoring_ap` | The AP is being restarted. Clients will need to reconnect. | Wait. Do not send a create. |
  | `restoring_dhcp` | Only DHCP is being restarted. The AP stays up. | Wait. |
  | `dhcp_failed` | DHCP could not be repaired alone (a restart failed, or dnsmasq died more than 3 times in an hour). Within 5 s the watchdog restarts the whole network (`restoring_ap`). | Wait. |
  | `restore_failed` | The AP restart failed for a non-radio reason. The AP is down (`active: false`); the watchdog retries after 15 s, 30 s, 60 s, 120 s, then every 5 minutes while the reservation is valid. | Wait for `runtime_state` to clear, or `DELETE .../network` to stop the retries (the reservation stays valid), or create a new network. |
  | `stop_failed` | After a `DELETE .../network` answered `503 / 1012` (also in `GET /status`): the stop did not complete, usually because hostapd stayed stuck in the kernel for a few seconds after a driver firmware timeout. The network is half stopped and the watchdog leaves it alone. | Repeat `DELETE .../network` after `Retry-After` (5 s). |

- An AP restart clears traffic shaping and QoS profiles: reapply them after a
  `restoring_ap` phase.
- If the restart fails because of the radio (including a hostapd crash on
  every internal start), or the AP fails more than 3 times in an hour, the
  antenna is quarantined and the reservation is invalidated **at once**, with
  no notification. The next call
  with the ID returns `404`: reserve again (see
  [3.2](#32-radio-failures-such-as-a-hostapd-crash)). If the restart fails for
  another reason, the reservation stays valid and `runtime_state` is
  `restore_failed` until a retry succeeds.
- `GET /api/v2/status` reports `recovery_state` (`recovering` or `unavailable`)
  for quarantined antennas. They can show `reservation: null` but are **not**
  allocatable.
- To stop the AP but keep the antenna: `DELETE .../network`. To finish: release
  the reservation.

### 2.7 Captive portal

With `"captive_portal": {"enabled": true}`, each client that joins the AP is held behind a
simple portal until it signs in. Use it to check how a device detects a
captive network. Without the flag, nothing changes.

Until the client signs in:

- DNS queries are answered by the AP with the gateway address, so connectivity
  checks resolve and reach the portal even when `internet.enabled` is `false`.
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
network's normal Internet setting: with `internet.enabled: false` it stays
offline. `GET .../network` reports `captive_portal.enabled`, `captive_portal.url`
and, for each client, `captive_authorized`.

Notes:

- Clients are detected through their HTTP connectivity checks. Wi-Lab does not
  advertise the portal via DHCP option 114 (RFC 8910) and does not intercept
  HTTPS.
- A client that obtains a new IP address, or changes its MAC address, must
  sign in again. Sign-ins are cleared when the AP stops, the reservation ends
  or the watchdog restarts the AP.
- The portal listens on port 80 and dnsmasq answers DNS on port 53, both on
  the AP gateway address only.

### 2.8 Service health: `degraded` and quarantined antennas

The client must check `GET /api/v2/status` to know whether every antenna is
usable. Poll it (for example every 10–30 s) and show the result to the user.

| `status` | Meaning |
|---|---|
| `standby` | No AP is active and no antenna is quarantined. |
| `ok` | APs are active and every health check passes. |
| `degraded` | At least one entry in `degraded_reasons`. |

`degraded_reasons` says why, with a stable `code` and the `interface` it
concerns (`null` for the whole service); `antennas[]` gives the state of each
antenna:

```json
{
  "status": "degraded",
  "degraded_reasons": [
    {"code": "antenna_quarantined", "interface": "wlx7419f8176286",
     "message": "Antenna quarantined (unavailable)"}
  ],
  "antennas": [
    {"display_name": "antenna-1", "interface": "wlx7419f8176286", "reservation": null,
     "network_active": false, "recovery_state": "unavailable"},
    {"display_name": "antenna-2", "interface": "wlx7419f817651c",
     "reservation": {"expires_at": "2026-11-19T23:00:00Z", "expires_in": 540},
     "network_active": true}
  ]
}
```

| `degraded_reasons[].code` | Meaning | Client action |
|---|---|---|
| `antenna_quarantined` | The antenna has `recovery_state`: `recovering` (Wi-Lab is resetting and probing it) or `unavailable` (no USB reset running; re-probed after 30 s, backing off to every 15 min). | Do not count it as available. It may return by itself; report it if `unavailable` persists. |
| `network_being_repaired` | A reserved AP has `runtime_state`: `restoring_ap`, `restoring_dhcp`, `dhcp_failed` (whole network restarted within 5 s) or `restore_failed` (AP down, retried with backoff). See [2.6](#26-after-the-ap-is-running). | Owner: wait (or `DELETE .../network` on `restore_failed`). Others: nothing to do. |
| `network_stop_incomplete` | A `DELETE .../network` on that antenna answered `503 / 1012`: the network is half stopped (`runtime_state: stop_failed`). | Its owner repeats the DELETE; others do nothing. |
| `hostapd_not_running`, `dnsmasq_not_running` | The AP or DHCP process of that network is not alive. | Report it; the watchdog normally repairs it within seconds. |
| `nat_rule_missing` | That network has Internet enabled but lost its NAT rule. | Report it; Internet does not work there until the watchdog repairs it. |
| `upstream_unreachable` | The host uplink is down or has no IPv4 address, while a network has Internet. | Report it; Internet access does not work. |
| `command_stuck` | A host command (`ip`, `iw`, `usbreset`, ...) did not exit even after SIGKILL: usually a hung Wi-Fi driver. Set in standby too. | Report it: the adapter may need a reset or the host a reboot. |
| `loop_stalled` | A Wi-Lab background loop has not run for 3 minutes. Wi-Lab restarts itself as soon as no reservation is active. | Report it; release reservations you no longer need. |
| `cleanup_failed` | The cleanup after a release or expiry failed (for example hostapd stuck in the kernel). The antenna is held, not reservable; Wi-Lab repeats the cleanup after 5 s, 15 s, 60 s, then every 5 minutes. | Nothing: reserve another antenna, or wait. If it persists, an operator checks the host. |

The checks that run host commands are refreshed every 10 s in the background,
so a problem can take up to 10 s to appear. The detail of every check
(processes, NAT rules, upstream link, stuck commands, stalled loops, time of
the last check) is in `GET /api/v2/monitoring`, for operators and monitoring
views; clients only need `/status`.

- Each antenna has `reservation` (`null` when no reservation holds it;
  `{expires_at, expires_in}` otherwise, both `null` when unlimited) and
  `network_active` (a network runs on it).
- `reservation: null` does **not** mean the antenna can be reserved: an entry
  with `recovery_state` is excluded from allocation.
- How a client learns that *its* antenna was quarantined: the create returns
  `503` with `detail.code: 1003`, `reason: device_unavailable` and
  `reservation_invalidated: true`. From then on the reservation ID returns
  `404`. There is no other notification: discard the ID and reserve again.
- New reservations skip quarantined antennas silently while another antenna is
  free. When none is allocatable because of quarantine, reserve returns `503`
  with `1002` (recovery in progress, retry after `Retry-After`) or `1003`
  (nothing is recovering).

## 3. Sequence diagram

The whole client flow, from the reservation to the release, with every answer
a client must handle (the same answers, one action each, are listed in
[3.1](#31-what-to-do-with-each-answer)). `id` is the `reservation_id`; every call carries
`Authorization: Bearer <token>` (a `401` anywhere means a wrong token: fix it,
never retry). Phases 4 and 5 are optional; the release (phase 6) also stops the
AP.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant W as Wi-Lab API

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 0 - before reserving (optional, no reservation needed)
    C->>W: GET /status
    W-->>C: status, antennas[] (reserved, recovery_state), reservation_policy
    Note over C: allow_unlimited tells whether duration_seconds 0 is accepted.<br/>Entries with recovery_state are not allocatable.
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 1 - reserve an antenna
    loop Until 200, or until the client gives up
        C->>W: POST /reservations {duration_seconds, interface (optional)}
        alt 200
            W-->>C: reservation_id, interface, display_name, expires_at, expires_in
            Note over C: Keep id and interface. Leave the loop
        else 409 / 1005 all antennas reserved (with interface: that antenna)
            W-->>C: next_available_at, next_available_in (null if no release is scheduled)
            Note over C: Automatic retry allowed: wait next_available_in<br/>(or a backoff of 10 to 60 s when null), then repeat
        else 503 / 1002 + Retry-After 10
            W-->>C: an antenna is being recovered, nothing allocatable now
            Note over C: Automatic retry allowed: wait Retry-After, then repeat
        else 503 / 1003
            W-->>C: no antenna discovered or usable, no recovery running
            Note over C: Right after a service start: wait for discovery (up to 30 s),<br/>check GET /status, then retry. With interface: that antenna is quarantined,<br/>reserve without interface. Otherwise stop and ask an operator
        else 422
            W-->>C: duration outside min/max, 0 while unlimited is off, or unknown interface
            Note over C: Fix the body. Never repeat the same body
        end
    end
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 2 - read what the antenna can use (no reservation needed)
    C->>W: GET /antennas/{interface}
    alt 200
        W-->>C: device, encryptions, bands: wifi_generations (widths) and usable channels (widths)
        Note over C: Build the body: band, then generation, then width,<br/>then a channel whose channel_widths contains that width.<br/>wpa1 only with wifi_generation 4 at 20 MHz
    else 503
        W-->>C: the radio cannot be read now (unplugged, being reset)
        Note over C: Retry after a few seconds, or create with the defaults (20 MHz, 802.11n)
    else 404
        W-->>C: no managed antenna has this interface
        Note over C: Should not happen with an interface from the reservation: reserve again
    end
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 3 - create the AP (one request, read timeout 120 s, 300 s on DFS)
    loop Only after a lost answer (see the last branch)
        C->>W: POST /reservations/{id}/network {radio, wifi, internet, captive_portal}
        Note over W: Waits for the antenna (never 1006). Prepares the radio, starts hostapd,<br/>waits for the AP (20 s, 75 s on DFS), gateway, DHCP, NAT, isolation.<br/>Radio failure: up to 3 starts within 20 s, then one after 5 s, then one after 10 s
        alt 200
            W-->>C: the network, as GET .../network returns it
            Note over C: Done. Leave the loop
        else 503 / 1003
            W-->>C: reservation_invalidated true (every start failed: antenna quarantined,<br/>or the reservation expires too soon for another start)
            Note over C: Terminal. Discard the id, do NOT release it.<br/>Reserve again (phase 1)
        else 422
            W-->>C: message starts with the field path (radio.channel: ..., wifi.security.password: ...)
            Note over C: Fix that field. Never repeat the same body
        else 409 / 1008 network_already_active
            W-->>C: an AP with different settings already runs on this reservation
            Note over C: The same body would have answered 200.<br/>Read it with GET .../network, or DELETE .../network first
        else 409 / 1009 restoration_in_progress
            W-->>C: the watchdog is restarting this AP
            Note over C: Do not create. Poll GET .../network until runtime_state is null
        else 404
            W-->>C: reservation unknown, expired, released or invalidated
            Note over C: Discard the id. Reserve again if needed
        else 500 / 1013 startup_failed
            W-->>C: detail.stage (hostapd, interface, gateway, dhcp, nat, isolation, ...) and message
            Note over C: Rolled back, reservation still valid. No automatic retry.<br/>Show the message. Release the id before reserving again
        else transport error or client timeout (no answer)
            Note over C: The server may have finished, or still be working.<br/>Send the SAME create again (same id, same body): it waits for a create<br/>in progress, and an AP already running with that body answers 200
        end
    end
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 4 - while the AP is in use
    par Owner polls its network (every 5 to 30 s)
        C->>W: GET /reservations/{id}/network
        alt 200, runtime_state null
            W-->>C: active, radio, wifi, ip, internet, captive_portal, clients, reservation
        else 200, runtime_state restoring_ap
            W-->>C: active false, sections null: the AP is being restarted
            Note over C: Wait. Clients must reconnect. Reapply QoS profiles afterwards
        else 200, runtime_state restoring_dhcp or dhcp_failed
            W-->>C: DHCP is being repaired, the whole network restarts within 5 s if needed
            Note over C: Wait
        else 200, runtime_state restore_failed
            W-->>C: AP down, the watchdog retries (15 s, 30 s, 60 s, 120 s, then every 5 min)
            Note over C: Wait, or DELETE .../network to stop the retries, or create again
        else 200, runtime_state stop_failed
            W-->>C: a previous stop did not complete
            Note over C: Repeat DELETE .../network (phase 5)
        else 503 / 1006 + Retry-After 2
            W-->>C: another operation holds the antenna, nothing changed
            Note over C: Automatic retry allowed after Retry-After
        else 404
            W-->>C: expired, released or invalidated (quarantine)
            Note over C: The AP is gone. Reserve again if needed
        end
    and Anyone polls the service (every 10 to 30 s)
        C->>W: GET /status
        W-->>C: ok, degraded or standby, degraded_reasons, recovery_state, runtime_state
        Note over C: Show degraded with the affected antenna
    end
    opt Change the running network
        C->>W: POST .../internet/enable or disable, POST .../txpower, POST or DELETE .../qos/profile
        alt 200
            W-->>C: applied
        else 409 / 1007
            W-->>C: no running network on this reservation
            Note over C: Create the network first
        else 503 / 1006 + Retry-After 2
            W-->>C: antenna busy, nothing changed
            Note over C: Automatic retry allowed after Retry-After
        else 404
            W-->>C: reservation gone
        end
    end
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 5 - stop the AP and keep the reservation (optional)
    loop Until 200, 409 / 1007 or 404
        C->>W: DELETE /reservations/{id}/network
        alt 200
            W-->>C: stopped (also cancels the retries of restore_failed)
        else 409 / 1007
            W-->>C: already inactive
        else 503 / 1006 + Retry-After 2
            W-->>C: antenna busy, nothing changed
            Note over C: Automatic retry allowed after Retry-After
        else 503 / 1012 + Retry-After 5
            W-->>C: stop not completed even after 15 s of server retries, runtime_state stop_failed
            Note over C: Automatic retry allowed: repeat the DELETE after Retry-After.<br/>The watchdog leaves the half-stopped network alone
        else 404
            W-->>C: reservation gone (the AP was stopped with it)
        end
    end
    end

    rect rgba(128,128,128,0.08)
    Note over C,W: Phase 6 - release (also stops the AP), or let the reservation expire
    C->>W: DELETE /reservations/{id}
    alt 200
        W-->>C: released (always, even if the cleanup failed: then the server<br/>keeps the antenna out of the pool and repeats the cleanup by itself)
    else 404
        W-->>C: already expired, released or invalidated
        Note over C: Nothing to do
    end
    Note over W: At expires_at Wi-Lab stops the AP and frees the antenna without any call.<br/>Creating or restarting an AP never extends the reservation
    end
```

### 3.1 What to do with each answer

Every answer leads to exactly one of these actions:

| Action | Meaning |
|---|---|
| **DONE** | Success. Go on. |
| **WAIT** | The server is working on it. Send nothing that changes the network; read the state again (`GET .../network`) every few seconds. |
| **REPEAT** | Send the **same** request again (same ID, same body) after `Retry-After`. Automatic retries are allowed only here. |
| **FIX** | The request is wrong. Change it; never resend the same one. |
| **RESERVE AGAIN** | The reservation ID is gone. Stop using it, **do not release it**, and reserve again (`POST /reservations`) if you still need an AP. You may get another antenna. |
| **STOP** | A problem the client cannot solve. Show `detail.message`, check `GET /status`, and ask an operator. No automatic retry. |

| Call | Answer | Action | Notes |
|---|---|---|---|
| any | `401` | FIX | Wrong or missing token. |
| any call with an ID, except the release | `404` | RESERVE AGAIN | The ID expired, was released, or was **invalidated** because its antenna was quarantined (radio failures, also during a watchdog restart). Never release it. |
| any call with an ID except the create | `503 / 1006` + `Retry-After: 2` | REPEAT | Another operation holds the antenna. Nothing was changed. |
| `POST /reservations` | `200` | DONE | Keep `reservation_id` and `interface`. |
| | `409 / 1005` | REPEAT | All antennas reserved (with `interface`: that one). Wait `next_available_in`, or a backoff of 10–60 s when it is `null`. |
| | `503 / 1002` + `Retry-After: 10` | REPEAT | An antenna is being recovered. |
| | `503 / 1003` | STOP | No usable antenna. Right after a service start, wait up to 30 s for discovery and check `GET /status` first. With `interface`: that antenna is quarantined; reserve without it. |
| | `422` | FIX | `duration_seconds` out of limits, `0` while unlimited reservations are off, or `interface: ...` not a managed antenna. |
| `GET /antennas/{interface}` | `503` | REPEAT | After a few seconds; the radio is being reset. Or create with the defaults. |
| | `404` | RESERVE AGAIN | The antenna is no longer managed. |
| `POST .../network` (create) | `200` | DONE | The body is the network, as `GET .../network` returns it. |
| | `503 / 1003` | RESERVE AGAIN | Every start failed (the server already retried), or the reservation expires too soon for another start: reservation invalidated. **Do not release it.** |
| | `422` | FIX | The message starts with the field path, e.g. `radio.channel_width: ...`. |
| | `409 / 1008` | FIX | An AP with **different** settings already runs on this reservation (the same body answers `200`). Read it with `GET .../network`; to replace it, `DELETE .../network` first. |
| | `409 / 1009` | WAIT | Until `runtime_state` is `null`, then create only if `active` is `false`. |
| | `500 / 1013` | STOP | Startup failed for a non-radio reason (`detail.stage`) and was rolled back; the reservation is still valid. Release it before reserving again. |
| | `500 / 500` | STOP | An unexpected server error. |
| | no answer (timeout, connection lost) | REPEAT | Send the **same** create again (same ID, same body), at once: it waits for a create still in progress, and an AP already running with that body answers `200`. Then handle the new answer. |
| `GET .../network` | `200`, `runtime_state: null` | DONE | |
| | `200`, `restoring_ap`, `restoring_dhcp`, `dhcp_failed` | WAIT | The watchdog is repairing the network. After `restoring_ap`, devices reconnect and QoS profiles must be reapplied. |
| | `200`, `restore_failed` | WAIT | The AP is down and the watchdog retries. Or `DELETE .../network` to give up, or create again. |
| | `200`, `stop_failed` | REPEAT | Repeat the `DELETE .../network` that answered `503 / 1012`. |
| Internet, TX power, QoS | `409 / 1007` | FIX | No running network: create it first. |
| | `422` | FIX | Includes a TX power the driver does not support and an unknown QoS `profile_id`. |
| QoS profile start | `409 / 1010` | FIX | A profile already runs: stop it first. |
| QoS profile stop | `409 / 1011` | DONE | No profile runs. |
| `DELETE .../network` | `200` | DONE | The reservation stays. |
| | `409 / 1007` | DONE | Already inactive. |
| | `503 / 1012` + `Retry-After: 5` | REPEAT | The stop did not complete, even after the server repeated it for 15 s (hostapd stuck in the kernel). Rare. Repeat until `200`. |
| `DELETE /reservations/{id}` | `200` | DONE | Always, even if the cleanup failed: the server then keeps the antenna out of the pool and repeats the cleanup by itself. |
| | `404` | DONE | Already expired, released or invalidated: nothing left to release. |

### 3.2 Radio failures (such as a hostapd crash)

The client never needs to know **why** the radio failed (hostapd crash,
driver firmware timeout, unplugged adapter): the answer code is enough. What
happens, from the most to the least common case:

1. **The server absorbs it: WAIT.** Wi-Lab starts the AP again by itself
   inside the create: up to 3 times within 20 s, then after 5 s and after
   10 s. The create just takes longer and answers `200`. The same holds for a
   watchdog restart of a running AP: `GET .../network` shows `restoring_ap`,
   then `runtime_state: null`. Nearly every hostapd crash ends here.
2. **The reservation is invalidated: RESERVE AGAIN.** It happens when:
   - every start of the create failed, or the reservation expires too soon
     for another start: the create answers `503 / 1003`;
   - a watchdog restart of a running AP fails on every internal start, or the
     AP fails for the fourth time in an hour: there is **no** answer to wait
     for, the next call with the ID answers `404`.

   In both cases the antenna is quarantined (`recovery_state` in
   `GET /status`). Do not release the ID; a new reservation gets another
   antenna.

A client that maps the answers with the table in 3.1 handles both cases
without special code for crashes.

## 4. Reference client logic

```python
def create_ap(api, reservation_id, body):
    for _ in range(3):  # the same create again only after a lost answer
        try:
            r = api.post(f"/reservations/{reservation_id}/network", json=body, timeout=300)
        except TransportError:
            continue  # Safe: the same body answers 200 if the AP already runs.

        code = r.json().get("detail", {}).get("code") if r.status_code >= 400 else None
        if r.status_code == 200:
            return r.json()  # the network, as GET .../network returns it
        if r.status_code == 503 and code == 1003 or r.status_code == 404:
            raise ReservationInvalidated()  # Do not release this ID: reserve again.
        raise CreateFailed(r.status_code, r.json())  # No automatic retry.
    raise CreateFailed("no answer after 3 tries")
```

## 5. What happens on the server

The client sees only the outcome; the following is useful to interpret it.
Details and diagrams are in [Architecture](architecture.md).

- **Classified radio failures** include a `hostapd` crash (segfault), a beacon
  rejected during interface setup, a timeout while preparing the radio, and an
  AP that does not reach the `ENABLED` state in time. They are radio failures in
  every create. The server retries them inside the request (up to 5 starts);
  if all fail, the reservation is invalidated (`503 / 1003`).
- **Unclassified failures** (for example `hostapd` exiting with code 1, a
  gateway, DHCP or captive portal startup error) are rolled back and return
  `500 / 1013` (`startup_failed`) with the failed `stage`. They do not count as radio failures and do not invalidate the
  reservation.
- **Unsafe cleanup**: if Wi-Lab cannot roll back a failed start, it invalidates
  the reservation and quarantines the antenna immediately (`503 / 1003`),
  without further starts.
- **Quarantine and USB recovery**: a quarantined USB antenna may be reset
  automatically in the background. Until it is verified, it is reported as
  `recovering` and cannot be reserved; other antennas stay available. See
  [Architecture](architecture.md#8-quarantine-and-automatic-usb-recovery) and the
  [manual recovery procedure](architecture.md#82-manual-recovery).
