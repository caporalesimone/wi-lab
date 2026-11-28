# Changelog

All notable changes to Wi-Lab are documented in this file.

How it is written: in each version the sections come in the order Breaking Changes, Features, Bug
Fixes, Maintenance, CI/CD, Tests, then the client migration chapter of the API. Entries are short
and written for whoever uses or installs Wi-Lab; tests are listed only when they tell something
useful. Every fix adds its line in the same commit, and a change of an already dated version
updates its date.

---

## [4.1.0] - Unreleased

### 📊 Statistics

| Item | Count |
|---|---:|
| ⚠️ Breaking changes | 13 |
| ✨ New features | 7 |
| 🐛 Bug fixes | 35 |
| 🔧 Maintenance changes | 17 |
| 🔄 CI/CD changes | 2 |
| ✅ Test changes | 8 |
| 📦 Commits since 4.0.0 | 112 |

Counts are the entries of the sections below and `git rev-list --count aca248e..HEAD` (`aca248e` is the last 4.0.0 commit), as of 2026-11-27.

### ⚠️ Breaking Changes

- Every `config.yaml` setting is required: `api_port`, `captive_portal_port`, `max_timeout`, `min_timeout`, `allow_unlimited_reservation`, `upstream_interface`, `country_code`, `internet_enabled_by_default`, `protected_commands_password` and `cors_origins` (the last two may be `null`). Only `hostapd_debug_dir` and `antennas` may be omitted. A missing key stops the service and names it: compare your file with `config.example.yaml`.
- `config.yaml` needs a `watchdog:` section with `ap_restores` and `dhcp_restarts` (`limit` and `window_minutes` each); `drivers` is optional. The 4.0.0 values are `{limit: 3, window_minutes: 60}`: copy the section from `config.example.yaml`.
- `dns_server` is required in `config.yaml`. Its old default, `192.168.10.21`, was a laboratory address that left Wi-Fi clients without DNS elsewhere (Fable NET-8).
- `log_level` is required in `config.yaml`, as its first setting: `DEBUG`, `INFO`, `WARNING` or `ERROR` (copy the block of `config.example.yaml`, which explains what each level writes). At `INFO` the successful reads (`GET`, `HEAD`, `OPTIONS`) of the HTTP access log are no longer written: clients' polling was most of the journal; changes and failed requests still are.
- `antennas[].show_dfs` is renamed `show_dfs_channels`, without an alias: the old name stops the service with a message naming the new one.
- Ubuntu Server 25.04 or newer is required, not only tested (tested on Ubuntu Server 26.04.1 LTS, kernel 7.0.0-44).
- NetworkManager is no longer supported: the host network must be on systemd-networkd. The installer offers to disable and mask NetworkManager and `wpa_supplicant`, never when the host needs them; `uninstall.sh` offers to re-enable them. When upgrading, run the installer again (Fable NM-1).
- The reservation and create bodies accept only the JSON types they document: `"6"`, `true` or `6.0` for an integer, or `"false"` and `0` for a boolean, are `422` (Fable REV-11).
- `GET` and `POST .../txpower` are removed. The MT7921U in AP mode ignores the level (always about 18 dBm, measured per level on 2026-11-28), the reported value was always 3 dBm, and changing the power of a running AP detached the adapter and hung the VM. The level is still set once at creation (`radio.tx_power_level`).
- `GET /status` is the only system status: `version`, `service`, and the health checks of the former `GET /monitoring` (`checked_at`, `check_interval_seconds`, `checks`). `GET /monitoring` is removed. `antennas` and `reservation_policy` moved to `GET /api/v2/antennas`, which also has `free_antennas` (the same value as `service.free_antennas`).
- The access point endpoints move from the reservation to their own path, and "network" becomes "access point" in the API: `POST`/`GET`/`DELETE /reservations/{id}/network` → `/access-point/{id}`, `.../internet/enable|disable` → `/access-point/{id}/internet/enable|disable`; `network_active` → `access_point_active`; error reasons `network_not_active` (1007) and `network_already_active` (1008) → `access_point_not_active` and `access_point_already_active`; `degraded_reasons` codes `network_being_repaired` and `network_stop_incomplete` → `access_point_being_repaired` and `access_point_stop_incomplete`. QoS profiles stay under `/reservations/{id}/qos/profile` (experimental).
- `GET /antennas/{interface}` is the antenna now: `interface`, `display_name`, `device`, its state as in `GET /antennas` (`reservation`, `access_point_active`, `recovery_state`, `runtime_state`) and `health`. `encryptions` and `bands` moved to the new `GET /antennas/{interface}/capabilities`, which does not change while the adapter stays the same. In every antenna object `interface` is the first field.
- `GET /status`: the string `status` (`standby`, `ok`, `degraded`) and the top-level `degraded_reasons`, `active_networks` and `restart_required` are replaced by one object, `service`: `{"health": "good" | "degraded", "free_antennas": N, "degraded_reasons": [...], "restart_required": null | {...}}`. `free_antennas` counts the antennas a reservation would get now; the running networks are `antennas[]` of `GET /antennas` with `access_point_active: true`.

### ✨ Features

- Optional 802.11n/ac features: the access point announces those its antenna supports (short guard interval, LDPC, STBC, larger frames, beamformee; hostapd `ht_capab` and `vht_capab` read from `iw phy`). Before, it announced none, so Wi-Fi 4 and 5 links were about 10% slower and less robust than the adapter allows. `radio.enable_ht_vht_capab: false` keeps the old minimal AP; the web UI card shows it and the fallback, with an explanation on hover.
- Wi-Fi generation without fallback: `radio.enable_generation_fallback: false` in the create accepts only clients of `wifi_generation` or newer (hostapd `require_ht`, `require_vht`, `require_he`); the default `true` keeps today's behavior. `GET /access-point/{reservation_id}` reports it in `radio`, and the web UI has an "Accept older Wi-Fi generations" checkbox.
- `GET /status` has `restart_required`: which installed security updates need a restart of Wi-Lab or a reboot, since when, and a sentence; the web UI shows it as a red bar. Wi-Lab never restarts by itself: the installer excludes it from needrestart, which had restarted it after an unattended upgrade and dropped every network.
- `GET /antennas/{interface}` has `health`: AP restores and DHCP restarts used against the limit of the antenna's driver, when the next one frees, quarantines and the last USB reset.
- The watchdog's repair budgets are set in the `watchdog:` section of `config.yaml`, with optional values per kernel driver (`watchdog.drivers.mt7921u.ap_restores.limit: 5`). The journal shows each antenna's driver and budget when it is added.
- `make reload-drivers` reloads the kernel driver of the Wi-Fi adapters, with the service stopped, for an adapter whose firmware hangs and crashes hostapd at every start. It never reloads the driver of the host's own network interface (Fable ARCH-11 D1).
- Startup prechecks: without root or a required command the service exits with code `78` and systemd does not restart it; an active NetworkManager, a radio held by `wpa_supplicant` or leftover Wi-Lab rules are a `WARNING` (Fable NM-1). Reinstall the systemd unit.

### 🐛 Bug Fixes

- **Security:** the web UI route no longer serves files outside its directory: `//etc/shadow` or `/../config.yaml` exposed any file of the host, the auth token included, without authentication. If the API port was reachable from outside the lab, change `auth_token` and `protected_commands_password` (Fable SEC-1).
- **Security:** Swagger UI (`/docs`) no longer prints the token in clear in the cURL command shown after "Execute": `Authorization` and `X-Confirm-Password` appear as `********`; the request is still sent with them.
- **Security:** the Bearer token is compared in constant time, so it cannot be guessed from response times (Fable BUG-8).
- A start that fails with an unexpected error is rolled back like any other: the AP no longer keeps transmitting after `start_failed` (Fable REV-1).
- A create on an antenna that disappeared just before it answers `202` and ends like any lost antenna, instead of a generic `500`.
- A stop that cannot end hostapd keeps the host guard and isolation rules until a repeated stop succeeds (Fable REV-7).
- A firewall check that fails (xtables lock held by another tool) no longer counts as a missing rule: the watchdog skips the round instead of restoring a healthy network (Fable REV-3).
- A host firewall reload that removed a network's host guard no longer quarantines the antenna at the next stop (Fable REV-4).
- A retry that brings the AP up after 20 s is kept, instead of being reported as `start_failed` (Fable REV-5).
- Releasing a reservation while the watchdog restarts its AP is immediate; the service stop cancels running creates instead of waiting for them (Fable REV-6).
- An adapter that udev never renames is used after 3 scans, with a warning, instead of being ignored forever (Fable BUG-5).
- The service stop releases antennas in parallel and ends within systemd's timeout (now 60 s), instead of being killed half-way. Reinstall the systemd unit (Fable STAB-8).
- On a loaded host, slow answers of hostapd no longer restart a healthy AP: only 3 real "not ENABLED" answers, or 6 probes without an answer, do (Fable WD-10).
- A network's DHCP leases are deleted when it ends: the next user no longer sees the previous clients. A DHCP repair keeps them (Fable NET-7).
- A start that ignores a cancel is no longer forgotten while it runs: `DELETE /access-point/{reservation_id}` answers `503 / 1006` until it ends, then `200` or `409 / 1007` (Fable REV-8).
- Cancelling a start whose rollback fails no longer quarantines the antenna: the release answers `200`, `DELETE /access-point/{reservation_id}` answers `503 / 1012` until the stop completes (Fable REV-2).
- `stop_failed` appears only after the client's own `DELETE /access-point/{reservation_id}` failed. On a half-stopped network, Internet and QoS answer `409 / 1012` (Fable REV-9).
- A watchdog restore whose cleanup fails once shows `restore_failed` and is retried 15 s later, instead of ending the reservation with a USB reset (Fable REV-10).
- A radar event on a DFS channel is no longer an AP fault: the watchdog waits for hostapd's radar check (up to 75 s), and `channel` shows the channel the AP moved to (Fable REV-12).
- An antenna unplugged for good leaves the pool after about 2 minutes when nothing holds it, so `/status` is no longer `degraded` until a restart; it is added again if it comes back (Fable WD-5).
- Weather-radar channels 120, 124 and 128 are no longer offered and are `422` in the create: their 10-minute radar check always failed the start (Fable HAP-9).
- A clock jump (NTP, a resumed VM) no longer expires or stretches reservations and networks. Reinstall the systemd unit (Fable STAB-5).
- hostapd and dnsmasq runtime files move from `/tmp` to `/run/wilab`, readable by root only. Reinstall the systemd unit (Fable STAB-2).
- The last 40 lines of `hostapd -d` reach the journal when a start fails or hostapd dies, without passwords or keys (Fable HAP-8).
- A wrong custom QoS profile is skipped with a warning instead of stopping the service (Fable BUG-9).
- Inline QoS with different download and upload qualities, or a quality with `advanced`, answers `422` instead of applying only one (Fable NET-11).
- Internet requests answer `500`, not `404`, for an internal error, so a client does not take its reservation for ended (Fable REV-11).
- `next_available_in` of a `409 / 1005` is rounded up like `GET /status` (Fable REV-11).
- The installer's API test checks `GET /api/v2/status` and fails the installation if the API does not answer; it called an endpoint that no longer exists.
- `uninstall.sh` removes what a stopped service leaves: the `wilab-protect-existing` rule, `/tmp/wilab-*`, the systemd-networkd rule and QoS devices. `config.yaml` is kept.
- Web UI, create: a cancelled start is no longer "started successfully", a transient error no longer ends the start, Stop and Release stay usable, and every `404` reason is a sentence (Fable REV-13).
- QoS: a step or inline request with only `advanced` (no speed, no quality) was removed right after being applied; it now stays until the next step or the stop.
- Web UI: a reload keeps the saved reservations unless the server answers `404`; Stop is enabled wherever the server accepts it; the dialog requires a password and counts bytes like the server (Fable REV-14).
- Web UI: a connection error no longer suggests a CORS problem (Fable REV-17).
- Web UI: the captive portal is chosen only in the create dialog; the antenna card no longer has its own toggle and shows only whether the running access point has a portal.

### 🔧 Maintenance

- QoS catalogue (experimental) rewritten with realistic values: every network profile limits the bandwidth, latency and loss are moderate and per direction (`satellite_link` 300 ms each way), outages are `packet_loss_percent: 100`, no jitter, no corruption; the single-pass profiles hold their last step (`once-hold-last`). Same ids.
- The journal tells real problems apart: `ERROR` only when someone must act. Lines carry their syslog priority (`journalctl -u wi-lab -p err` works) and `[ant=… res=…]`; the TX power warning appears once an hour per antenna (Fable ARCH-10).
- Each AP keeps one control connection to hostapd instead of a `hostapd_cli` every 5 s: a crashed AP is restored in about a second (Fable PERF-4).
- dnsmasq runs as a foreground child like hostapd, without PID files: an early failure reports dnsmasq's own message (Fable ARCH-6).
- `requirements.lock` pins the tested dependency versions for the installer, the Makefile and CI; `make lock` regenerates it (Fable STAB-7).
- Dependencies: `jq`, `network-manager` and the system `python3-pip` are no longer installed; `ip6tables`, `hostapd_cli`, `networkctl` and `usbreset` are checked. `uvicorn` drops unused extras.
- A command timeout is the value passed, without a hidden 5 s minimum (Fable PERF-5).
- Internet and QoS requests no longer read the radio only to check that the network runs; the client list is reused for 1.5 s (Fable PERF-2).
- The network manager is split into smaller modules: start retries, TX power, client list, subnets (Fable ARCH-1).
- Start failures are classified once, where they happen (Fable ARCH-2).
- A running network is stored apart from its API answer; the watchdog restarts it from the original request (Fable ARCH-3).
- One device registry holds the antennas and their locks (Fable ARCH-4).
- The service's parts are built once and started and stopped in a fixed order (Fable ARCH-5).
- The create job reports its outcome as a value; error codes are in one enum (Fable REV-16).
- Dead code removed, `flush_all_rules` included, which would have emptied the host's whole NAT table (Fable ARCH-9), and the AP-mode check that proved nothing (Fable BUG-6).
- Leftovers removed: the dead `1004` path, test-only helpers, a duplicate error handler; one module deletes Wi-Lab's firewall rules by comment (Fable REV-17).
- One `pyproject.toml` configures pytest, ruff and mypy; ruff's rules are pinned and `make lint` is clean. `update_version.sh` moves to `scripts/`, `run-tests.sh` is gone (Fable ARCH-11 A2–A4).

### 🔄 CI/CD

- CI runs `make lint` too, and prints the unit coverage report (`make test-local`; `make test-local-quick` stays without it) (Fable ARCH-11 A3, A5).
- CI installs the exact versions of `requirements.lock` (Fable STAB-7).

### ✅ Tests

- A 14-hour simulation in about a second (`test_soak.py`): crashes, slow probes, xtables lock failures and failed starts within the watchdog budgets; every network must survive with no `ERROR` logged (T-20).
- New e2e tests for the asynchronous create, its cancels and `404` reasons, `restarts`, the captive portal, the host guard, a `kill -SEGV` of hostapd and the stop of a frozen hostapd.
- The long run adds a burst test on every antenna with a chaos monkey that kills hostapd and dnsmasq; each must come back by itself within 45 s.
- The long run ends by checking that the service's memory, descriptors and threads did not grow (PERF-7).
- Web UI specs for the create (`make frontend-test`, no browser) (unit-test-15).
- The web UI route is tested against `..`, absolute and `//` paths (T-01).
- Unit tests create networks through the real asynchronous path (REV-16); unit coverage is 94 %.
- Unit tests for every failure branch of the watchdog, radar checks, antenna retirement and the client list.

### 🔌 API changes from 4.0.0 (client migration)

- `POST /access-point/{reservation_id}`: new optional `radio.enable_ht_vht_capab` (default `true`: the AP announces the optional 802.11n/ac features of the antenna; `false`: none, as before). `radio` of `GET /access-point/{reservation_id}` has it. The body is unchanged for existing clients; their networks now announce the features.
- `POST /access-point/{reservation_id}`: new optional `radio.enable_generation_fallback` (default `true`, today's behavior); `false` refuses clients older than `wifi_generation`, and with `wpa1` it is `422`. `radio` of `GET /access-point/{reservation_id}` has it. Additive.
- Access point: call `/access-point/{reservation_id}` instead of `/reservations/{reservation_id}/network` (same methods, bodies and answers), and `/access-point/{reservation_id}/internet/enable|disable`. Read `access_point_active` instead of `network_active`, and compare `detail.reason` and `degraded_reasons[].code` with the `access_point_*` names (codes 1007 and 1008 are unchanged). Success messages in `detail` changed wording (`Access point on wls16 stopped`): do not parse them.
- `GET /status`: read `service.health` (`good` or `degraded`) where you compared `status` with `"degraded"` (`standby` and `ok` are gone), `service.degraded_reasons` instead of `degraded_reasons`, and `service.restart_required` (always present, `null` when nothing is needed) instead of `restart_required`. `active_networks` is removed: count `antennas[]` with `access_point_active: true`. `service.free_antennas` says how many antennas are free right now; to get one, reserve it, since another client may take it in between.
- `GET /status` no longer has `antennas` and `reservation_policy`: read them from `GET /api/v2/antennas` (`{free_antennas, reservation_policy, antennas}`; each antenna starts with `interface`). `GET /monitoring` is removed: its `checked_at`, `check_interval_seconds` and `checks` are in `GET /status`.
- `GET /antennas/{interface}`: read `encryptions` and `bands` from `GET /antennas/{interface}/capabilities` (same content); the antenna itself now also has `reservation`, `access_point_active` and, when set, `recovery_state` and `runtime_state`, as in `GET /antennas`. A `503` (radio being reset) comes only from `.../capabilities`.
- `GET /status` is documented by a schema in Swagger: required fields, `null` values shown in the examples, `recovery_state` and `runtime_state` present only when set.
- `GET /status`: `checks.upstream_interface` gives the interface data (`operstate`, `mac`, `mtu`, `ipv4` and `ipv6` addresses with prefix, `gateway`) instead of `up`, `has_ip` and `reachable`; it is information only. The `degraded_reasons` code `upstream_unreachable` is gone: the host uplink no longer makes the service degraded.
- Strict types: send integers and booleans as JSON numbers and booleans. A string such as `"6"`, `true` for a number or `6.0` is now `422` in `POST /reservations` and `POST /access-point/{reservation_id}` (REV-11).
- `GET` and `POST /reservations/{reservation_id}/txpower` are removed, with no replacement: set `radio.tx_power_level` in the create. On the MT7921U the level has no effect in AP mode, and `radio.tx_power.reported_dbm` is not a measurement.
- **Not stable in 4.1:** `radio.tx_power_level` has no effect on the MT7921U, and QoS profiles are experimental. Both may change in any release; the rest of the API is frozen for 4.1.
- `DELETE /access-point/{reservation_id}` on a network that is not running now stops what a failed start may have left (hostapd, rules) before answering `200`; if that cleanup fails it answers `503 / 1012` with `Retry-After`, like any incomplete stop (REV-1). Before it answered `200` and left them.
- Internet and QoS profile requests can answer `409 / 1012` (`stop_incomplete`): the last `DELETE /access-point/{reservation_id}` did not complete; repeat it until `200` (REV-9).
- Cancelling a start (release or `DELETE /access-point/{reservation_id}`) whose rollback fails: the release answers `200` (before: `404 reservation_invalidated` and the antenna quarantined); `DELETE /access-point/{reservation_id}` answers `503 / 1012`, repeat it (REV-2).
- `GET /status`: `runtime_state: stop_failed` and `access_point_stop_incomplete` appear only after the client's own `DELETE /access-point/{reservation_id}` failed (REV-9).
- A watchdog restore whose cleanup fails once now shows `runtime_state: restore_failed` and is retried, instead of `404 reservation_invalidated` (REV-10).
- QoS (experimental): the built-in profiles have new values and three change mode from `once` to `once-hold-last` (`4g_train_tunnel`, `4g_to_3g_fallback`, `progressive_degradation`); a test that relied on their old numbers sees a different network.
- QoS (experimental): `POST .../qos/profile` with different `download_quality` and `upload_quality`, or a quality with `advanced`, is now `422` (NET-11).
- `GET /status` has a new field `restart_required` (`null` or `{service, system, since, message}`); `checks` a new check `os_updates`. Additive: it never makes the status `degraded`.
- `GET /antennas/{interface}` has a new object `health` (repair budgets, quarantines, USB resets).
- `GET /access-point/{reservation_id}`: after a radar event on a DFS channel `channel` is the channel the AP moved to, which can differ from the one requested (REV-12).
- An antenna whose interface has been gone for about 2 minutes, with nothing holding it, leaves `GET /status` and `GET /antennas`; `GET /antennas/{interface}` then answers `404` and a reserve by that `interface` answers as for an unknown antenna (WD-5).
- Channels 120, 124 and 128 (5 GHz) are no longer listed by `GET /antennas/{interface}/capabilities` and are `422` in the create (HAP-9).
- `POST /access-point/{reservation_id}` can answer `503 / 1006` with `Retry-After: 2`, only when the same body finds the network already running (the `200` case) and another operation holds the adapter: repeat it. It was possible before but documented as never happening (REV-11).

---

## [4.0.0] - 2026-11-26

### 📊 Statistics

| Item | Count |
|---|---:|
| 🐛 Bug fixes | 34 |
| ⚠️ Breaking changes | 20 |
| 🔧 Maintenance changes | 11 |
| ✨ New features | 22 |
| 🔄 CI/CD changes | 1 |
| ✅ Test changes | 1 |
| 📦 Commits since 3.0.0 | 129 |

Counts are the entries of the sections below and `git rev-list --count 3.0.0..aca248e` (`aca248e` is the last 4.0.0 commit, before the bump to 4.1.0).

### ⚠️ Breaking Changes

- When all antennas are reserved and no release is scheduled, the reservation `409` returns `null` for `next_available_at` and `next_available_in`.
- AP creation requires a single 2.4 GHz or 5 GHz band; `dual` returns `422`.
- Release all moved from `DELETE /api/v1/device-reservation` to `DELETE /api/v2/reservations/all` and requires the `X-Confirm-Password` header matching the new `protected_commands_password` setting (disabled when unset). A malformed single-release URL can no longer release everything.
- All `/api/v2` error bodies are an object with `detail.code` and `detail.reason`. Clients that displayed the former string `detail` should read `detail.message`.
- API timestamps (`expires_at`, `detail.next_available_at`) use RFC 3339 UTC with a `Z` suffix. Durations and countdowns stay in seconds.
- Internet, TX power and QoS profile requests on a valid reservation without a running network return `409` with `detail.code: 1007` (`network_not_active`). Before, Internet, TX power and the QoS profile stop returned `404`, which looked like an expired reservation, and the QoS profile GET returned `200` with `active: false` (Fable API-2).
- The create body and `GET .../network` are grouped in sections: `radio`, `wifi` (with `security`), `internet`, `captive_portal`, plus `reservation` and `ip` in the answer; flat bodies return `422`. Duplicated and internal fields (`dhcp.*` paths and files, `clients_connected`, the second `interface` and `subnet`) are removed, and `ip.dns_server` is new (Fable API-8; first step of ARCH-3).
- AP creation with `encryption: "wpa"` returns `422` (it silently created WPA2). Use `wpa2` for the same network, or the new `wpa1` for real legacy WPA/TKIP (Fable HAP-10).
- Configuration: the `networks` section is renamed `antennas`, and every entry must set `show_dfs: true|false`; an old `networks` section is ignored (`--validate-config` warns). Wi-Lab now manages every AP-capable Wi-Fi radio it finds, so list a radio the host needs with `disable: true`.
- `GET /api/v1/interface/{id}/network/available-channels` is removed. Use `GET /api/v2/antennas/{interface}`: it needs no reservation and lists only usable channels, grouped by band, with the widths each can use.
- `GET /api/v2/status` no longer returns `checks`; it returns `degraded_reasons`, one entry per cause of `degraded` with `code`, `interface` and `message`. Codes: `antenna_quarantined`, `network_being_repaired`, `hostapd_not_running`, `dnsmasq_not_running`, `nat_rule_missing`, `upstream_unreachable`, `command_stuck`, `loop_stalled`, `cleanup_failed`, `network_stop_incomplete`. The check details moved to the new `GET /api/v2/monitoring`.
- Every `409` has a `detail.code` (Fable API-3): `1008 network_already_active`, `1009 restoration_in_progress` and `1012 stop_incomplete` on the create, `1007 network_not_active` when stopping a stopped network, `1010 qos_profile_already_active` and `1011 qos_profile_not_active` on QoS profiles. `404` on a call with a reservation ID now only means the ID is gone: an unknown QoS `profile_id` and an unsupported TX power answer `422` (were `404`), and stopping a QoS profile that is not running answers `409 / 1011` (was `404`).
- Unknown fields in a request body (reservation, every section of the create, TX power, QoS profile) are refused with `422` and the field path (`captive-portal: Extra inputs are not permitted`, `radio.chanel: ...`) instead of being ignored (Fable API-10).
- The API prefix is `/api/v2` (was `/api/v1`). `/api/v1` is not kept: every path under it answers `404`, with any method.
- Paths renamed (Fable API-6): `/api/v1/device-reservation` → `/api/v2/reservations`, and every `/api/v1/interface/{reservation_id}/...` → `/api/v2/reservations/{reservation_id}/...` (network, Internet, TX power, QoS profile).
- **The create is asynchronous** (Fable API-4, API-5). `POST .../network` checks the request and answers `202` at once with the network in `runtime_state: starting`, same schema as `GET .../network` (was a synchronous `200` with `{"detail": "Network ... created successfully"}` that could take up to 80 s). Poll `GET .../network` until the outcome: the network (`runtime_state: null`); `runtime_state: start_failed` with `error` (`1013` with `stage`, rolled back, reservation kept; was `500`); or `404` with `reason: reservation_invalidated` (every start failed, antenna quarantined; was `500`) or `reservation_expired`. Releasing the reservation or `DELETE .../network` during a start cancels it.
- The release (`DELETE /api/v2/reservations/{id}`, and release-all) stops the network and cleans up before freeing the antenna (3.0.0 freed it first), and still always answers `200`. If the cleanup fails, the ID is gone, the antenna stays held and the server retries the cleanup (5 s, 15 s, 60 s, then every 5 min), shown in `GET /status` as `cleanup_failed`. A held antenna counts as reserved: `409 / 1005` with `next_available_in` until the next cleanup attempt, also when reserved by `interface`.
- `404` on every call with a reservation ID has a stable `detail.reason`: `reservation_released`, `reservation_expired`, `reservation_invalidated` (antenna quarantined) or `reservation_not_found` (never existed, or ended more than an hour ago). Reserve again after `invalidated` or `expired`, and treat a release answered `404` as done.
- `GET /api/v2/status` lists antennas, reserved or not, in `antennas[]` (was `networks[]`). Each entry has `reservation` (`null`, or `{expires_at, expires_in}`) instead of `reserved` and `reservation_remaining_seconds`, and a new `network_active` (Fable API-1).
- `GET /api/v1/debug` is removed: use `GET /api/v2/monitoring` for the health checks. No endpoint lists other clients' reservation IDs any more (Fable SEC-2, API-1).

### ✨ Features

- Optional captive portal on AP creation (`captive_portal.enabled`): clients stay behind a page on the AP gateway until they press Sign in. The page listens on the new optional `captive_portal_port` setting (default 8081; must differ from `api_port`, 53 and 67) and its address is in `captive_portal.url`.
- DFS channels (5 GHz 52–144) are chosen per antenna with `antennas[].show_dfs`: when `false` they are not listed and AP creation on them returns `422`. Antennas not listed in the configuration offer them.
- Export the current API schema and offline Swagger/ReDoc documentation.
- Frontend: explains that TX power control depends on the adapter.
- DHCP subnet selection skips AP subnets that overlap host IPv4 routes.
- Optional offline configuration check (`--validate-config`) with actionable errors and warnings.
- Radio startup failures (hostapd crash, beacon setup failure, radio or readiness timeout, interface lost) are retried by the server during the create: up to 3 starts within 20 s, then again after a 5 s and a 10 s pause. When every start fails, the reservation is invalidated and the antenna quarantined; new reservations return `503 / 1002` or `1003` while recovery or quarantine leaves no antenna.
- New watchdog repairs a running network with the same reservation and expiry (Fable WD-1, WD-2, WD-3, WD-7). A dead AP is restarted up to 3 times per hour per antenna (a failed restore shows `runtime_state: restore_failed` and is retried); a dead dnsmasq up to 3 times per hour, then the whole network. A lost gateway address, `ip_forward`, NAT, Internet-block or isolation rule is repaired within 30 s, and a broken captive portal restores the network.
- Antenna recovery: a quarantined USB antenna is reset through its USB port and returns to the pool only after a test AP and DHCP start. Other quarantined antennas are re-probed periodically and return without a service restart (Fable WD-4).
- Antenna discovery: AP-capable Wi-Fi interfaces (USB or built-in) are found automatically at startup and every 30 s, so Wi-Lab starts without antennas and adds adapters plugged in later without a restart. The `antennas` section only sets display names, `show_dfs` and `disable: true`, and is re-read at each scan; unlisted interfaces use their interface name. With no usable adapter, reservations return `503 / 1003`.
- Frontend: requests answered `503 / 1006` (antenna busy) are repeated automatically after `Retry-After`, and `1006`/`1007` errors show a readable explanation.
- New `encryption: "wpa1"` (legacy WPA, PSK/TKIP, 802.11a/g only) to test old clients, accepted only on antennas whose driver supports TKIP (Fable HAP-10).
- AP creation takes optional `channel_width` (20, 40, 80 MHz) and `wifi_generation` (4 = 802.11n, 5 = 802.11ac, 6 = 802.11ax); the defaults 20 MHz / 802.11n keep the previous behaviour. `GET /antennas/{interface}` lists what each antenna accepts, and `GET .../network` reports the width the radio actually uses (Fable HAP-11).
- Frontend: the start dialog offers only the encryptions, Wi-Fi generations, channel widths and channels the antenna supports (DFS channels marked, `wpa1` instead of `wpa` where available), and a running network shows its width and Wi-Fi generation.
- New `GET /api/v2/monitoring` (System, token only): `status`, `degraded_reasons`, `checked_at`, `check_interval_seconds` and the detail of every health check (`commands`, `loops`, `hostapd`, `dnsmasq`, `iptables_nat`, `upstream_interface`), for operators.
- Optional `hostapd_debug_dir` setting: each failed hostapd start writes a report there (configuration without passwords and the last 400 lines of `hostapd -d`); the newest 100 reports are kept.
- New **Antennas** API (token only): `GET /api/v2/antennas` lists the managed antennas (`display_name`, `interface`). `GET /api/v2/antennas/{interface}` gives `device` (`bus`, `address`, `driver`), `encryptions` and, per band, the Wi-Fi generations with their widths and the usable channels with their widths, to fill a form's dropdowns.
- Frontend: a captive portal switch on each reserved antenna card presets the start dialog, and a running network shows the captive portal as On or Off with its URL and a header badge.
- `POST /api/v2/reservations` takes an optional `interface` (from `GET /api/v2/antennas`) to reserve that antenna; without it the first free one is reserved, as before. A reserved antenna answers `409 / 1005` with the expiry of its reservation, a quarantined one `503 / 1002` or `1003`, an unknown one `422`.
- Repeating the same create body is safe: `202` while that start runs (no second AP), `200` with the network once it runs; a different body answers `409 / 1008`. After a lost answer, send the same create again or just poll.
- Frontend: a banner lists why the service is `degraded` (`degraded_reasons` of `GET /status`, with antenna names).
- `GET .../network` has a `restarts` section (`ap`, `dhcp`, `last_at`, `last_reason`) counting watchdog repairs over the whole reservation: read it before and after a test to know whether the AP was interrupted.

### 🐛 Bug Fixes

- Wi-Lab radios are kept away from NetworkManager and systemd-networkd (runtime rule under `/run`) from discovery on, also after a USB re-enumeration; 3.0.0 released a radio from NetworkManager only at each AP start.
- Disabling Internet also cuts connections already open: forwarded TCP traffic of that AP's clients is reset.
- After an unclean shutdown, startup removes Wi-Lab's stale firewall rules (without flushing host chains), orphan hostapd/dnsmasq processes, stale runtime files and Wi-Lab's QoS devices, and resets each radio when discovery adds it (Fable STAB-4).
- Each Wi-Lab masquerade rule is restricted to its AP subnet.
- The API listens on the configured port instead of always 8080.
- Startup refuses a `country_code` that is a regulatory region (`EU`, `ETSI`, `FCC`) or not two uppercase letters.
- Active QoS profiles stop when their network is released or expires.
- After a network stops, its radio is left down in managed mode instead of being brought up again.
- The gateway and DHCP start only once the access point is enabled, and incomplete network starts are rolled back.
- Timed-out access point starts are cleaned up.
- Other API requests, other adapters and the system status stay responsive during a slow AP start or cleanup. A request on an antenna that another operation holds for more than 5 s answers `503 / 1006 device_busy` with `Retry-After: 2` (Fable RACE-1).
- 5 GHz channels read before the regulatory domain was applied are no longer refused until a restart: a refused channel is checked again against a fresh `iw` reading (Fable BUG-4).
- `/status` health checks look at Wi-Lab's own processes and rules per network: a network without Internet is no longer `degraded` on a host without NAT rules, Docker's MASQUERADE no longer hides a missing Wi-Lab rule, a DOWN link is no longer reported up, and hostapd is checked too (`checks.hostapd` and `missing` lists in `GET /monitoring`) (Fable BUG-2).
- An AP start runs fewer host commands (Fable PERF-1).
- Swagger examples match the real responses: no `device_id` field, no unused QoS models (Fable API-9).
- With `upstream_interface: auto`, Wi-Lab follows the default route when it moves to another interface: new networks use it and the NAT of running networks moves within 30 s, without a restart (Fable STAB-6).
- Clients of a Wi-Lab network can no longer reach the Wi-Lab host (API, SSH, other services, also over IPv6): only DHCP, ping and, with the captive portal, DNS and the portal page are allowed (Fable SEC-3).
- A dnsmasq launch that timed out before writing its PID file is stopped instead of left running (Fable NET-6).
- If a Wi-Lab background loop stalls, `/status` reports it and the service restarts itself through the systemd watchdog, only when no reservation is active. This needs the new service unit (`Type=notify`, `WatchdogSec=90s`): install the service again (Fable STAB-1).
- A host command stuck in the kernel (hung Wi-Fi driver) no longer freezes the API: Wi-Lab stops waiting 2 s after SIGKILL, fails the operation and reports it (`command_stuck` in `degraded_reasons` of `/status`, `checks.commands.stuck` in `/monitoring`) (Fable STAB-1).
- A network whose NAT or isolation rules cannot be installed fails (`start_failed` with its `stage`) and is rolled back instead of reporting success (Fable NET-2); the false "Isolation disabled for testing" log line is gone (Fable NET-4).
- `iptables` calls wait up to 5 s for the xtables lock instead of failing when another program holds it (Fable NET-1).
- Stopping a network on a disconnected adapter completes its cleanup (Fable WD-5).
- The create request is validated before touching the antenna: SSID, password and channel rules, and no line injection into `hostapd.conf` (Fable BUG-1).
- `wpa3` and `wpa2-wpa3` networks write `wpa_key_mgmt` and `ieee80211w` only once in `hostapd.conf`; the mixed mode requires PMF for WPA3 clients only, and SAE accepts H2E (Fable HAP-10).
- The service refuses to start with an empty `auth_token`, `api_port` outside 1–65535, `max_timeout` below `min_timeout` or a `dns_server` that is not an IPv4 address; before, `dns_server: foo` started and every network creation failed with `500` (Fable BUG-3).
- Networks are isolated from each other with any `dhcp_base_network`: with subnets outside `192.168.*` (e.g. `10.20.0.0/24`) clients of different networks could talk to each other (Fable NET-3).
- A `DELETE .../network` that cannot stop hostapd (stuck in the kernel) no longer answers `200` with the process left behind. After retrying for up to 15 s it answers `503 / 1012 stop_incomplete` with `Retry-After: 5`; the network reports `runtime_state: stop_failed` (also in `/status`) and a create on that reservation answers `409 / 1012`. Repeat the DELETE to finish the stop.
- `/status` no longer runs host commands on every call: it reads checks refreshed every 10 s in the background, so a change takes up to 10 s to show.
- An unexpected server error answers `500 / 500` without closing the connection, so the client's next request on the same keep-alive connection no longer fails with a transport error.
- Normal outcomes are no longer logged as errors: a missing `iptables -C` rule, a `tc` qdisc with nothing to delete, `iw set txpower` unsupported by the driver and a stop without DHCP (Fable NET-5).
- The log line `Starting network ... with SSID` is written only for a create that really starts.
- 6 GHz channels are no longer listed as 5 GHz channels (in 3.x `available-channels`, now `GET /antennas/{interface}`): Wi-Fi 6E antennas added 59 unusable channels, some with the same number as a 5 GHz channel.
- Every `422` message starts with the path of the refused field written with dots (`radio.channel: ...`, `wifi.security.password: ...`), without pydantic's `Value error, ` prefix, also for rules between fields and antenna checks.

### 🔧 Maintenance

- The configuration is read once at startup.
- Fix the PyYAML type-stub requirement for fresh development installs.
- Report an empty internal command consistently across platforms.
- The generated hostapd configuration enables `ieee80211d=1` (advertise the country code) on all bands, and `ieee80211h=1` (DFS/TPC) on 5 GHz where regulatory rules require it.
- Documented safe recovery of a blocked USB Wi-Fi adapter.
- New [AP creation procedure](docs/ap-creation-procedure.md) for client developers, with a [sequence diagram](docs/ap-creation-procedure.md#3-sequence-diagram) from reservation to release and the client action for every answer of every call. New backend [architecture](docs/architecture.md) guide with startup, threading, creation, retry, watchdog and recovery diagrams and the [server view](docs/architecture.md#61-end-to-end-sequence-server-view) of the same flow.
- Swagger and ReDoc explain the reservation and recovery lifecycle, with retry, quarantine and watchdog response examples.
- Journal entries for server errors include the API operation, HTTP status and error code, without request or response data.
- New [docs/error-codes.md](docs/error-codes.md): every `detail.code`, its HTTP status, `Retry-After`, where it is answered and the client action, plus the `degraded_reasons` codes.
- Documented the `GET /api/v2/status` health values (`standby`, `ok`, `degraded`), what makes the service `degraded` and how clients learn about quarantined adapters, in Swagger, the API overview, the AP creation procedure (2.8) and the Swagger guide.
- `wilab/wifi` is a regular Python package, like `wilab/network` and `wilab/api` (Fable ARCH-12).

### 🔄 CI/CD

- CI runs the backend tests, type checks and the frontend build, and publishes the API documentation.

### ✅ Tests

- Tests are split into `tests/unit-tests/` (mocked hardware, run by `make test-local` and CI) and the new `tests/e2e-tests/`, which run on the Wi-Lab machine against the running service. They combine API calls with journal checks, the SSID on the air (`iw`) and USB unplugs simulated through sysfs, and cover the API contract, create validation, firewall rules, watchdog repairs, device loss and return, unclean restarts and create/delete stability. They are skipped unless `WILAB_E2E=1`; run them with `make test-e2e` or `make test-e2e-usb` (see `docs/e2e-testing.md`).

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

- **QoS Profiles**: simulate network conditions per reservation with a profile, an ordered sequence of timed steps. Each step sets bandwidth limits, a 0–100 quality score (mapped to packet loss, delay, jitter and corruption via netem) or advanced netem overrides. Playback modes: `loop`, `bounce`, `once`, `once-hold-last`.
- **Built-in profile catalogue**: 10 ready-to-use profiles (4G urban/highway/rural/tunnel/stadium, 4G-to-3G fallback, WiFi interference, satellite link, progressive degradation). Add custom profiles as `*.json` files in `wilab/data/qos-profiles/`; they are validated against a JSON Schema at startup.
- **Inline static QoS**: sending speed/quality parameters directly creates a single-step `once-hold-last` profile, applied until stopped.
- **Profile source**: each profile has a `source_file` field (the JSON file it was loaded from, or `"generated"` for inline QoS), in the catalogue and in the active profile state.
- **Step count**: the `steps` field of the profile state gives the number of steps of the active profile.
- **New API endpoints:**
  - `GET /api/v1/qos/profiles`: the full catalogue (no auth)
  - `POST /api/v1/interface/{rid}/qos/profile`: start a profile or inline QoS
  - `GET /api/v1/interface/{rid}/qos/profile`: active profile state
  - `DELETE /api/v1/interface/{rid}/qos/profile`: stop and clear (`200` with confirmation, `404` if no active profile)

### 🔧 Maintenance

- New dependency `jsonschema>=4.19.0` (`requirements.txt`), and `types-jsonschema` for development.

### ✅ Tests

- New QoS test suite (113 tests): models, catalogue loading, profile playback in all 4 modes, inline profiles, API endpoints and the `tc` driver.

---

## [2.5.1] - 2026-04-18

### 🐛 Bug Fixes

- The frontend accepts `expires_at: null` and `expires_in: null` from `GET /api/v1/interface/{reservation_id}/network` for unlimited reservations.

### 🔧 Maintenance

- `update_version.sh` accepts `--bump-to X.Y.Z` for non-interactive version bumps; without it, it still prompts.

---

## [2.5.0] - 2026-04-16

### ✨ Features

- **API docs links in the toolbar**: two frontend toolbar buttons open Swagger UI and ReDoc in a new tab.
- **Reservation policy API**: `GET /api/v1/status` returns a `reservation_policy` object with `min_seconds`, `max_seconds` and `allow_unlimited`, replacing the flat `allow_unlimited_reservation` field.
- **Dynamic reservation dialog**: the frontend validates the duration against the server's min/max, shows it as a live `00h 00m 00s` badge and shows the valid range below the input.

### 🐛 Bug Fixes

- Unlimited reservations no longer cause a `TypeError` in the network status and Internet enable/disable.
- `start-service.sh` prints colored URL lines instead of raw escape codes.

### 🔧 Maintenance

- **Removed the `default_timeout` config parameter**: the reservation duration is always set with `duration_seconds` in the API.
- **Updated documentation**: README rewritten with the current config format, an API usage example and the Makefile workflow; outdated `net_id` references and obsolete curl examples removed.

---

## [2.4.0] - 2026-04-16

### ✨ Features

- **Token login dialog**: on first load, the frontend asks for the Bearer token and keeps it in `localStorage` for all API requests. A lock button in the toolbar changes the token at any time.

### 🐛 Bug Fixes

- **Security:** the hardcoded `authToken` is removed from the frontend environment files; the token is entered at runtime, so no secret is in the source code.
- **Security:** the hardcoded IP is removed from the development environment; both environments use the relative path `/api/v1`.
- **Security:** a `401` answer clears the invalid token and asks for a new one at once.

### 🔧 Maintenance

- The frontend keeps the auth token in one service, using `localStorage`.
- New frontend dialog to enter or update the auth token.

---

## [2.3.0] - 2026-04-01

### 🐛 Bug Fixes

- **Auto-stop network on reservation release**: releasing a reservation (single or bulk) stops the network on its device. Before, the network kept running until its expiry, leaving AP/DHCP/NAT resources behind.

---

## [2.2.0] - 2026-03-31

### ✨ Features

- **Unlimited reservations**: with `allow_unlimited_reservation: true` in the config, `duration_seconds: 0` creates a reservation with no expiry, active until released.
- **Duration validation**: `POST /device-reservation` validates `duration_seconds` against `min_timeout` and `max_timeout` from the config (before, only the frontend checked it).
- **`min_timeout` floor**: `min_timeout` cannot be set below 10 seconds.

### 🔧 Maintenance

- **Frontend unlimited UX**: the reservation dialog shows an "Unlimited" checkbox when allowed; owned cards show "∞ Unlimited" instead of a countdown, occupied cards "Occupied — No expiry".

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

### ✨ Features

- **Available WiFi Channels API**: new endpoint listing the WiFi channels supported by a reserved device, split by band.
- **Channel cache warm-up**: channel information is read at startup, so the first API call is answered from the cache.
- **Channel validation**: 5 GHz channels 169/173/177 are recognized, and network creation refuses unsupported or disabled channels with a clear `422`.
- **Configurable country code**: the WiFi regulatory domain is set with `country_code` in `config.yaml` (default `IT`).
- **Regulatory domain at startup**: `iw reg set` applies the configured country code before the channel warm-up, so channel flags are correct; channels marked `No IR` are treated as disabled.

### 🔧 Maintenance

- **Reorganized `scripts/`**: 10 obsolete API helper scripts removed; `restart-service.sh` split into `scripts/stop-service.sh` and `scripts/start-service.sh`.
- **Makefile service targets**: new `make stop`, `make start`, `make restart`; duplicate `build-release`/`run-release` targets removed.
- **Tests independent of the host config**: tests use their own `tests/test.config.yaml`, so they pass whatever the host `config.yaml`.

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

- **`net_id` removed from the configuration.** Each device is identified by its interface name; the new required field `display_name` replaces the `net_id` label.
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
- **Network, Internet and TX power routes take `{reservation_id}`** instead of `{net_id}`; every operation needs a valid reservation token.
- **The `timeout` parameter of network creation is removed.** The reservation `duration_seconds` is the only lifetime: WiFi stops when the reservation expires.

### ✨ Features

- **Device reservations**: get a time-limited token before any network operation. The API assigns the first free device and returns an 8-character hex token; at expiry the network stops, the device is released and the token is invalidated. When all devices are taken, the API returns the estimated wait until one is free.
- **Frontend reservation UX**: every physical interface is a card (refreshed every 10 seconds) that is owned (with WiFi controls), occupied by another user (with a countdown) or available. Users can hold several reservations, each with a countdown; "Release All" frees all owned devices after a confirmation. Reservations survive a page reload, and when capacity is full a countdown shows when the next device is free.
- **Installer state**: installer stages share a persistent state across precondition checks, install stages and post-install tests.

### 🔧 Maintenance

- Configuration example updated: `interface` + `display_name`, no `net_id`.
- Networking docs: "Secure Timeout Configuration" replaced with "Reservation-Driven Timeout".
- Developer guide updated with the new config format and Makefile workflow.

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

---

## [1.5.0] - 2026-03-24

### 🔧 Maintenance

- Troubleshooting is consolidated in `docs/troubleshooting.md`, with a note that the diagnostics scripts need the right interface names.
- `docs/installation-guide.md` is removed; its content is in README.md and `docs/troubleshooting.md`.
- The API reference is Swagger UI at `http://localhost:8080/docs`; hardcoded examples are removed from `docs/swagger.md`.
- `docs/readme-dev.md` uses Makefile targets (`make venv`, `make test-local*`, `make type-check`) instead of manual commands.
- New `make lint` and `make lint-fix` targets (Ruff `>=0.3.0`), part of the pre-commit checklist.
- New `make type-check` target (MyPy `>=1.8.0`); warnings are expected while type hints are added.
- Ruff fixes applied across the codebase (unused imports and variables, f-strings without placeholders).

---

## [1.4.0] - 2026-03-23

### ⚠️ Breaking Changes

- Network and Internet calls answer a short message instead of the network details: `POST` and `DELETE /api/v1/interface/{net_id}/network` return `{"detail": "Network {net_id} created successfully"}` / `{"detail": "Network {net_id} stopped successfully"}`, and `POST .../internet/enable` / `disable` return `{"detail": "Network {net_id} internet enabled successfully"}` / `{"detail": "Network {net_id} internet disabled successfully"}`. Read the network details with `GET /api/v1/interface/{net_id}/network`.
- Validation errors are a plain string: `{"detail": "..."}` instead of the Pydantic list.
- `DELETE /api/v1/interface/{net_id}/network` returns `404` for an unknown `net_id` and `409` when the network is already inactive.

### 🐛 Bug Fixes

- **Security:** `GET /api/v1/debug` requires a valid Bearer token like the other protected endpoints; before, it exposed system debug information (services, interfaces, diagnostics) without authentication.

---

## [1.3.0] - 2026-03-18

### ⚠️ Breaking Changes

- TX power responses use a nested `tx_power` object (`requested_level`, `reported_level`, `reported_dbm`); the flat fields `current_level`, `current_dbm` and top-level `reported_dbm` and the warning field are removed.

### ✨ Features

- **Connected clients table**: each active AP card lists its clients with `IP Address` and `MAC Address`, or a message when none is connected.
- **Network card details**: new `TX Power` row (same labels as the creation dialog) and `Expires in` row (`h m s`); the card border is green when Internet is enabled and yellow when disabled.
- **AP diagnostic utility**: restored as `diagnostics/diagnose-ap.py` (was `scripts/10-diagnose-ap.py`), with usage examples for running it from the repository root.
- **Requested vs reported TX power**: `GET /api/v1/interface/{net_id}/network` and `GET /api/v1/interface/{net_id}/txpower` return `tx_power` with `requested_level`, `reported_level` and `reported_dbm`.
- Network cards: a single right-aligned `Connected Clients:` count, tighter spacing, and the WiFi icon, network name and interface left-aligned in the header.
- Network cards: the Internet status is an icon badge in the top-right corner (green `cloud_done` "Internet available", yellow `cloud_off` "Internet disabled").
- Inactive cards show `Access point <net_id> disabled.` with the name in bold, and cards show `TX Power requested/reported`.

### 🐛 Bug Fixes

- `POST /api/v1/interface/{net_id}/txpower` returns `422 Unprocessable Entity` when the interface reports a different power than requested, instead of a success with a warning.
- `POST /api/v1/interface/{net_id}/txpower` returns `422` for out-of-range levels with `{"detail": "Requested power out of range. Valid values are 1, 2, 3, 4."}`.

### 🔧 Maintenance

- Swagger examples for `GET .../network`, `GET .../txpower` and `POST .../txpower` (success, out-of-range `422`, hardware mismatch `422`) match the nested `tx_power` shape.
- Client and traffic planning docs merged into `TODOs/clients-info-and-statistics.md`; `TODOs/traffic-statistics.md` removed.

---

## [1.2.1] - 2026-03-18

### ✨ Features

- **Dynamic WiFi network names**: each AP gets its own SSID (`test-network-ap-01`, `test-network-ap-02`, ...), generated by the frontend from the AP ID.

### 🐛 Bug Fixes

- **Hostapd startup timeout**: the command timeout is configurable with an 8 s default (was a fixed 1 s) and at least 5 s, fixing intermittent "Failed to start hostapd" errors.

### 🔧 Maintenance

- **Setup → Install renaming**: `install/02-setup-stages/` is now `install/02-install-stages/`, with matching variable names (`INSTALL_DIR`, `install_common_vars()`); no compatibility alias.
- **API documentation**: `401 Unauthorized` responses are documented in Swagger for every protected endpoint.
- **Development tooling**: new `restart-service.sh` script to stop and start the service quickly.
- Frontend build: bundle size and warnings reviewed; the Docker multi-stage frontend build is unchanged.

---

## [1.2.0] - 2026-01-29

### ⚠️ Breaking Changes

- **Unified network endpoint**: `/interface/{net_id}/status`, `/interface/{net_id}/summary` and `/interface/{net_id}/clients` are removed. `GET /interface/{net_id}/network` returns the whole network state, with new `dhcp`, `clients` and `clients_connected` fields.

### ✨ Features

- **Version display**: the frontend page title shows the software version (1.2.0).
- **Swagger examples**: `net_id` parameters are prefilled with `ap-01`.
- **System health**: `/api/v1/status` (renamed from `/health`) checks dnsmasq, iptables NAT and the upstream interface, and reports `ok`, `standby` (no network active) or `degraded`.
- **Debug endpoint**: new `/api/v1/debug` with system information (OS, kernel, Python, uptime), active networks, DHCP leases, iptables rules and hostapd/dnsmasq status (about 600 ms).
- The frontend reads the network state with one API call instead of two or three.

### 🐛 Bug Fixes

- **Security:** `/api/v1/status` requires the authentication token, like the other system status endpoints.

### 🔧 Maintenance

- `/status` fields are ordered `version`, `status`, `networks`, `active_networks`, `checks`.
- Internal cleanup: routes renamed and merged, redundant code removed (251 lines) from backend and frontend.
- Swagger and `TODOs/api-simplification.md` updated for the unified endpoint.

---

## [1.1.0] - 2026-01-29

### ✨ Features

- **CORS**: the frontend and backend can be served from different origins; allowed origins are configurable.

### 🐛 Bug Fixes

- The installer homepage test uses a GET request for reliable HTTP detection.
- iptables rules are no longer created twice.
- Gateway assignment is fixed.
- The number of connected clients is reported correctly.

### 🔧 Maintenance

- **Modular installer**: `install.sh` is a slim orchestrator that runs 15 stages (5 preconditions, 5 setup, 5 tests) discovered at runtime from `install/` in numeric order, with shared functions in `install/common.sh`; add a stage without editing `install.sh`. `install/99-final-test.sh` verifies the installation.
- **API routes**: split by domain (clients, health, internet, network, txpower).
- All `install.sh` and `uninstall.sh` scripts are executable.
- The uninstall script takes the Docker `IMAGE_NAME` from `deploy_frontend.sh`.
- Swagger/OpenAPI responses document their HTTP status codes.
- `config.yaml` comes with an example file.
- Development guidelines updated.
- The service is renamed from `wilab.service` to `wi-lab.service`.

### ✅ Tests

- Tests no longer need Wi-Fi hardware, so they run in CI.

---

## [1.0.0] - Initial Release

### ✨ Features

- **WiFi networks**: create and manage networks with custom SSID and WPA2 security, with a full lifecycle (create, activate, deactivate, delete).
- **Clients**: real-time monitoring and tracking of connected devices, with connection history and statistics.
- **DHCP server**: configurable subnets, automatic IP assignment and lease management.
- **NAT and Internet access**: Internet for clients through an automatically detected upstream connection.
- **Traffic control**: Linux `tc` integration and TX power management.
- **REST API**: network operations, a health check endpoint and Swagger/OpenAPI documentation.
- **Frontend**: Angular web application for network status and client management, with a production Docker build.
- **Systemd service**: starts automatically on boot.
- **Docker**: containerized deployment with Docker Compose; the frontend build runs in Docker.
- **Security**: HTTPS for the API, configuration validation at startup, network isolation checks and safe cleanup of system resources.
- **Installation**: automated multi-stage setup with verification, service registration and health checks.

### 🔧 Maintenance

- Requirements: Linux with WiFi support (hostapd, dnsmasq), Python 3.8+, Docker and Docker Compose.
- Documentation: setup and installation, API with examples, network configuration, troubleshooting and development guidelines.

---
