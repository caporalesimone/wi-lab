# Changelog

All notable changes to Wi-Lab are documented in this file.

---

## [4.1.0] - Unreleased

### 📊 Statistics

| Item | Count |
|---|---:|
| 🐛 Bug fixes | 13 |
| ⚠️ Breaking changes | 3 |
| 🔧 Maintenance changes | 3 |
| ✨ New features | 0 |
| ✅ Test changes | 7 |
| 📦 Commits since 4.0.0 | 30 |

Counts are the entries of the sections below and `git rev-list --count aca248e..HEAD` (`aca248e` is the last 4.0.0 commit), as of 2026-11-26.

### ⚠️ Breaking Changes

- NetworkManager is no longer supported: Wi-Lab requires Ubuntu Server with the host network on systemd-networkd and no longer releases radios from NetworkManager (`nmcli` is never run; the runtime file under `/run/NetworkManager/conf.d` is gone). On hosts where NetworkManager runs, check that it manages no interface (`nmcli device status`), then `sudo systemctl disable --now NetworkManager && sudo systemctl mask NetworkManager` (Fable NM-1).
- Request bodies of the reservation, the create and `POST .../txpower` take only the JSON types they document: `"6"`, `true` or `6.0` for an integer, and `"false"` or `0` for a boolean, are now a `422` instead of being converted (Fable REV-11).
- `POST .../txpower` takes `tx_power_level` instead of `level`, the name of `radio.tx_power_level` in the create (Fable API-6).

### ✨ Features

### 🐛 Bug Fixes

- A create on an antenna that disappeared just before it no longer answers a generic `500` when the channel list was not cached: it is accepted (`202`) and ends like any lost antenna, retried by the server and then `404 reservation_invalidated`.
- A start that fails with an unexpected error (for example too many open files) is rolled back like any other failure: the AP no longer keeps transmitting after `start_failed`, `DELETE .../network` stops whatever a failed start left, and the watchdog reports such a failed restore as `restore_failed` and retries it (Fable REV-1).
- A stop that cannot stop hostapd keeps the host guard and the isolation rules until a repeated stop succeeds, so clients of an AP still transmitting cannot reach the host or other networks (Fable REV-7).
- A firewall check that fails (xtables lock held by another tool, timeout) no longer counts as a missing rule: the watchdog skips that round instead of adding the Internet block again or restoring a healthy network, and stopping a network removes every copy of its Internet block (Fable REV-3).
- Removing a network's host guard no longer fails when the firewall already lost its chain (a host firewall reload, or a guard that failed half-way): the antenna is no longer quarantined for it (Fable REV-4).
- A retry of a failed AP start is no longer cut by a 20 s budget left over from the synchronous create: a retry that brings the AP up is kept instead of being reported as `start_failed`, and later phases (DHCP, NAT) are no longer blamed for the expired budget. Only the 3 attempts and the reservation expiry limit the retries (Fable REV-5).
- Releasing a reservation while the watchdog restarts its AP is immediate, as during a create, instead of waiting for the restart (up to 75 s on DFS); the service shutdown cancels running creates instead of waiting for them, and the recovery probe of a reset antenna no longer uses a DFS channel (60 s radar check under the device lock) (Fable REV-6).
- An adapter whose name differs from the one udev suggests is no longer ignored forever with nothing in the log: after 3 scans without a rename it is used as it is, with a warning (Fable BUG-5).
- The service stop no longer risks being killed by systemd half-way through the cleanup (leaving APs and rules behind): antennas are released in parallel within 20 s, running requests get 10 s, and the unit's `TimeoutStopSec` is 60 s. Reinstall the systemd unit to apply the new timeout (Fable STAB-8).
- On a loaded host, slow answers of `hostapd_cli` no longer restart a healthy AP (disconnecting every client and using one of the 3 restores of the hour): a probe without an answer in 1 s counts half a miss, so the watchdog restarts the AP after 3 real "not ENABLED" answers or 6 probes without an answer (Fable WD-10).
- The DHCP lease file of a network is deleted when the network ends: the next user of the adapter no longer inherits the previous session's clients (MAC addresses) for up to 12 hours. A watchdog restart of dnsmasq alone keeps the leases, so connected clients keep their addresses (Fable NET-7).
- The installer's API test called `/api/v1/health`, which no longer exists, and passed anyway after 60 s of `404`; it now calls `GET /api/v2/status` with the token and fails the installation if the API does not answer. The final summary no longer lists a health URL that does not exist.
- `uninstall.sh` removes what a stopped service leaves on the host (the `wilab-protect-existing` FORWARD rule, `/tmp/wilab-*`, the systemd-networkd rule, QoS IFB devices); `config.yaml` is still kept.

### 🔧 Maintenance

- The create job reports its outcome as a value instead of HTTP exceptions that no client received, and the synchronous create used only by the unit tests is gone; the create and network OpenAPI examples are module constants, and every error code is in one enum. The API contract is unchanged (Fable REV-16).
- `validate_interface_wireless`, `validate_interface_ap_mode` and `validate_interface` are gone: the AP-mode check was a substring search that proved nothing, and no start used them any more; discovery already establishes wireless and AP capability (Fable BUG-6).
- Dependencies: the installer no longer requires or installs `jq` (unused), `network-manager` (not supported any more, see Breaking Changes) and the system `python3-pip` (the venv has its own); it now checks `ip6tables`, `hostapd_cli`, `networkctl` and `usbreset` (package `usbutils`, needed by the USB recovery and so far never installed). `uvicorn[standard]` becomes `uvicorn` with `uvloop` and `httptools`, without the unused `watchfiles`, `websockets` and `python-dotenv`; `pytest-asyncio` leaves the development requirements. Docker stays: it builds the frontend.

### ✅ Tests

- New tests for unexpected start errors (REV-1), failed firewall checks (REV-3), a missing host guard chain (REV-4) and a stop failing in each phase (REV-7).
- The e2e re-probe test waits for the first re-probe (30 s after the quarantine) instead of reading the journal at once.
- The e2e watchdog tests that block dnsmasq take UDP port 67 after the failure they cause: dnsmasq of the running network already held it, so the three tests failed before testing anything.
- New unit tests from the 2026-11-26 review: cancel timeout, `404` reasons on every operation, cancel in each start phase and during the pause, tombstones, expiry during a start, stop retry budget, `restarts` counters, reserve by `interface`, cleanup backoff (unit-test-7 … 17).
- New e2e tests: `start_failed`, stop and release during a start, reserve by `interface`, `404` reasons, `restarts` counters, create during a repair, expiry, captive portal, lost host guard, Internet kept disabled (e2e-test-1 … 12, except 8).
- Unit tests for retries without a time budget (REV-5) and for cancelling watchdog restores, creates at shutdown and the DFS-free probe (REV-6); an adapter udev never renames (BUG-5); parallel shutdown within its budget (STAB-8); slow watchdog probes (WD-10); a stale gateway address no longer shifts the subnet after an unclean restart, already fixed by the discovery reset (NET-9); leases deleted at the end of a network and kept by a DHCP repair (NET-7).
- Unit tests create networks through the real asynchronous path (`202`, then polling) with the `create_network` helper (REV-16).

### 🔌 API changes from 4.0.0 (client migration)

- Strict types: send integers and booleans as JSON numbers and booleans. A string such as `"6"`, `true` for a number or `6.0` is now `422` in `POST /reservations`, `POST .../network` and `POST .../txpower` (REV-11).
- `POST .../txpower`: the body is `{"tx_power_level": 2}`; `{"level": 2}` is now `422` (API-6).
- **Not stable in 4.1:** TX power is under debugging (the drivers in use do not apply it reliably) and QoS profiles are experimental. Both may change in any release; the rest of the API is frozen for 4.1.
- `DELETE .../network` on a network that is not running now stops what a failed start may have left (hostapd, rules) before answering `200`; if that cleanup fails it answers `503 / 1012` with `Retry-After`, like any incomplete stop (REV-1). Before it answered `200` and left them.

---

## [4.0.0] - 2026-11-20

### 📊 Statistics

| Item | Count |
|---|---:|
| 🐛 Bug fixes | 35 |
| ⚠️ Breaking changes | 20 |
| 🔧 Maintenance changes | 11 |
| ✨ New features | 23 |
| ✅ Test changes | 4 |
| 📦 Commits since 3.0.0 | 129 |

Counts are the entries of the sections below and `git rev-list --count 3.0.0..aca248e` (`aca248e` is the last 4.0.0 commit, before the bump to 4.1.0).

### ⚠️ Breaking Changes

- Reservation contention returns null availability estimates when no release is scheduled.
- AP creation requires a single 2.4 GHz or 5 GHz band; `dual` returns 422.
- Release all reservations moved from `DELETE /api/v1/device-reservation` to `DELETE /api/v2/reservations/all`, and now requires the `X-Confirm-Password` header matching the new `protected_commands_password` setting (disabled when unset). A malformed single-release URL can no longer release everything.
- All `/api/v2` error bodies now use an object with `detail.code` and `detail.reason`. Clients displaying a former string `detail` should read `detail.message`.
- API timestamps (`expires_at`, `detail.next_available_at`) now use RFC 3339 UTC with a `Z` suffix. Durations and countdowns remain in seconds.
- Internet, TX power and QoS profile requests on a valid reservation without a running network return `409` with `detail.code: 1007` (`network_not_active`). Before, Internet, TX power and the QoS profile stop returned `404`, which clients could not tell apart from an expired reservation, and the QoS profile GET returned `200` with `active: false` (Fable API-2).
- The create body and `GET .../network` are grouped in sections: `radio`, `wifi` (with `security`), `internet`, `captive_portal`, plus `reservation` and `ip` in the answer. Duplicated and internal fields (`dhcp.*` paths and files, `clients_connected`, the second `interface` and `subnet`) are gone, and `ip.dns_server` is new. Flat bodies return `422` (Fable API-8; first step of ARCH-3).
- AP creation with `encryption: "wpa"` returns `422`: it silently created WPA2. Use `wpa2` for the same network, or the new `wpa1` for real legacy WPA/TKIP (Fable HAP-10).
- Configuration: the `networks` section is renamed `antennas`, and every entry must set `show_dfs: true|false`. An old `networks` section is ignored (`--validate-config` warns): Wi-Lab now manages every AP-capable Wi-Fi radio it finds, so a radio the host needs must be listed with `disable: true`.
- `GET /api/v1/interface/{id}/network/available-channels` is removed: use `GET /api/v2/antennas/{interface}`, which lists only the usable channels, grouped by band with the widths each can use, and needs no reservation.
- `GET /api/v2/status` no longer returns `checks`: it gives `degraded_reasons`, one entry per cause of `degraded` with a stable `code` (`antenna_quarantined`, `network_being_repaired`, `hostapd_not_running`, `dnsmasq_not_running`, `nat_rule_missing`, `upstream_unreachable`, `command_stuck`, `loop_stalled`, `cleanup_failed`, `network_stop_incomplete`), the `interface` it concerns and a `message`. The detail of the checks moved to the new `GET /api/v2/monitoring`.
- Every `409` has a `detail.code` (Fable API-3): `1008 network_already_active`, `1009 restoration_in_progress` and `1012 stop_incomplete` on the create, `1007 network_not_active` on stopping a stopped network, `1010 qos_profile_already_active` and `1011 qos_profile_not_active` on QoS profiles; before they had none and the client had to read the message. `404` on a call with a reservation ID now only means the ID is gone: an unknown QoS `profile_id` and a TX power the driver does not support answer `422` (were `404`), stopping a QoS profile that is not running answers `409 / 1011` (was `404`).
- Unknown fields in a request body are refused with `422` and the field path (`captive-portal: Extra inputs are not permitted`, `radio.chanel: ...`) instead of being ignored: a typo no longer creates a network without the intended setting (Fable API-10). Applies to the reservation, the create (every section), TX power and QoS profile bodies.
- The API prefix is `/api/v2` (was `/api/v1`): the contract changed, so the version in the URL changes too. `/api/v1` is not kept: every path under it answers `404`, with any method.
- Paths renamed (Fable API-6): `/api/v1/device-reservation` → `/api/v2/reservations`, and every `/api/v1/interface/{reservation_id}/...` → `/api/v2/reservations/{reservation_id}/...` (network, Internet, TX power, QoS profile). The old `interface` segment held a reservation ID, not an interface, which the new `/antennas/{interface}` would have made more confusing.
- **The create is asynchronous.** `POST .../network` checks the request and answers `202` at once with the network in `runtime_state: starting` (the same schema as `GET .../network`; was a synchronous `200` with `{"detail": "Network ... created successfully"}`); the client polls `GET .../network` until the outcome: the network (`runtime_state: null`), `runtime_state: start_failed` with `error` (non-radio failure, `1013` with `stage`, rolled back, reservation kept; was `500`), or `404` with `reason: reservation_invalidated` (every start failed, antenna quarantined; was `500`, with the reservation kept) or `reservation_expired`. Releasing the reservation or `DELETE .../network` during a start cancels it. The create needs no long read timeout any more: it could take up to 80 s (Fable API-4, API-5).
- The release (`DELETE /api/v2/reservations/{id}`, and release-all) stops the network and cleans up before it frees the antenna (3.0.0 freed it first), and still always answers `200`: if the cleanup fails (for example hostapd stuck in the kernel) the ID is gone anyway, the antenna stays held and the server repeats the cleanup in the background (5 s, 15 s, 60 s, then every 5 min), shown in `GET /status` as `cleanup_failed`. A held antenna counts as reserved (`409 / 1005`, with `next_available_in` until the next cleanup attempt, also when reserved by `interface`).
- `404` on every call with a reservation ID has a stable `detail.reason`: `reservation_released`, `reservation_expired`, `reservation_invalidated` (antenna quarantined) or `reservation_not_found` (never existed, or ended more than an hour ago); before it was one message for every case. Clients reserve again after `invalidated` or `expired`, and treat a release answered `404` as done.
- `GET /api/v2/status` lists the antennas in `antennas[]` (was `networks[]`), like the Antennas API: an entry is an antenna, reserved or not, not a network. Each entry has `reservation` (`null`, or `{expires_at, expires_in}` as in the reservation and network answers) instead of `reserved` and `reservation_remaining_seconds`, which could not tell a free antenna from an unlimited reservation, and `network_active` (Fable API-1).
- `GET /api/v1/debug` is removed: `GET /api/v2/monitoring` gives the health checks, and no endpoint lists other clients' reservation IDs any more (Fable SEC-2, API-1).

### ✨ Features

- Add an optional captive portal to AP creation (`captive_portal.enabled`): clients are held behind a page on the AP gateway until they press Sign in, which releases only that client. The page listens on the new optional `captive_portal_port` setting (default 8081; must differ from `api_port`, 53 and 67) and its address is reported in `captive_portal.url`.
- DFS channels (5 GHz 52–144) are chosen per antenna with `antennas[].show_dfs`: when `false` they are not listed and AP creation on them returns `422`; antennas not listed in the configuration offer them.
- Run backend tests, type checks and the frontend build in CI and publish API documentation.
- Export the current API schema and offline Swagger/ReDoc documentation.
- Explain adapter-dependent TX power control in the frontend.
- Skip AP subnets that overlap host IPv4 routes when selecting a DHCP subnet.
- Add an optional offline configuration check (`--validate-config`) with actionable errors and warnings.
- Radio startup failures (hostapd crash, beacon setup failure, radio or readiness timeout, interface lost during the start) are retried by the server during the create: up to 3 starts, 1 s apart, within 20 s, then after a 5 s and a 10 s pause; when every start fails the reservation is invalidated and the antenna quarantined. New reservations return `503 / 1002` or `1003` while recovery or quarantine leaves no antenna.
- New watchdog: a running network is repaired with the same reservation and expiry. A dead AP is restarted up to 3 times per hour per antenna (a failed restore is `runtime_state: restore_failed` and is retried with backoff); a dead dnsmasq is restarted up to 3 times per hour, then the whole network is; every 30 s a lost gateway address, `ip_forward`, NAT, Internet-block and isolation rules are repaired in place, and a broken captive portal restores the network (Fable WD-1, WD-2, WD-3, WD-7).
- Antenna recovery: a quarantined USB antenna is reset through its USB port (detected automatically) and returns to the pool only after an AP and DHCP test start; quarantined antennas with no USB recovery running are re-probed periodically and return without a service restart (Fable WD-4).
- Antenna discovery: AP-capable Wi-Fi interfaces (USB or built-in) are found automatically instead of being required in the configuration, at startup and then every 30 s (every 5 s while none is available), so Wi-Lab starts without antennas and adds those plugged in later without a restart. The `antennas` section only assigns display names, `show_dfs` and `disable: true`, and is re-read at each scan; unlisted interfaces use their interface name. With no usable adapter, reservations return `503 / 1003`.
- Frontend: requests answered `503 / 1006` (antenna busy) are repeated automatically after `Retry-After`, and `1006`/`1007` errors show a readable explanation.
- New `encryption: "wpa1"` (legacy WPA, PSK/TKIP, 802.11a/g only) to test old clients; accepted only on antennas whose driver supports TKIP (Fable HAP-10).
- AP creation takes optional `channel_width` (20, 40, 80 MHz) and `wifi_generation` (4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax); defaults 20 MHz / 802.11n keep the previous behaviour. `GET /antennas/{interface}` lists per band the generations, widths and channels an antenna accepts, and `GET .../network` reports the width the radio actually uses (Fable HAP-11).
- Frontend: the start dialog reads the antenna (`GET /antennas/{interface}`) and offers in dropdowns only the encryptions, Wi-Fi generations, channel widths and channels it supports (DFS channels marked, `wpa` replaced by `wpa1` where available), and a running network shows its width and Wi-Fi generation.
- New `GET /api/v2/monitoring` (System, token only): `status`, `degraded_reasons`, `checked_at`, `check_interval_seconds` and the detail of every health check (`commands`, `loops`, `hostapd`, `dnsmasq`, `iptables_nat`, `upstream_interface`), for operators and a future monitoring view.
- Optional `hostapd_debug_dir` setting: every hostapd start that fails writes a report there (hostapd configuration without passwords and the last 400 lines of `hostapd -d`); only failures are written and the newest 100 reports are kept.
- New **Antennas** API, listed in Swagger before Network and readable with the token only: `GET /api/v2/antennas` lists the managed antennas (`display_name`, `interface`); `GET /api/v2/antennas/{interface}` gives `device` (`bus`, `address`, `driver`), `encryptions` and per band the Wi-Fi generations with their widths and the usable channels with the widths each can use, to fill a form's dropdowns.
- Frontend: a captive portal switch on each reserved antenna card chooses whether the next network starts with a portal page (it presets the start dialog, which has the same switch), and a running network shows the captive portal as On or Off with its URL and a header badge.
- `POST /api/v2/reservations` takes an optional `interface` to reserve a given antenna (from `GET /api/v2/antennas`); without it the first free one is reserved, as before. A reserved antenna answers `409 / 1005` with the expiry of its reservation, a quarantined one `503 / 1002` or `1003`, an unknown one `422`.
- The same create body again is safe: `202` while that start runs (no second AP), `200` with the network once it runs; another body answers `409 / 1008`. After a lost answer the client sends the same create again or just polls.
- Frontend: a banner lists why the service is `degraded` (`degraded_reasons` of `GET /status`, with the antenna names), for example an antenna held by a failed cleanup or a half-stopped network.
- `GET .../network` has a `restarts` section (`ap`, `dhcp`, `last_at`, `last_reason`) counting the watchdog repairs over the whole reservation: a client reads it before and after a test to know whether the AP was interrupted, without polling `runtime_state`.

### 🐛 Bug Fixes

- Keep Wi-Lab radios away from NetworkManager and systemd-networkd (runtime rule under `/run`) from discovery on, also after a USB re-enumeration; 3.0.0 released a radio from NetworkManager only at each AP start.
- Disabling Internet also cuts the connections already open: forwarded TCP traffic of the clients of that AP is reset.
- After an unclean shutdown, startup removes Wi-Lab's stale firewall rules without flushing host chains, stops orphan hostapd/dnsmasq, removes stale runtime files (including a dnsmasq PID file that failed every start) and Wi-Lab's QoS devices, and resets each radio (no address, no leftover netem/HTB) when discovery adds it (Fable STAB-4).
- Restrict each Wi-Lab masquerade rule to the corresponding AP subnet.
- Listen on the configured API port instead of always using 8080.
- Refuse at startup a `country_code` that is a regulatory region (`EU`, `ETSI`, `FCC`) or not two uppercase letters.
- Prevent concurrent reservations in one service process from sharing an antenna.
- Stop active QoS profiles when their network is released or expires.
- Leave a radio in managed mode and down after a network stops instead of bringing it up again, to avoid an unnecessary activation cycle.
- Verify that the access point is enabled before assigning its gateway and starting DHCP. Roll back incomplete network starts.
- Clean up timed-out access point starts by tracking hostapd directly instead of waiting for a PID file.
- Keep independent API requests, other adapters and the system status responsive during a slow AP startup or cleanup; a request on an antenna that another operation holds for more than 5 s answers `503 / 1006 device_busy` with `Retry-After: 2` (Fable RACE-1).
- A channel refused from the cached channel list is checked once more against a fresh `iw` reading, so 5 GHz channels cached before the regulatory domain was applied are no longer refused until a restart; the API and the TX power code share one channel cache, refreshed after a USB recovery or a failed start (Fable BUG-4).
- `/status` health checks now look at Wi-Lab's own processes and rules per network: a network without Internet is no longer `degraded` on a host without NAT rules, Docker's MASQUERADE no longer hides a missing Wi-Lab rule, a link that is DOWN is no longer reported up, and hostapd is checked too (in `GET /monitoring`: `checks.hostapd` and `missing` lists) (Fable BUG-2).
- An AP start runs fewer host commands: no repeated wireless/AP capability checks (established by discovery), no `dnsmasq --version`, and `nmcli` is looked up once instead of on every start (Fable PERF-1).
- Swagger examples now match the real responses: no `device_id` field that the API never returns, and unused QoS models removed; a test checks every `200` example against its model (Fable API-9).
- With `upstream_interface: auto`, Wi-Lab follows the default route when it moves to another interface: new networks use it and the NAT of running networks is moved within 30 s, instead of naming the old interface until a restart (Fable STAB-6).
- Clients of a Wi-Lab network can no longer reach the Wi-Lab host (API, SSH, other services, also over IPv6): only DHCP, ping and, with the captive portal, DNS and the portal page are allowed (Fable SEC-3).
- A dnsmasq launch that timed out before writing its PID file is found by its configuration file and stopped, instead of being left running (Fable NET-6).
- If a Wi-Lab background loop stalls, `/status` reports it and the service restarts itself through the systemd watchdog, but only when no reservation is active; this needs the new service unit (`Type=notify`, `WatchdogSec=90s`): install the service again (Fable STAB-1).
- A host command stuck in the kernel (hung Wi-Fi driver) no longer freezes its thread and eventually the API: Wi-Lab stops waiting 2 s after SIGKILL, fails the operation and reports it (`degraded_reasons` `command_stuck` in `/status`, `checks.commands.stuck` in `/monitoring`) (Fable STAB-1).
- A network whose NAT or isolation rules cannot be installed now fails (`start_failed` with its `stage`) instead of reporting success, and is rolled back (Fable NET-2); the false "Isolation disabled for testing" log line is gone (Fable NET-4).
- `iptables` calls wait up to 5 s for the xtables lock instead of failing when another program holds it (Fable NET-1).
- Stopping a network on a disconnected adapter completes its cleanup (Fable WD-5).
- The create request is validated before touching the antenna: SSID, password and channel rules, and no line injection into `hostapd.conf` (Fable BUG-1).
- `wpa3` and `wpa2-wpa3` networks no longer write `wpa_key_mgmt` and `ieee80211w` several times in `hostapd.conf` (they worked only because hostapd keeps the last one); the mixed mode now requires PMF for WPA3 clients only, and SAE accepts H2E (Fable HAP-10).
- The service refuses to start with an empty `auth_token`, `api_port` outside 1–65535, `max_timeout` below `min_timeout` or a `dns_server` that is not an IPv4 address; before, `dns_server: foo` started and every network creation failed with `500` (Fable BUG-3).
- Networks are isolated from each other whatever `dhcp_base_network` is: with subnets outside `192.168.*` (e.g. `10.20.0.0/24`) no isolation rule was installed and clients of different networks could talk to each other (Fable NET-3).
- A `DELETE .../network` that cannot stop hostapd (stuck in the kernel after SIGKILL, seen with mt7921u firmware timeouts) no longer answers `200` with the process left behind: the server repeats the stop every 2 s for up to 15 s, then answers `503 / 1012 stop_incomplete` with `Retry-After: 5`. The half-stopped network reports `runtime_state: stop_failed` (also in `/status`), repeating the DELETE finishes the stop, and a create on that reservation answers `409 / 1012` until then.
- `/status` no longer runs host commands on every call: the checks (processes, NAT rules, upstream link) are refreshed every 10 s in the background and `/status` reads the latest result, so a change takes up to 10 s to show.
- An unexpected server error answers `500 / 500` without closing the connection: before, uvicorn dropped it after the answer, so the client's next request on the same keep-alive connection failed with a transport error.
- Normal answers are no longer logged as errors: a missing `iptables -C` rule, a `tc` qdisc with nothing to delete, `iw set txpower` unsupported by the driver and a stop without DHCP are logged at debug level, and QoS uses `tc ... replace` instead of a failing `add` (Fable NET-5).
- The log line `Starting network ... with SSID` is written only for a create that really starts, not for one refused because the network is already active.
- 6 GHz channels are no longer listed as 5 GHz channels (in 3.x `available-channels`, now `GET /antennas/{interface}`): Wi-Fi 6E antennas added 59 channels that cannot be used, some with the same number as a 5 GHz channel (e.g. two `149`).
- Every `422` message starts with the path of the refused field written with dots (`radio.channel: ...`, `wifi.security.password: ...`), without pydantic's `Value error, ` prefix, also for rules between fields and antenna checks.

### 🔧 Maintenance

- Read the configuration once at startup.
- Fix the PyYAML type-stub requirement for fresh development installs.
- Report an empty internal command consistently across platforms.
- **hostapd regulatory compliance** — The generated hostapd configuration now enables `ieee80211d=1` (advertise country code and apply the regulatory domain) on all bands, and `ieee80211h=1` (DFS/TPC) on 5 GHz where regulatory rules require it.
- Documented safe recovery of a blocked USB Wi-Fi adapter.
- Added an [AP creation procedure](docs/ap-creation-procedure.md) for client developers, with a [sequence diagram](docs/ap-creation-procedure.md#3-sequence-diagram) of the whole flow from reservation to release and one action (done, wait, repeat, fix, reserve again, stop) for every answer of every call, and a backend [architecture](docs/architecture.md) guide with startup, threading, creation, retry, watchdog and recovery diagrams and the [server view](docs/architecture.md#61-end-to-end-sequence-server-view) of the same flow.
- Explain the reservation and recovery lifecycle in Swagger and ReDoc, including retry, quarantine and watchdog response examples.
- Include the API operation, HTTP status, and error code in journal entries for server errors, without request or response data.
- New [docs/error-codes.md](docs/error-codes.md): every `detail.code`, its HTTP status, `Retry-After`, where it is answered and the client action, plus the `degraded_reasons` codes; a test fails when a code is not documented.
- Document `GET /api/v2/status` health values (`standby`, `ok`, `degraded`), what makes the service `degraded` (quarantined adapter, network being repaired, failed health check) and how clients learn about quarantined adapters, in Swagger (three response examples), the API overview, the AP creation procedure (2.8) and the Swagger guide.
- `wilab/wifi` is a regular Python package (`__init__.py`) like `wilab/network` and `wilab/api`, instead of an implicit namespace package (Fable ARCH-12).

### ✅ Tests

- Add regression coverage for authentication on protected reservation endpoints.
- Test unique concurrent reservations and device reuse on a ten-antenna pool.
- Added `TestHostapdConfigGeneration` covering the presence of `ieee80211d` on all bands and the band-dependent handling of `ieee80211h` (enabled on 5 GHz, absent on 2.4 GHz).
- Tests are split into `tests/unit-tests/` (the existing suite: mocked hardware, run by `make test-local` and CI) and `tests/e2e-tests/` (new). The e2e tests run on the Wi-Lab machine against the running service and combine API calls with server actions: journal checks, the SSID on the air via `iw`, and USB unplugs simulated through sysfs. They cover the API contract, create validation, firewall rules, watchdog repairs, device loss and return, unclean restarts and create/delete stability, are skipped unless `WILAB_E2E=1`, and have their own flags for USB unplugs and long tests (`make test-e2e`, `make test-e2e-usb`, see `docs/e2e-testing.md`).

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
| `GET /api/v1/status`, `GET /api/v1/qos/profiles` | `GET /api/v2/status`, `GET /api/v2/qos/profiles` |
| `GET /api/v1/debug` | removed: `GET /api/v2/monitoring` |

The rest of this chapter names each endpoint by its 3.x path.

**All endpoints**

- Error body: `detail` is an object `{code, reason, message, ...}` (was a string, or `{error, ...}` on reserve). Branch on `detail.code`, show `detail.message`.
- Timestamps (`expires_at`, `detail.next_available_at`): RFC 3339 UTC, e.g. `2026-11-19T23:00:00Z` (was `YYYY-MM-DD HH:MM:SS`, UTC in the reservation and local time in `next_available_at`, and ISO 8601 with `+00:00` in `GET .../network`).
- `404` on a call with a reservation ID: `detail.reason` is `reservation_released`, `reservation_expired`, `reservation_invalidated` or `reservation_not_found` (was one message). Reserve again after `invalidated` or `expired`.
- Every request body: unknown fields answer `422` (were ignored).

**Reservation**

- `DELETE /api/v1/device-reservation` (release all): removed. Use `DELETE /api/v2/reservations/all` with header `X-Confirm-Password`.
- `POST /api/v1/device-reservation`:
  - `409`: now `detail.code: 1005`; `next_available_at` / `next_available_in` are `null` when no release is scheduled.
  - new `503 / 1002`: an antenna is recovering; retry after `Retry-After` (10 s).
  - new `503 / 1003`: no usable antenna (all quarantined or none found).
  - new optional `interface`: reserve that antenna only (see Features).
- `DELETE /api/v1/device-reservation/{reservation_id}`: still `200`, now after the network is stopped and cleaned up. A failed cleanup is repeated by the server, which keeps the antenna held meanwhile: `POST` answers `409 / 1005`, with `next_available_in` the time to the next cleanup attempt.

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
  - asynchronous: `202` with `runtime_state: starting`, then poll `GET .../network` (was a synchronous `200` with `{"detail": "Network ... created successfully"}`). Outcomes: the network; `start_failed` with `error` (`1013`, `stage`; was `500`); `404` with `reason` `reservation_invalidated` (every start failed and the antenna is quarantined; was `500`, with the reservation kept) or `reservation_expired`.
  - radio failures are retried by the server during the start, never by the client.
  - `409 / 1008`: a network with different settings runs or is starting (was a `409` without code, also for the same body, which now answers `202` or `200`); new `409 / 1009`: a watchdog repair in progress; new `409 / 1012`: the last stop did not complete, repeat the DELETE then the create.
  - `DELETE .../network` or a release during the start cancels it.
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
  | — | `restarts` (`ap`, `dhcp`, `last_at`, `last_reason`): watchdog repairs over the reservation, present even when the network is not running |

  `interface` and `active` stay at the top level, with the new `runtime_state` (`starting`, `start_failed`, `restoring_ap`, `restoring_dhcp`, `dhcp_failed`, `restore_failed`, `stop_failed`; `null` otherwise), `error` (set with `start_failed`) and `restarts`.
- `DELETE /api/v1/interface/{id}/network`: a stopped network answers `409 / 1007` (was a `409` without code). It also cancels a start in progress and a pending `restore_failed`. New `503 / 1012` (`stop_incomplete`) + `Retry-After: 5` when the stop does not complete even after the server repeated it for 15 s (`runtime_state: stop_failed`): repeat the DELETE.
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

**Internet, TX power, QoS profile**

- No running network: `409 / 1007` on Internet enable/disable, TX power GET/POST and QoS profile POST/GET/DELETE. Before: `404` on Internet, TX power and QoS profile DELETE, `200` with `active: false` on QoS profile GET, `409` without code on QoS profile POST.
- `404` on these endpoints now only means the reservation is gone. Unknown QoS `profile_id` and unsupported TX power: `422` (were `404`).
- QoS profile: starting one while another runs answers `409 / 1010` (was a `409` without code); stopping one that is not running answers `409 / 1011` (was `404`).

**Every `/api/v1/interface/{id}/...` endpoint except the create**

- New `503 / 1006` + `Retry-After: 2`: the antenna is busy with another operation. Repeat the request.

**Status**

- `GET /api/v1/status`:
  - `networks[]` is renamed `antennas[]`. In each entry `reserved` and `reservation_remaining_seconds` become `reservation` (`null`, or `{expires_at, expires_in}`; both `null` when unlimited), and `network_active`, `recovery_state` (`recovering`, `unavailable`) and `runtime_state` are new. What an antenna supports is in `GET /api/v2/antennas/{interface}`.
  - `checks` moved to `GET /api/v2/monitoring` (with `hostapd`, `commands`, `loops`, and `missing` lists in `dnsmasq` and `iptables_nat`); `/status` has `degraded_reasons` instead (`{code, interface, message}`).
  - `degraded` now also covers quarantined antennas, networks being repaired or half stopped, failed cleanups, stuck commands and stalled loops.
- `GET /api/v1/debug`: removed; use `GET /api/v2/monitoring`.

**Configuration**

- `networks:` → `antennas:`; each entry needs `show_dfs: true|false` (DFS channels offered or not). An old `networks:` section is ignored.
- Every AP-capable Wi-Fi radio is managed, listed or not: add `disable: true` to the entry of a radio the host needs.
- New optional `protected_commands_password`: required to use release-all (`403` without it).
- New optional `captive_portal_port` (default 8081), the port of the captive portal page on each AP gateway.
- New optional `hostapd_debug_dir`, for diagnostics of failed hostapd starts.
- The systemd unit changed (`Type=notify`, `WatchdogSec=90s`): install the service again to get the restart of a stalled service.

**Error codes**

- Full list, with the HTTP status, `Retry-After` and the client action of each code: [docs/error-codes.md](docs/error-codes.md).

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

