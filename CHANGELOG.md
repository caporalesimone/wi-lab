# Changelog

All notable changes to Wi-Lab are documented in this file.

---

## [4.0.0] - 2026-11-20

### 📊 Statistics

| Item | Count |
|---|---:|
| 🐛 Bug fixes | 55 |
| ⚠️ Breaking changes | 22 |
| 🔧 Maintenance changes | 13 |
| ✨ New features | 21 |
| 📦 Commits since 3.0.0 | 89 |

Counts are the entries of the sections below (as of 2026-11-25) and `git rev-list --count 3.0.0..HEAD` (as of 2026-11-25).

### ⚠️ Breaking Changes

- Reservation contention returns null availability estimates when no release is scheduled.
- AP creation requires a single 2.4 GHz or 5 GHz band; `dual` returns 422.
- Release all reservations moved from `DELETE /api/v1/device-reservation` to `DELETE /api/v2/reservations/all`, and now requires the `X-Confirm-Password` header matching the new `protected_commands_password` setting (disabled when unset). A malformed single-release URL can no longer release everything.
- All `/api/v2` error bodies now use an object with `detail.code` and `detail.reason`. Clients displaying a former string `detail` should read `detail.message`. Recovery codes 1002–1003 are unchanged; 1001 is no longer answered (see below).
- API timestamps (`expires_at`, `detail.next_available_at`) now use RFC 3339 UTC with a `Z` suffix. Durations and countdowns remain in seconds.
- Internet, TX power and QoS profile requests on a valid reservation without a running network return `409` with `detail.code: 1007` (`network_not_active`); Internet and TX power returned `404`, which clients could not tell apart from an expired reservation (Fable API-2).
- A create that quarantines the adapter and invalidates the reservation (`detail.code: 1003`, `reservation_invalidated: true`) now returns `503` instead of `500`, so clients and proxies no longer treat it as a retryable server error; the code and body are unchanged (Fable API-4).
- The create body and `GET .../network` are grouped in sections: `radio`, `wifi` (with `security`), `internet`, `captive_portal`, plus `reservation` and `ip` in the answer. Duplicated and internal fields (`dhcp.*` paths and files, `clients_connected`, the second `interface` and `subnet`) are gone, and `ip.dns_server` is new. Flat bodies return `422` (Fable API-8; first step of ARCH-3).
- AP creation with `encryption: "wpa"` returns `422`: it silently created WPA2. Use `wpa2` for the same network, or the new `wpa1` for real legacy WPA/TKIP (Fable HAP-10).
- Configuration: the `networks` section is renamed `antennas`, and every entry must set `show_dfs: true|false`; there is no fallback for the old name.
- `GET /api/v1/interface/{id}/network/available-channels` is removed: use `GET /api/v2/antennas/{interface}`, which lists only the usable channels, grouped by band with the widths each can use, and needs no reservation.
- `GET /api/v2/status` no longer returns `checks`: it gives `degraded_reasons`, one entry per cause of `degraded` with a stable `code` (`antenna_quarantined`, `network_being_repaired`, `hostapd_not_running`, `dnsmasq_not_running`, `nat_rule_missing`, `upstream_unreachable`, `command_stuck`, `loop_stalled`, `cleanup_failed`), the `interface` it concerns and a `message`. The detail of the checks moved to the new `GET /api/v2/monitoring`.
- Every `409` has a `detail.code` (Fable API-3): `1008 network_already_active` and `1009 restoration_in_progress` on the create, `1007 network_not_active` on stopping a stopped network, `1010 qos_profile_already_active` and `1011 qos_profile_not_active` on QoS profiles; before they had none and the client had to read the message. `404` on a call with a reservation ID now only means the ID is gone: an unknown QoS `profile_id` and a TX power the driver does not support answer `422` (were `404`), stopping a QoS profile that is not running answers `409 / 1011` (was `404`).
- A create that fails for a non-radio reason answers `500 / 1013` (`startup_failed`) with `detail.stage` (`hostapd`, `interface`, `gateway`, `dhcp`, `captive_portal`, `nat`, `internet_block`, `isolation`, `host_guard`) instead of a generic `500 / 500` with only a message.
- Unknown fields in a request body are refused with `422` and the field path (`captive-portal: Extra inputs are not permitted`, `radio.chanel: ...`) instead of being ignored: a typo no longer creates a network without the intended setting (Fable API-10). Applies to the reservation, the create (every section), TX power and QoS profile bodies.
- The API prefix is `/api/v2` (was `/api/v1`): the contract changed, so the version in the URL changes too. `/api/v1` is not kept: every path under it answers `404`, with any method.
- Paths renamed (Fable API-6): `/api/v1/device-reservation` → `/api/v2/reservations`, and every `/api/v1/interface/{reservation_id}/...` → `/api/v2/reservations/{reservation_id}/...` (network, Internet, TX power, QoS profile). The old `interface` segment held a reservation ID, not an interface, which the new `/antennas/{interface}` would have made more confusing. The old paths answer `404`.
- The create no longer answers `409 / 1001` (`retry_later`) after a radio failure (such as a hostapd crash): the server takes the same pauses (5 s, then 10 s) and starts the AP again inside the request, so the client sends one create and gets `200` or a terminal `503 / 1003`. `1003` also comes, without quarantine, when the reservation expires too soon for another start. The create can take up to about 80 s (several minutes on DFS channels): use a read timeout of at least 120 s (300 s on DFS).
- The release (`DELETE /api/v2/reservations/{id}`, and release-all) always answers `200`: if the cleanup fails (for example hostapd stuck in the kernel) the ID is gone anyway, the antenna stays held and the server repeats the cleanup in the background (5 s, 15 s, 60 s, then every 5 min), shown in `GET /status` as `cleanup_failed`. Reserve, get and release no longer answer `503 / 1004`: a held antenna counts as reserved (`409 / 1005`, with `next_available_in` until the next cleanup attempt, also when reserved by `interface`) and the get of a released ID answers `404`.
- A successful create answers the network, the same body as `GET .../network`, instead of `{"detail": "Network ... created successfully"}`: the client no longer needs a second call (Fable API-5).
- `GET /api/v2/status` lists the antennas in `antennas[]` (was `networks[]`), like the Antennas API: an entry is an antenna, reserved or not, not a network.
- Every **Maintenance** endpoint requires the `X-Confirm-Password` header, like release-all: `GET /api/v2/debug` now returns `403` without it, or when `protected_commands_password` is not set.

### ✨ Features

- Add an optional captive portal to AP creation (`captive_portal`). Its sign-in button releases only the client that pressed it.
- DFS channels (5 GHz 52–144) are chosen per antenna with `antennas[].show_dfs`: when `false` they are not listed and AP creation on them returns `422`; antennas not listed in the configuration offer them.
- Run backend tests, type checks and the frontend build in CI and publish API documentation.
- Export the current API schema and offline Swagger/ReDoc documentation.
- Explain adapter-dependent TX power control in the frontend.
- Skip AP subnets that overlap host IPv4 routes when selecting a DHCP subnet.
- Add an optional offline configuration check with actionable errors and warnings.
- Allow clients to retry classified radio startup failures using the same reservation after `Retry-After`. A terminal creation failure returns `503 / 1003` and invalidates the reservation. New reservations still return `503` when blocked by recovery or quarantine.
- Restart failed active access points or DHCP processes and verify AP and DHCP startup before a USB-reset antenna returns to the pool.
- Discover AP-capable Wi-Fi interfaces (USB or built-in) automatically instead of requiring each one in the configuration. The `antennas` section (was `networks`) now only assigns display names and `show_dfs`, and `disable: true` keeps a radio out of Wi-Lab; unlisted interfaces use their interface name. A missing configured interface no longer prevents startup; with no usable adapter, reservations return `503 / 1003`. USB ports are detected automatically for recovery resets; `usb_recovery_port` is ignored.
- Add a device discovery service: Wi-Lab starts without antennas and scans as soon as the API starts, then every 5 seconds while none is available and every 30 seconds afterwards. Antennas plugged in later are added without a restart. Each scan re-reads `antennas` (display names, `disable` and `show_dfs`) and only adds devices; existing antennas, subnets and reservations are unchanged. Interfaces still being renamed by udev are skipped until they have their final name.
- Frontend: requests answered `503 / 1006` (antenna busy) are repeated automatically after `Retry-After`, and `1006`/`1007` errors show a readable explanation instead of the raw body.
- New `encryption: "wpa1"` (legacy WPA, PSK/TKIP, 802.11a/g only) to test old clients; accepted only on antennas whose driver supports TKIP (Fable HAP-10).
- AP creation takes optional `channel_width` (20, 40, 80 MHz) and `wifi_generation` (4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax); defaults 20 MHz / 802.11n keep the previous behaviour. `GET /antennas/{interface}` lists per band the generations, widths and channels an antenna accepts, and `GET .../network` reports the width the radio actually uses (Fable HAP-11).
- Frontend: the start dialog reads the antenna (`GET /antennas/{interface}`) and offers in dropdowns only the encryptions, Wi-Fi generations, channel widths and channels it supports (DFS channels marked, `wpa` replaced by `wpa1` where available), and a running network shows its width and Wi-Fi generation.
- New `GET /api/v2/monitoring` (System, token only): `status`, `degraded_reasons`, `checked_at`, `check_interval_seconds` and the detail of every health check (`commands`, `loops`, `hostapd`, `dnsmasq`, `iptables_nat`, `upstream_interface`), for operators and a future monitoring view.
- Optional `hostapd_debug_dir` setting: every hostapd start that fails writes a report there (hostapd configuration without passwords and the last 400 lines of `hostapd -d`); only failures are written and the newest 100 reports are kept.
- New **Antennas** API, listed in Swagger before Network and readable with the token only: `GET /api/v2/antennas` lists the managed antennas (`display_name`, `interface`); `GET /api/v2/antennas/{interface}` gives `device` (`bus`, `address`, `driver`), `encryptions` and per band the Wi-Fi generations with their widths and the usable channels with the widths each can use, to fill a form's dropdowns.
- Frontend: a captive portal switch on each reserved antenna card chooses whether the next network starts with a portal page (it presets the start dialog, which has the same switch), and a running network shows the captive portal as On or Off with its URL and a header badge.
- `POST /api/v2/reservations` takes an optional `interface` to reserve a given antenna (from `GET /api/v2/antennas`); without it the first free one is reserved, as before. A reserved antenna answers `409 / 1005` with the expiry of its reservation, a quarantined one `503 / 1002` or `1003`, an unknown one `422`.
- A create repeated with the same body on a network that already runs with exactly those settings answers `200` with the network instead of `409 / 1008`: after a lost answer the client just sends the same create again. A different body still answers `409 / 1008`.

### 🐛 Bug Fixes

- Report a hostapd exit during AP startup within about 1 s instead of after the full 10 s readiness timeout. A hostapd exit after a failed beacon setup previously returned a generic `500` after about 10.3 s.
- Retry transient radio failures inside the create request on both bands (hostapd segfault, beacon setup failure, radio or readiness timeout): up to 3 starts, 1 s apart, within 20 s. If they all fail, the server pauses and starts again (see the breaking change on `409 / 1001`).
- Keep Wi-Lab radios away from NetworkManager (per-device release, no configuration reload) and systemd-networkd (runtime rule under `/run`), and bring a radio down again after a USB reset. Previously a reset adapter could be raised by the host and stay quarantined.
- Send TCP resets for forwarded client traffic after Internet is disabled.
- Remove stale Wi-Lab firewall rules after an unclean shutdown without flushing host chains.
- Restrict each Wi-Lab masquerade rule to the corresponding AP subnet.
- Disabling Internet cuts existing forwarded connections on the selected AP.
- Listen on the configured API port instead of always using 8080.
- Report common invalid regulatory regions at startup.
- Prevent concurrent reservations in one service process from sharing an antenna, and wait for network cleanup before reassigning it. Failed cleanup keeps the device held and returns 503 when it prevents an operation.
- Stop active QoS profiles when their network is released or expires.
- Keep independent API requests responsive during slow device operations.
- Leave Wi-Fi interfaces managed and down after a network stops to avoid an unnecessary activation cycle.
- Verify that the access point is enabled before assigning its gateway and starting DHCP. Roll back incomplete network starts.
- Retry a transient hostapd startup segfault once on 2.4 GHz after successful cleanup, without requiring the client to resubmit the request.
- Clean up timed-out access point starts by tracking hostapd directly instead of waiting for a PID file.
- Keep other adapters and system status responsive during a slow AP startup or cleanup.
- `wilab/wifi` is a regular Python package (`__init__.py`) like `wilab/network` and `wilab/api`, instead of an implicit namespace package (Fable ARCH-12).
- A channel refused from the cached channel list is checked once more against a fresh `iw` reading, so 5 GHz channels cached before the regulatory domain was applied are no longer refused until a restart; the API and the TX power code share one channel cache, refreshed after a USB recovery or a failed start (Fable BUG-4).
- `/status` health checks now look at Wi-Lab's own processes and rules per network: a network without Internet is no longer `degraded` on a host without NAT rules, Docker's MASQUERADE no longer hides a missing Wi-Lab rule, a link that is DOWN is no longer reported up, and hostapd is checked too (new `checks.hostapd`, `missing` lists); `/debug` uses the same checks (Fable BUG-2).
- Background loops (discovery, watchdog, expiry) survive any unexpected error and log its traceback once, and a `config.yaml` saved with the wrong shape is reported as a clear configuration error instead of silently stopping discovery (Fable WD-9).
- `/status` no longer flaps to `degraded` while a network is being stopped or started: it uses one snapshot of the active networks and does not judge a network with an operation in progress (Fable RACE-2).
- An AP start runs fewer host commands: no repeated wireless/AP capability checks (established by discovery), no `dnsmasq --version`, and `nmcli` is looked up once instead of on every start (Fable PERF-1).
- Swagger examples now match the real responses: no `device_id` field that the API never returns, validation errors in the real `detail` object format, and unused QoS models removed; a test checks every `200` example against its model (Fable API-9).
- With `upstream_interface: auto`, Wi-Lab follows the default route when it moves to another interface: new networks use it and the NAT of running networks is moved within 30 s, instead of naming the old interface until a restart (Fable STAB-6).
- An internal AP start retry begins only with at least 4 s left (budget raised from 15 to 20 s), so a start cut short by the budget no longer counts as an extra radio failure towards quarantine (Fable HAP-4).
- Clients of a Wi-Lab network can no longer reach the Wi-Lab host (API, SSH, other services, also over IPv6): only DHCP, ping and, with the captive portal, DNS and the portal page are allowed (Fable SEC-3).
- After an unclean shutdown, startup stops orphan hostapd/dnsmasq, removes stale runtime files (including a dnsmasq PID file that failed every start) and Wi-Lab's QoS devices, and resets each radio (no address, no leftover netem/HTB) when discovery adds it (Fable STAB-4).
- A dnsmasq launch that timed out before writing its PID file no longer blocks the cleanup forever: Wi-Lab finds the daemon by its configuration file, or sees none was started (Fable NET-6).
- A device cleanup that keeps failing is retried in the background after 5, 15, 60 and then every 300 s instead of every 5 s, with one traceback per failure series; a client's release still tries immediately (Fable WD-6).
- Requests on a reservation wait at most 5 s for another operation on the same adapter and then return `503 / 1006 device_busy` with `Retry-After: 2`, instead of holding an API thread until a slow start ends (Fable RACE-1).
- The watchdog checks a running network every 30 s and repairs in place a lost gateway address, `ip_forward`, NAT, Internet-block and isolation rules; a broken captive portal restores the network (Fable WD-7).
- If a Wi-Lab background loop stalls, `/status` reports it and the service restarts itself through the systemd watchdog, but only when no reservation is active (Fable STAB-1).
- A dead dnsmasq is restarted up to 3 times per hour, and when that is not enough the watchdog restarts the whole network, instead of leaving it in `dhcp_failed` for good (Fable WD-3).
- A beacon failure gets the same classification and message whether the readiness probe sees hostapd `DISABLED` or its exit first (Fable HAP-2).
- A beacon rejected during hostapd setup is a radio failure in every create and watchdog restart, so it is retried by the server instead of answering a generic `500` (Fable HAP-3).
- A host command stuck in the kernel (hung Wi-Fi driver) no longer freezes its thread, device lock and eventually the API: Wi-Lab stops waiting 2 s after SIGKILL, fails the operation and reports `checks.commands.stuck` and `degraded` in `/status` (Fable STAB-1).
- A network whose NAT or isolation rules cannot be installed now fails with `500` instead of reporting success, and is rolled back (Fable NET-2); the false "Isolation disabled for testing" log line is gone (Fable NET-4).
- `iptables` calls wait up to 5 s for the xtables lock instead of failing when another program holds it (Fable NET-1).
- A failed watchdog AP restore is reported as `runtime_state: restore_failed` and retried with backoff, instead of leaving the AP silently down (Fable WD-2).
- The watchdog restores a failed AP up to 3 times per hour per antenna, instead of once per network life (Fable WD-1).
- Quarantined adapters with no USB recovery running are re-probed periodically and return to the pool without a service restart (Fable WD-4).
- Stopping a network on a disconnected adapter completes its cleanup, and an interface lost during startup is a radio failure retried by the server instead of a `500` (Fable WD-5).
- The create request is validated before touching the antenna: SSID, password and channel rules, and no line injection into `hostapd.conf` (Fable BUG-1).
- `wpa3` and `wpa2-wpa3` networks no longer write `wpa_key_mgmt` and `ieee80211w` several times in `hostapd.conf` (they worked only because hostapd keeps the last one); the mixed mode now requires PMF for WPA3 clients only, and SAE accepts H2E (Fable HAP-10).
- The service refuses to start with an empty `auth_token`, `api_port` outside 1–65535, `max_timeout` below `min_timeout` or a `dns_server` that is not an IPv4 address, as `--validate-config` already reported; before, `dns_server: foo` started and every network creation failed with `500` (Fable BUG-3).
- Networks are isolated from each other whatever `dhcp_base_network` is: with subnets outside `192.168.*` (e.g. `10.20.0.0/24`) no isolation rule was installed and clients of different networks could talk to each other (Fable NET-3).
- `DELETE .../network` no longer answers a bare `500` when hostapd stays stuck in the kernel after SIGKILL (seen with mt7921u firmware timeouts): it answers `503` with its own code `1012 stop_incomplete` (not `1004`, which means a cleanup not to retry) and `Retry-After: 5`, the half-stopped network reports `runtime_state: stop_failed`, the watchdog no longer "repairs" it, and repeating the DELETE finishes the stop.
- `DELETE .../network` repeats a stop that did not complete every 2 s for up to 15 s before answering `503 / 1012`: hostapd stuck in the kernel is usually released within seconds, so the client rarely sees `1012`.
- `/status` no longer runs host commands on every call: the checks (processes, NAT rules, upstream link) are refreshed every 10 s in the background and `/status` reads the latest result. Under load a call took up to 13 s, and every polling client added `ip` and `iptables` commands; a change now takes up to 10 s to show.
- An unexpected server error answers `500 / 500` without closing the connection: before, uvicorn dropped it after the answer, so the client's next request on the same keep-alive connection failed with a transport error (seen by the stress test as `ReadError` / `RemoteProtocolError` right after the `500` of a stop).
- Normal answers are no longer logged as errors: a missing `iptables -C` rule, a `tc` qdisc with nothing to delete, `iw set txpower` unsupported by the driver and a stop without DHCP are logged at debug level, and QoS uses `tc ... replace` instead of a failing `add` (Fable NET-5). In a stress run they were most of the `ERROR` lines.
- The log line `Starting network ... with SSID` is written only for a create that really starts, not for one refused because the network is already active.
- 6 GHz channels are no longer listed as 5 GHz channels (in 3.x `available-channels`, now `GET /antennas/{interface}`): Wi-Fi 6E antennas added 59 channels that cannot be used, some with the same number as a 5 GHz channel (e.g. two `149`).
- Every `422` message starts with the path of the refused field written with dots (`radio.channel_width: ...`, was `radio: channel_width: ...`), without pydantic's `Value error, ` prefix, also for rules between fields and antenna checks (`wifi.security.password`, `radio.channel`).
- APs with SSIDs that hostapd reports with escapes (non-ASCII, quotes, backslashes) become ready instead of ending in quarantine (Fable HAP-1).

### 🔧 Maintenance

- Read the initial configuration once while keeping periodic antenna configuration refreshes.
- Fix the PyYAML type-stub requirement for fresh development installs.
- Report an empty internal command consistently across platforms.
- **hostapd regulatory compliance** — The generated hostapd configuration now enables `ieee80211d=1` (advertise country code and apply the regulatory domain) on all bands, and `ieee80211h=1` (DFS/TPC) on 5 GHz where regulatory rules require it.
- Documented safe recovery of a blocked USB Wi-Fi adapter.
- Added an [AP creation procedure](docs/ap-creation-procedure.md) for client developers and a backend [architecture](docs/architecture.md) guide with startup, threading, creation, retry, watchdog and recovery diagrams.
- Explain the reservation and recovery lifecycle in Swagger and ReDoc, including retry, quarantine and watchdog response examples.
- Include the API operation, HTTP status, and error code in journal entries for server errors, without request or response data.
- Swagger lists release-all (`DELETE /api/v2/reservations/all`) and `GET /api/v2/debug` only under **Maintenance**; release-all also appeared under Reservation.
- `GET /api/v2/debug` is deprecated and will be removed.
- New [docs/error-codes.md](docs/error-codes.md): every `detail.code`, its HTTP status, `Retry-After`, where it is answered and the client action, plus the `degraded_reasons` codes; a test fails when a code is not documented.
- Detailed sequence diagrams of the whole flow, reservation to release, with every error answer and when to retry: client view in the [AP creation procedure](docs/ap-creation-procedure.md#3-sequence-diagram), with one action (done, wait, repeat, fix, reserve again, stop) for every answer of every call and how radio failures such as a hostapd crash reach the client, server view in [Architecture 6.1](docs/architecture.md#61-end-to-end-sequence-server-view). The captive portal diagram in the architecture guide did not render (a `;` in a note).
- Document `GET /api/v2/status` health values (`standby`, `ok`, `degraded`), what makes the service `degraded` (quarantined adapter, network being repaired, failed health check) and how clients learn about quarantined adapters, in Swagger (three response examples), the API overview, the AP creation procedure (2.8) and the Swagger guide.

### ✅ Tests

- Add regression coverage for authentication on protected reservation endpoints.
- Test unique concurrent reservations and device reuse on a ten-antenna pool.
- Added `TestHostapdConfigGeneration` covering the presence of `ieee80211d` on all bands and the band-dependent handling of `ieee80211h` (enabled on 5 GHz, absent on 2.4 GHz).
- Tests are split into `tests/unit-tests/` (the existing suite: mocked hardware, run by `make test-local` and CI) and `tests/e2e-tests/` (new). The e2e tests run on the Wi-Lab machine against the running service and combine API calls with server actions: journal checks, the SSID on the air via `iw`, and USB unplugs simulated through sysfs. They cover BUG-1, HAP-1, WD-4 and WD-5, are skipped unless `WILAB_E2E=1`, and have their own flags for USB unplugs and long tests (`make test-e2e`, `make test-e2e-usb`, see `docs/e2e-testing.md`).

### 🔌 API changes from 3.x (client migration)

**Paths (rename first)**

| 3.x | 4.0.0 |
|---|---|
| prefix `/api/v1` | prefix `/api/v2`: every path below; `/api/v1` answers `404` |
| `POST /api/v1/device-reservation` | `POST /api/v2/reservations` |
| `GET`, `DELETE /api/v1/device-reservation/{reservation_id}` | `GET`, `DELETE /api/v2/reservations/{reservation_id}` |
| `DELETE /api/v1/device-reservation` (release all) | `DELETE /api/v2/reservations/all` (Maintenance, `X-Confirm-Password`) |
| `/api/v1/interface/{reservation_id}/network` | `/api/v2/reservations/{reservation_id}/network` |
| `/api/v1/interface/{reservation_id}/internet/enable`, `/disable` | `/api/v2/reservations/{reservation_id}/internet/enable`, `/disable` |
| `/api/v1/interface/{reservation_id}/txpower` | `/api/v2/reservations/{reservation_id}/txpower` |
| `/api/v1/interface/{reservation_id}/qos/profile` | `/api/v2/reservations/{reservation_id}/qos/profile` |
| `/api/v1/interface/{reservation_id}/network/available-channels` | removed: `GET /api/v2/antennas/{interface}` |

The rest of this chapter names each endpoint by its 3.x path.

**All endpoints**

- Error body: `detail` is an object `{code, reason, message, ...}` (was a string, or `{error, ...}` on reserve). Branch on `detail.code`, show `detail.message`.
- Timestamps (`expires_at`, `detail.next_available_at`): RFC 3339 UTC, e.g. `2026-11-19T23:00:00Z` (was `YYYY-MM-DD HH:MM:SS`, local time).

**Reservation**

- `DELETE /api/v1/device-reservation` (release all): removed. Use `DELETE /api/v2/reservations/all` with header `X-Confirm-Password`.
- `POST /api/v1/device-reservation`:
  - `409`: now `detail.code: 1005`; `next_available_at` / `next_available_in` are `null` when no release is scheduled.
  - new `503 / 1002`: an antenna is recovering; retry after `Retry-After` (10 s).
  - new `503 / 1003`: no usable antenna (all quarantined or none found).
  - new optional `interface`: reserve that antenna only (see Features).
- Release: always `200`; a failed cleanup is repeated by the server (see the breaking changes). `1004` is no longer answered.

**Network**

- `POST /api/v1/interface/{id}/network`:
  - the body is grouped in sections; flat bodies return `422`. Field by field:

    | 3.x | 4.0.0 |
    |---|---|
    | `band`, `channel`, `tx_power_level` | `radio.band`, `radio.channel`, `radio.tx_power_level` |
    | — | `radio.channel_width` (`20`, `40`, `80`; default `20`), `radio.wifi_generation` (`4`, `5`, `6`; default `4`) |
    | `ssid`, `hidden` | `wifi.ssid`, `wifi.hidden` |
    | `encryption`, `password` | `wifi.security.encryption`, `wifi.security.password` |
    | `internet_enabled` | `internet.enabled` |
    | — | `captive_portal.enabled` (default `false`) |

    Only `radio` and `wifi` are required.
  - `radio.band: "dual"` removed (`422`).
  - `encryption: "wpa"` removed (`422`): use `wpa2` (same network as before). New `wpa1` for legacy WPA/TKIP, only on antennas that list it.
  - widths and generations the antenna does not support return `422`.
  - stricter validation, `422`: `ssid` 1–32 bytes, `password` 8–63 bytes, no control characters, channel must match the band, DFS channels refused unless the antenna has `show_dfs: true`.
  - radio failures are retried by the server inside the request; `409 / 1001` is no longer answered.
  - new `503 / 1003` with `reservation_invalidated: true`: discard the ID and reserve again.
  - `500 / 1013` with `detail.stage`: startup failed for a non-radio reason, reservation still valid.
  - `409 / 1008`: a network with different settings already active (the same body answers `200`); `409 / 1009`: a watchdog restore in progress (both had no code).
  - `200`: the body is the network, as `GET .../network` returns it (was `{"detail": "Network ... created successfully"}`).
  - can take up to about 80 s (several minutes on DFS channels): use a read timeout of at least 120 s (300 s on DFS).
- `GET /api/v1/interface/{id}/network`: the answer is grouped in sections, which are `null` while the network is not running:

  | 3.x | 4.0.0 |
  |---|---|
  | `expires_at`, `expires_in` | `reservation.expires_at`, `reservation.expires_in` |
  | `band`, `channel`, `tx_power` | `radio.band`, `radio.channel`, `radio.tx_power` |
  | — | `radio.channel_width.requested` / `.reported`, `radio.wifi_generation` |
  | `ssid`, `hidden` | `wifi.ssid`, `wifi.hidden` |
  | `encryption`, `password` | `wifi.security.encryption`, `wifi.security.password` |
  | `subnet`, `dhcp.gateway`, `dhcp.dhcp_range` (`"a,b"`) | `ip.subnet`, `ip.gateway`, `ip.dhcp_range` (`{start, end}`) |
  | — | `ip.dns_server` |
  | `dhcp.interface`, `dhcp.subnet`, `dhcp.network_addr`, `dhcp.config_file`, `dhcp.pid_file`, `dhcp.lease_file` | removed |
  | `internet_enabled` | `internet.enabled` |
  | — | `captive_portal.enabled`, `captive_portal.url` |
  | `clients_connected` | removed: use the length of `clients` |
  | `clients` | `clients` (new `captive_authorized` with a portal) |

  `interface`, `active` and the new `runtime_state` (`restoring_ap`, `restoring_dhcp`, `dhcp_failed`, `restore_failed`) stay at the top level.
- `DELETE /api/v1/interface/{id}/network`: also cancels a pending `restore_failed`, and returns `200`. New `503 / 1012` (`stop_incomplete`) + `Retry-After: 5` when the stop does not complete even after the server repeated it for 15 s (`runtime_state: stop_failed`): repeat the DELETE.
- `GET /api/v1/interface/{id}/network/available-channels`: removed, see **Antennas**.

**Antennas** (new, token only, no reservation)

- `GET /api/v2/antennas` → `{"antennas": [{display_name, interface}]}`.
- `GET /api/v2/antennas/{interface}` replaces `available-channels`:

  | 3.x `available-channels` | 4.0.0 `GET /antennas/{interface}` |
  |---|---|
  | `interface` | `interface` (+ `display_name`, `device`, `encryptions`) |
  | `channels_24ghz`, `channels_5ghz` | `bands["2.4ghz"].channels`, `bands["5ghz"].channels` |
  | entries with `disabled: true` | not listed |
  | `channel`, `frequency_mhz`, `max_power_dbm` | same, plus `dfs` and `channel_widths` |
  | — | `bands[...].wifi_generations[]`: `{wifi_generation, channel_widths}` |

**Configuration**

- `networks:` → `antennas:`; each entry needs `show_dfs: true|false` (DFS channels offered or not).

**Error codes**

- New domain codes on `409`: `1008` (create on an active network), `1009` (create during a watchdog restoration), `1010` / `1011` (QoS profile already / not running); stopping a stopped network answers `409 / 1007`. Full list: [docs/error-codes.md](docs/error-codes.md).
- Create: non-radio startup failure `500 / 1013` with `detail.stage` (was `500 / 500`).
- Every request body: unknown fields answer `422` (were ignored).
- `404` with a reservation ID only means the ID is gone. Unknown QoS `profile_id` and unsupported TX power: `422` (were `404`). Stopping a QoS profile that is not running: `409 / 1011` (was `404`).

**Internet, TX power, QoS profile**

- No running network: `409 / 1007` on Internet enable/disable, TX power GET/POST and QoS profile POST/GET/DELETE. Before: `404` on Internet, TX power and QoS GET/DELETE.
- `404` on these endpoints now only means the reservation is gone.

**Every `/api/v1/interface/{id}/...` endpoint except the create**

- New `503 / 1006` + `Retry-After: 2`: the antenna is busy with another operation. Repeat the request.

**Status**

- `GET /api/v1/status`:
  - `networks[]` is renamed `antennas[]`, and its entries gain `recovery_state` (`recovering`, `unavailable`) and `runtime_state`. What an antenna supports is in `GET /api/v2/antennas/{interface}`.
  - `checks` moved to `GET /api/v2/monitoring` (with `hostapd`, `commands`, `loops`, and `missing` lists in `dnsmasq` and `iptables_nat`); `/status` has `degraded_reasons` instead (`{code, interface, message}`).
  - `degraded` now also covers quarantined antennas, networks being repaired, stuck commands and stalled loops.
- `GET /api/v1/debug`: send the `X-Confirm-Password` header too (`403` without it), as for every Maintenance endpoint.

**Access**

- Clients connected to a Wi-Lab AP can no longer reach the API (nor any other host service). Call the API from the management network.

---

## [3.0.0] - 2026-04-18

### ✨ Features

- **QoS Profiles** — Per-reservation network condition simulation via profiles. A profile is an ordered sequence of timed steps, each defining bandwidth limits, a 0–100 quality score (mapped to packet loss, delay, jitter, corruption via netem), or advanced netem overrides. Supports 4 playback modes: `loop`, `bounce`, `once`, `once-hold-last`.
- **Built-in profile catalogue** — 10 ready-to-use profiles covering 4G urban/highway/rural/tunnel/stadium, 4G-to-3G fallback, WiFi interference, satellite link, and progressive degradation. Custom profiles can be added as `*.json` files in `wilab/data/qos-profiles/`, validated against a JSON Schema at startup.
- **Inline static QoS** — Submitting speed/quality parameters directly auto-generates a single-step `once-hold-last` profile, applied indefinitely until stopped.
- **Profile source tracking** — Each profile includes a `source_file` field showing which JSON file it was loaded from, both in the catalogue and in active profile state responses. Inline generated profiles show `"generated"`.
- **Profile state includes step count** — The `steps` field in profile state responses shows the total number of steps in the active profile.
- **New API endpoints:**
  - `GET /api/v1/qos/profiles` — browse the full catalogue (no auth)
  - `POST /api/v1/interface/{rid}/qos/profile` — start a profile or inline QoS
  - `GET /api/v1/interface/{rid}/qos/profile` — active profile state
  - `DELETE /api/v1/interface/{rid}/qos/profile` — stop and clear (returns 200 with confirmation, 404 if no active profile)

### 🔧 Maintenance

- Added `jsonschema>=4.19.0` to `requirements.txt` and `types-jsonschema` to `requirements-dev.txt`.

### ✅ Tests

- 113 tests covering models, catalogue loading, profile manager (all 4 playback modes, step isolation, inline profiles), API endpoints, and the underlying tc driver (`QosManager`).

---

## [2.5.1] - 2026-04-18

### 🔧 Maintenance

- **Non-interactive version bump support** – `update_version.sh` now accepts `--bump-to X.Y.Z`, while preserving the interactive prompt when no argument is provided.

### 🐛 Bug Fixes

- **Aligned frontend typing with unlimited reservation responses** – The frontend `NetworkStatus` model now accepts `expires_at: null` and `expires_in: null`, matching the backend contract for unlimited reservations on `GET /api/v1/interface/{reservation_id}/network`.

### ✅ Tests

- **Added explicit unlimited reservation API coverage** – New tests verify that both `GET /api/v1/device-reservation/{reservation_id}` and `GET /api/v1/interface/{reservation_id}/network` return `expires_at: null` and `expires_in: null` for unlimited reservations.

## [2.5.0] - 2026-04-16

### 🔧 Maintenance

- **Removed `default_timeout` config parameter** – Reservation duration is now always required explicitly via `duration_seconds` in the API. The legacy fallback in `NetworkManager.start_network()` was dead code (never triggered by the reservation flow) and has been removed.
- **Updated documentation** – README rewritten: concise structure, current config format, API usage example, Makefile-based workflow. Removed outdated `net_id` references, duplicate sections, and obsolete curl examples.

### 🐛 Bug Fixes

- **Fixed `TypeError` on unlimited reservations** – `_expires_at_timestamp` `None` comparisons in `NetworkManager` (get_status, enable/disable internet) now handle unlimited reservations correctly.
- **Fixed missing ANSI colors in `start-service.sh`** – URL lines were using `echo` without `-e`, printing raw escape codes instead of colored output.

### ✨ Features

- **Swagger UI & ReDoc links in toolbar** – Two icon buttons (`description`, `menu_book`) added to the frontend toolbar, separated from the auth lock button by a vertical divider. Each opens the corresponding API docs in a new tab.
- **Reservation policy API** – `GET /api/v1/status` now returns a `reservation_policy` object with `min_seconds`, `max_seconds`, and `allow_unlimited`, replacing the flat `allow_unlimited_reservation` field.
- **Dynamic reservation dialog** – The frontend fetches reservation policy from the API and uses server-configured min/max for validation. Duration is shown as a live `00h 00m 00s` badge in the dialog title bar, with a human-readable valid range hint below the input.

---

## [2.4.0] - 2026-04-16

### ✨ Features

- **Token-based login dialog** – The frontend no longer stores the auth token in environment files. On first load, a dialog prompts the user to enter a Bearer token, which is saved in `localStorage` and used for all API requests. A lock icon button in the toolbar allows changing the token at any time.

### 🔒 Security

- **Removed hardcoded `authToken`** from both `environment.ts` and `environment.prod.ts`. The token is now provided at runtime by the user, eliminating secrets from the source code.
- **Removed hardcoded IP** from the development environment file. Both environments now use the relative path `/api/v1`.
- **401 auto-detection** – An HTTP interceptor detects unauthorized responses, clears the invalid token, and re-prompts the user immediately.

### 🔧 Maintenance

- **New `AuthService`** – Centralized service for token management via `localStorage`.
- **New `TokenDialogComponent`** – Angular Material dialog for entering/updating the auth token.

---

## [2.3.0] - 2026-04-01

### 🐛 Bug Fixes

- **Auto-stop network on reservation release** – Releasing a reservation (single or bulk delete) now automatically stops any active WiFi network on the associated device. Previously, the network remained running until its expiry timeout, leaving orphaned AP/DHCP/NAT resources.

---

## [2.2.0] - 2026-03-31

### ✨ Features

- **Unlimited reservations** – When `allow_unlimited_reservation: true` in config, users can create reservations with no expiry by sending `duration_seconds: 0`. The reservation stays active until explicitly released.
- **Duration validation** – `POST /device-reservation` now validates `duration_seconds` against `min_timeout` and `max_timeout` from config (previously only enforced client-side)
- **Hardcoded `min_timeout` floor** – `min_timeout` can never be set below 10 seconds in config

### 🔧 Maintenance

- **Frontend unlimited UX** – Reservation dialog shows an "Unlimited" checkbox when allowed. Owned cards show "∞ Unlimited" instead of countdown; occupied cards show "Occupied — No expiry"

### 🔌 API Changes

#### `POST /api/v1/device-reservation`

- `duration_seconds: 0` creates an unlimited reservation (requires `allow_unlimited_reservation: true` in config)
- `duration_seconds` is now validated server-side against `min_timeout` / `max_timeout`; returns 422 if out of bounds
- Response fields `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### `GET /api/v1/device-reservation/{reservation_id}`

- Response fields `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### `GET /api/v1/status`

- New field: `allow_unlimited_reservation` (boolean) — reflects the server config
- Each network entry now includes `reserved` (boolean) — distinguishes "available" from "occupied unlimited" when `reservation_remaining_seconds` is `null`
- `reservation_remaining_seconds` is `null` for unlimited reservations (previously only `null` when not reserved)

#### `GET /api/v1/interface/{reservation_id}/network`

- `expires_at` and `expires_in` are now **nullable** (`null` for unlimited reservations)

#### New config parameter

```yaml
# Set to true to allow unlimited reservations (duration_seconds: 0)
allow_unlimited_reservation: false
```

---

## [2.1.0] - 2026-03-28

### 🔧 Maintenance

- **Reorganized `scripts/` folder** – Removed 10 obsolete API helper scripts; split `restart-service.sh` into `scripts/stop-service.sh` and `scripts/start-service.sh`
- **Makefile service targets** – Added `make stop`, `make start`, `make restart`; removed duplicate `build-release`/`run-release` targets
- **Test suite decoupled from host config** – Tests now use a dedicated `tests/test.config.yaml` so they pass regardless of the host `config.yaml`

### ✨ Features

- **Available WiFi Channels API**
  - New endpoint to query all WiFi channels supported by a reserved device, split by band
- **Channel cache warm-up at startup** – WiFi channel info is pre-fetched in a background thread so the first API call is served from cache
- **Centralized channel validation** – Static and hardware-aware channel validation, with 5 GHz channels 169/173/177 now recognized. Network creation rejects unsupported or disabled channels with a clear 422 error
- **Configurable country code** – WiFi regulatory domain (`country_code`) moved from hardcoded value to `config.yaml` (default: `IT`)
- **Regulatory domain enforcement at startup** – `iw reg set` is called with the configured country code before cache warm-up, ensuring the kernel reports correct channel flags. Channels marked `No IR` (no initiate radiation) are now detected and treated as disabled

### 🔌 API Changes

#### New endpoint

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/interface/{reservation_id}/network/available-channels` | List supported WiFi channels for the reserved device |

Response body:
```json
{
  "interface": "wlxbc071dc527d6",
  "channels_24ghz": [
    { "channel": 1, "frequency_mhz": 2412, "max_power_dbm": 20.0, "disabled": false },
    { "channel": 14, "frequency_mhz": 2484, "max_power_dbm": 0.0, "disabled": true }
  ],
  "channels_5ghz": [
    { "channel": 36, "frequency_mhz": 5180, "max_power_dbm": 23.0, "disabled": false },
    { "channel": 169, "frequency_mhz": 5845, "max_power_dbm": 0.0, "disabled": true }
  ]
}
```

Each channel includes frequency in MHz, maximum TX power in dBm, and a disabled flag. Disabled channels (blocked by regulatory domain) are reported with `max_power_dbm = 0.0` by convention. Channel data is resolved from `iw phy` on first request and cached in memory for subsequent calls.

---

## [2.0.0] - 2026-03-27 - ⚠️ Unreleased version ⚠️

Major release introducing a reservation-based device lifecycle. Users must now acquire a time-limited reservation token before performing any network operation. The frontend has been redesigned around this workflow, showing all physical interfaces as cards with real-time status and allowing multiple simultaneous reservations.

### ⚠️ Breaking Changes

- **`net_id` removed from configuration.** Each device is now identified internally by its physical interface name (`device_id`). A new required field `display_name` replaces the old `net_id` label.
  ```yaml
  # Before
  networks:
    - net_id: "ap-01"
      interface: "wlxbc071dc527d6"

  # After
  networks:
    - interface: "wlxbc071dc527d6"
      display_name: "bench-antenna-1"
  ```
- **All network, internet, and txpower routes now use `{reservation_id}` as path parameter** instead of the old `{net_id}`. A valid reservation token is required for every operation.
- **The `timeout` parameter on network creation has been removed.** Reservation `duration_seconds` is the only lifetime source; WiFi auto-stops when the reservation expires.

### ✨ Features

- **Device Reservation System**
  - Reservation-first workflow: a time-limited token must be acquired before any network operation
  - Devices are allocated automatically — the API assigns the first available interface
  - Token is an 8-character hex string, cryptographically generated
  - At reservation expiry the network is stopped, the device is released, and the token is invalidated
  - When all devices are occupied, the API returns the estimated wait time until the next device becomes free

- **Frontend Reservation UX**
  - All physical interfaces are displayed as cards, polled every 10 seconds from the status API
  - Each card shows one of three states: owned (with full WiFi controls), occupied by another user (with live countdown), or available
  - Users can hold multiple reservations simultaneously; cards appear with a countdown progress bar and `hh:mm:ss` label
  - "Release All" button with destructive-action confirmation dialog to free all owned devices at once
  - Reservations persist to `localStorage` and are validated on page reload — surviving browser refresh
  - When capacity is full, an inline error shows a live countdown to the next available slot

- **Shared Installation State Contract**
  - Installer stages now share a persistent state contract, propagated across precondition checks, install stages, and post-install tests

### 🔌 API Changes

#### New endpoints — Reservation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/device-reservation` | Reserve the first available device. Body: `{ "duration_seconds": <int> }`. Returns `reservation_id`, `display_name`, `interface`, `expires_at`, `expires_in`. |
| `GET` | `/api/v1/device-reservation/{reservation_id}` | Query reservation status. Returns same fields as create. `404` if expired or unknown. |
| `DELETE` | `/api/v1/device-reservation/{reservation_id}` | Release a single reservation. `404` if not found. |
| `DELETE` | `/api/v1/device-reservation` | Release all active reservations at once. Returns `{ "released": <count> }`. |

When all devices are reserved, `POST` returns `409 Conflict`:
```json
{
  "detail": {
    "error": "No device available",
    "next_available_at": "2026-03-27 14:30:00",
    "next_available_in": 120
  }
}
```

#### Changed endpoints

- **`POST /api/v1/network/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`; `timeout` field removed from request body.
- **`GET /api/v1/network/{reservation_id}`** — always returns `expires_at` (ISO 8601 UTC) and `expires_in` (seconds), even when WiFi is off.
- **`DELETE /api/v1/network/{reservation_id}`** — stops the network but does not release the reservation.
- **`POST|DELETE /api/v1/internet/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`.
- **`GET|PUT /api/v1/txpower/{reservation_id}`** — path parameter changed from `net_id` to `reservation_id`.
- **`GET /api/v1/status`** — each device now includes `reservation_remaining_seconds` (integer or `null` when unreserved) and `display_name`.
- **`GET /api/v1/debug`** — each network entry includes `reservation_id` and `display_name`.

### 📝 Documentation

- Configuration example updated: `interface` + `display_name`, no `net_id`
- Networking docs: "Secure Timeout Configuration" section replaced with "Reservation-Driven Timeout"
- Developer guide updated with new config format and Makefile workflow

---

## [1.5.0] - 2026-03-24

### 📚 Documentation

- **Consolidated Troubleshooting Documentation**
  - Merged troubleshooting content from `networking.md` into centralized `docs/troubleshooting.md`
  - Removed redundant troubleshooting sections from `networking.md`
  - Added disclaimer about interface name alignment for diagnostics scripts
- **Removed Obsolete Installation Guide**
  - Deleted `docs/installation-guide.md` (content migrated to README.md and troubleshooting.md)
  - Updated all documentation references to point to current resources
- **Simplified API Documentation**
  - Removed hardcoded API endpoint examples from `docs/swagger.md`
  - Directed users to Swagger UI at `http://localhost:8080/docs` as single source of truth
- **Updated Development Guide**
  - `docs/readme-dev.md` now prioritizes Makefile targets over manual commands
  - Added `make venv` and `make test-local*` examples
  - Removed references to old setup patterns
  - Added `make type-check` to development workflow documentation

### 🔧 Tool Integration

- **Added Ruff Linter to Build System**
  - Integrated `ruff>=0.3.0` as primary code quality tool
  - Added `make lint` target to check code style
  - Added `make lint-fix` target to auto-fix code style issues
  - Updated development workflow to include linting step in pre-commit checklist
  - Documented ruff usage in `docs/readme-dev.md`
- **Added MyPy Static Type Checking**
  - Integrated `mypy>=1.8.0` for static type validation
  - Added `make type-check` target to run type checker
  - Type checking included in pre-commit guidelines (warnings expected during type hint migration)
  - Updated Makefile and documentation to reflect type-checking workflow

### 🧹 Code Quality

- **Applied Ruff Fixes Across Codebase**
  - Removed 14 unused imports: `AppConfig`, `tempfile` (3x), `pytest`, `MagicMock`, `Body`, `Optional`, `datetime`, `execute_iptables`
  - Removed unused exception variables in except clauses
  - Fixed 3 f-strings without placeholders (unnecessary `f` prefix)
  - Files improved: 12 files across tests/, wilab/api/routes/, wilab/network/, wilab/wifi/
  - All 151 tests pass successfully

---

## [1.4.0] - 2026-03-23

### 🔒 Security

- **Fixed unauthenticated access to `/api/v1/debug` endpoint**
  - `GET /api/v1/debug` now requires a valid Bearer token, consistent with all other protected endpoints
  - Previously, the endpoint exposed full system debug information (services, interfaces, diagnostics) without authentication

### 🧪 Testing

- Added `test_debug_requires_auth`: verifies `GET /api/v1/debug` returns `401` without a token
- Added `test_debug_with_invalid_token`: verifies `GET /api/v1/debug` returns `401` with an invalid token
- Updated existing `TestDebugEndpoint` tests to supply the valid Bearer token header

### 🔧 Refactoring & Infrastructure

- **Network Lifecycle API Response Simplification**
  - `POST /api/v1/interface/{net_id}/network` now returns a compact success payload: `{"detail": "Network {net_id} created successfully"}`
  - `DELETE /api/v1/interface/{net_id}/network` now returns a consistent payload: `{"detail": "Network {net_id} stopped successfully"}`
  - `POST /api/v1/interface/{net_id}/internet/enable` now returns: `{"detail": "Network {net_id} internet enabled successfully"}`
  - `POST /api/v1/interface/{net_id}/internet/disable` now returns: `{"detail": "Network {net_id} internet disabled successfully"}`
  - Full network details are now retrieved only via `GET /api/v1/interface/{net_id}/network`
- **Validation Error Payload Simplification**
  - Request validation errors are exposed with a simple string payload: `{"detail": "..."}`
  - Removed dependency on verbose Pydantic-style validation lists for API clients
- **DELETE Network State Semantics**
  - `DELETE /api/v1/interface/{net_id}/network` now enforces proper state transitions:
    - `404` for unknown `net_id`
    - `409` when the network is already inactive

### 🧪 Testing

- Added coverage for simplified POST network success response payload
- Added coverage that `422` validation responses expose a string `detail`
- Added deterministic coverage for DELETE network behavior:
  - stop active network succeeds (`200`)
  - stop inactive network returns `409`
  - stop unknown network returns `404`
- Added coverage for internet enable/disable success cases:
  - `test_enable_internet_success`: validates POST returns detail message with net_id
  - `test_disable_internet_success`: validates POST returns detail message with net_id
- Hardened internet-control tests by isolating manager state per test

---

## [1.3.0] - 2026-03-18

### 🐛 Bug Fixes

- **TX Power POST Hardware Mismatch Handling**
  - `POST /api/v1/interface/{net_id}/txpower` now returns HTTP `422 Unprocessable Entity` when the wireless interface reports a different power than the requested one
  - Replaced warning-style success handling with explicit API error semantics for unsupported dynamic TX power changes
- **TX Power POST Out-of-Range Validation**
  - `POST /api/v1/interface/{net_id}/txpower` now always returns HTTP `422 Unprocessable Entity` for out-of-range levels
  - Out-of-range errors now use a short and stable payload: `{"detail": "Requested power out of range. Valid values are 1, 2, 3, 4."}`

### ✨ Features

- **Client Details in Network Cards (Phase 1)**
  - Replaced count-only view with a connected clients table in each active AP card
  - Added client list columns for `IP Address` and `MAC Address`
  - Added empty-state message when no clients are connected
  - Kept polling-based refresh behavior unchanged

- **Network Card Status Visibility Improvements**
  - Added `TX Power` row with descriptive values matching the creation dialog labels
  - Added `Expires in` row with human-readable duration formatting (`h m s`)
  - Dynamic card border state by Internet status:
    - Green when Internet is enabled
    - Yellow when Internet is disabled

- **AP Diagnostic Utility Restoration**
  - Restored the AP diagnostic helper on `main`
  - Moved the script from `scripts/10-diagnose-ap.py` to `diagnostics/diagnose-ap.py`
  - Added clearer command-line usage examples for running diagnostics from the repository root

- **Requested vs Reported TX Power API Model**
  - Added nested `tx_power` payloads exposing `requested_level`, `reported_level`, and `reported_dbm`
  - `GET /api/v1/interface/{net_id}/network` now includes TX power details alongside DHCP and client information
  - `GET /api/v1/interface/{net_id}/txpower` now returns the same requested/reported TX power structure

### 🎨 UI/UX

- Simplified clients summary presentation:
  - Removed duplicate `Clients` row
  - Kept `Connected Clients:` label with right-aligned count
- Improved spacing and readability in network cards:
  - Increased separation between interface subtitle and details section
  - Reduced vertical spacing between detail rows (`SSID`, `Password`, `Channel`, etc.)
- Refined card header layout:
  - Kept WiFi icon, network name, and interface subtitle consistently left-aligned
- Moved Internet status indicator to the top-right corner of the card:
  - Replaced text chip with icon-only rounded rectangular badge
  - Green badge with `cloud_done` when Internet is available
  - Yellow badge with `cloud_off` when Internet is disabled
  - Added hover tooltip text: `Internet available` / `Internet disabled`
- Updated inactive card copy:
  - Replaced `No active network` with `Access point <net_id> disabled.`
  - Network name is emphasized in bold for better visibility
- Updated frontend network cards to display `TX Power requested/reported` instead of a single legacy TX power level

### 🔧 Refactoring & Infrastructure

- **TX Power Response Reshape**
  - Introduced shared backend model for requested/reported TX power data
  - Removed legacy flat TX power fields such as `current_level`, `current_dbm`, and top-level `reported_dbm`
  - Removed the legacy warning field from successful TX power responses

- **OpenAPI Example Alignment**
  - Updated Swagger examples for `GET /api/v1/interface/{net_id}/network`
  - Updated Swagger examples for `GET /api/v1/interface/{net_id}/txpower` to match the nested `tx_power` response shape
  - Added explicit Swagger examples for `POST /api/v1/interface/{net_id}/txpower` success and `422` error variants (out-of-range and hardware mismatch)

### 🧪 Testing

- Added/updated backend API coverage for `GET /api/v1/interface/{net_id}/network` client structure:
  - Validates `clients[]` payload entries include stable `ip` and `mac` fields
  - Confirms correct `clients_connected` count for active networks
- Added manager-level TX power coverage:
  - Validates requested TX power updates keep internal state in sync on success
  - Validates hardware mismatch raises an error and preserves the previous configured TX power level
- Added API coverage for TX power endpoints:
  - Verifies nested `tx_power` serialization on `GET /api/v1/interface/{net_id}/txpower`
  - Confirms legacy warning and flat TX power fields are no longer exposed by the GET response
  - Confirms `POST /api/v1/interface/{net_id}/txpower` returns `422` on hardware mismatch
  - Confirms `POST /api/v1/interface/{net_id}/txpower` returns the simplified `422` out-of-range error message
  - Confirms OpenAPI schema documents `422` examples for both out-of-range and hardware mismatch cases

### 📝 Documentation

- Consolidated client and traffic planning docs into:
  - `TODOs/clients-info-and-statistics.md`
- Removed overlapping legacy planning document:
  - `TODOs/traffic-statistics.md`

---

## [1.2.1] - 2026-03-18

### 🐛 Bug Fixes

- **Hostapd Startup Timeout**: Fixed intermittent hostapd failures on interface transitions
  - Command execution timeout increased from hardcoded 1s to configurable 8s default
  - Minimum timeout floor enforced at 5s to prevent accidental timeouts
  - Resolves "Failed to start hostapd" errors during AP initialization
  - Added comprehensive test coverage for timeout enforcement

### ✨ Features

- **Dynamic WiFi Network Names**: SSID now generated based on AP identifier
  - Format: `test-network-ap-01`, `test-network-ap-02`, `test-network-ap-03`
  - Each AP card displays unique, recognizable network name
  - Prevents duplicate network names across multiple access points
  - Frontend dynamically generates SSID from AP ID parameter

### 🔧 Refactoring & Infrastructure

- **Setup → Install Terminology Migration**:
  - Renamed `install/02-setup-stages/` → `install/02-install-stages/`
  - Updated variable naming: `SETUP_DIR` → `INSTALL_DIR`, `setup_common_vars()` → `install_common_vars()`
  - Consistent terminology across all installation scripts and documentation
  - Removed backward compatibility alias (internal scripts only)

- **API Response Documentation**:
  - Explicitly documented 401 Unauthorized responses in OpenAPI/Swagger schema
  - All authentication-protected endpoints now properly reflected in API documentation
  - Improved API contract clarity for client implementations

- **Development Tooling**:
  - Added `restart-service.sh` utility script for rapid development iteration
  - Simplified restart flow: stop (10s → 5s) → wait → start
  - Removed unnecessary Docker container check (frontend served as static files)

### 📝 Testing

- Enhanced timeout behavior validation:
  - Test coverage for default 8s timeout enforcement
  - Test coverage for 5s minimum timeout clamping
  - Added custom timeout configuration tests
  - All 136+ tests passing

### 📦 Dependencies & Build

- Frontend build optimization: reduced bundle size analysis and warnings review
- Docker multi-stage build for frontend compilation remains unchanged

---

## [1.2.0] - 2026-01-29

### 🚀 Major API Simplification

- **Unified Network Endpoints** (Breaking Change):
  - Consolidated 4 redundant endpoints into single `GET /interface/{net_id}/network`
  - **Removed endpoints**: `/interface/{net_id}/status`, `/interface/{net_id}/summary`, `/interface/{net_id}/clients`
  - New unified endpoint returns complete network state: configuration, DHCP info, connected clients
  - 75% reduction in API surface area (4→1 endpoints)
  - Enhanced `NetworkStatus` model with `dhcp`, `clients`, `clients_connected` fields
  - Frontend migrated to use unified endpoint (1 call instead of 3)

### ✨ Features

- **Version Display**: Software version (1.2.0) now displayed in frontend page title
- **Enhanced Swagger UI**: Added example values (`ap-01`) precompiled in all `net_id` parameters
- **System Health Monitoring**:
  - Added `/api/v1/status` endpoint (renamed from `/health`) with comprehensive health checks
  - Standby mode when no networks active
  - Checks: dnsmasq status, iptables NAT, upstream interface connectivity
  - Status levels: `ok`, `standby`, `degraded`
  
- **Debug Endpoint**: New `/api/v1/debug` endpoint for troubleshooting
  - System info: OS, kernel, Python version, uptime
  - Network diagnostics: active networks, DHCP leases, iptables rules
  - Service status: hostapd, dnsmasq processes
  - ~600ms response time for comprehensive diagnostics

### 🔒 Security

- **Authentication Enforcement**: `/api/v1/status` endpoint now requires authentication token
- All system status endpoints protected behind auth layer

### 🔧 Refactoring & Code Quality

- **API Route Organization**:
  - Renamed `health.py` → `status.py` for semantic clarity
  - Removed `clients.py` route file (functionality merged into network endpoint)
  - Deleted `ClientsResponse` model (no longer needed)
  - Cleaner route structure and reduced code duplication

- **JSON Response Optimization**:
  - Reordered `/status` endpoint fields: `version` → `status` → `networks` → `active_networks` → `checks`
  - More logical field ordering for better API ergonomics

- **Code Reduction**:
  - Removed `get_summary()` method from NetworkManager
  - Eliminated 251 lines of redundant code across backend and frontend
  - Simplified frontend service: removed `getClients()` and `loadClients()` methods

### 🧪 Testing

- **Test Suite Optimization**: Reduced from 33 to 29 tests (removed redundant endpoint tests)
- **Enhanced Coverage**: Added comprehensive test for unified network endpoint with DHCP and clients validation
- All tests passing with new consolidated structure

### 📚 Documentation

- **API Simplification**: Updated `TODOs/api-simplification.md` to COMPLETED status
- **Swagger Documentation**: Updated OpenAPI specs with consolidated endpoint structure
- Improved endpoint descriptions and response examples

### ⚡ Performance

- Frontend efficiency: Single API call replaces 2-3 previous calls for network status
- Reduced network overhead and improved page load times

---

## [1.1.0] - 2026-01-29

### 🔧 Refactoring & Infrastructure Improvements

- **Modularized Setup Infrastructure**:
  - Centralized common functions in `install/common.sh` (9 reusable functions)
  - Split setup into 15 modular stages (5 preconditions + 5 setup + 5 tests)
  - Eliminated all code duplication across setup scripts
  - 60% reduction in install.sh size (from 436 to 76 lines)

- **Dynamic Stage Discovery**:
  - Setup stages automatically discovered at runtime from `install/` directory
  - Numerical sorting ensures correct execution order
  - Add new stages without modifying install.sh
  - Each stage independent and reusable

- **Setup Orchestrator Pattern**:
  - Replaced monolithic install.sh with slim orchestrator
  - Complex logic moved to individual `install/*` stage scripts
  - User confirmation flow and dynamic config extraction
  - Added `install/99-final-test.sh` for comprehensive verification

- **API Routes Refactoring**:
  - Split monolithic `routes.py` into modular domain-based structure
  - Separate modules: clients, health, internet, network, txpower
  - Improved maintainability and testability

- **Make Scripts Executable**:
  - Ensured all install.sh and uninstall.sh scripts have execute permissions
  - Improved CI/CD pipeline compatibility

### 🐛 Bug Fixes

- **Fix Homepage Test**: Updated to use GET request for reliable HTTP detection
- **Prevent Duplicate iptables Rules**: Enhanced rule creation logic to prevent duplicates
- **Fix Gateway Assignment**: Corrected gateway assignment logic
- **Fix Client Count Reporting**: Fixed reported number of connected clients calculation
- **Test Hardware Independence**: Made tests hardware-independent for better CI/CD compatibility
- **Improve NAT Test Mocks**: Enhanced mocks in `test_enable_nat_auto_upstream` to distinguish between commands
- **Extract Docker IMAGE_NAME**: Improved DRY principle by extracting `IMAGE_NAME` from `deploy_frontend.sh` in uninstall script

### 📖 Documentation & Configuration

- **API Documentation**: Added HTTP status codes to Swagger/OpenAPI responses
- **Configuration Management**: Improved config.yaml handling with example file
- **Development Guidelines**: Updated copilot instructions for development best practices
- **Service Naming**: Renamed service from `wilab.service` to `wi-lab.service` for consistency

### 🔐 Security & CORS

- **CORS Support**: Enhanced frontend integration with proper Cross-Origin Resource Sharing configuration
- **Allowed Origins**: Updated configuration for cross-domain requests between frontend and backend

---

## [1.0.0] - Initial Release

### 🎯 Core Features

- **WiFi Network Management**:
  - Create and manage WiFi networks with customizable SSID and security settings
  - Network lifecycle management (create, activate, deactivate, delete)
  - Support for WPA2 authentication

- **Client Management**:
  - Real-time client connection monitoring
  - Client device tracking and identification
  - Connection history and statistics

- **DHCP Server**:
  - Integrated DHCP server with configurable subnet allocation
  - Automatic IP assignment to connected clients
  - Lease management and renewal

- **NAT & Internet Access**:
  - Network Address Translation (NAT) for client internet connectivity
  - Upstream connection handling
  - Automatic upstream detection and configuration

- **Traffic Control**:
  - Linux `tc` (traffic control) integration for advanced network management
  - TX power management for WiFi interface control

- **REST API**:
  - Full-featured REST API for network operations
  - Comprehensive health check endpoint
  - Swagger/OpenAPI documentation

- **Frontend Application**:
  - Angular-based web frontend for network management
  - Real-time network status monitoring
  - Client device management interface
  - Production-ready Docker build

- **Systemd Service**:
  - Linux systemd service integration
  - Automatic service startup on boot
  - Service lifecycle management

- **Docker Support**:
  - Docker containerization for easy deployment
  - Docker Compose for multi-service orchestration
  - Frontend build integrated in Docker pipeline

### 🛠️ System Requirements

- Linux OS with WiFi support (hostapd, dnsmasq)
- Python 3.8+
- Docker & Docker Compose
- Network interface management capabilities

### 📚 Documentation

- Comprehensive setup and installation guide
- API documentation with examples
- Network configuration guide
- Troubleshooting documentation
- Development guidelines for contributors

### 🔐 Security Features

- HTTPS support for API endpoints
- Configuration validation on startup
- Security checks for network isolation
- Safe cleanup of system resources

### 🚀 Setup & Installation

- Automated setup script for quick deployment
- Multi-stage installation with verification
- Service registration and auto-start configuration
- Health checks and validation

---

