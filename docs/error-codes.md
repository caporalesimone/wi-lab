# Error codes

Every error answered under `/api/v2` has the same body (the create is
asynchronous: it answers `202`, and a failed start is read with
`GET /access-point/{reservation_id}`, see `1013` and the `404` reasons):

```json
{"detail": {"code": 1006, "reason": "device_busy", "message": "text for display"}}
```

- **`code`** (integer) and **`reason`** (string) are stable: use them, with the
  HTTP status, for control flow.
- **`message`** is for display and can change between versions.
- Some codes add fields (listed below) and some answers carry a `Retry-After`
  header (seconds).

The **action** column uses the six actions of the
[AP creation procedure, 3.1](ap-creation-procedure.md#31-what-to-do-with-each-answer):
**DONE**, **WAIT**, **REPEAT** (same request after `Retry-After`; the only
case for automatic retries), **FIX**, **RESERVE AGAIN** (the ID is gone: do not
release it), **STOP** (show the message, ask an operator).

## Domain codes (1001 and up)

| Code | Reason | HTTP | `Retry-After` | Where | Meaning | Action |
|---|---|---|---|---|---|---|
| 1001 | `retry_later` | 409 | — | — | **No longer answered** (4.0.0): radio failures are retried by the server inside the create. Kept reserved. | — |
| 1002 | `device_recovering` | 503 | 10 | reserve | No antenna is allocatable while one is being recovered (USB reset); with `interface`, that antenna is being recovered. | REPEAT |
| 1003 | `device_unavailable` | 503 | no | reserve | No antenna discovered or usable and nothing recovering; with `interface`, that antenna is quarantined. (A create whose every start failed is no longer answered with it: the asynchronous create ends with `404` and `reason: reservation_invalidated`.) | STOP (after a service start, wait for discovery first); with `interface`, reserve without it |
| 1004 | `cleanup_failed` | 503 | — | — | **No longer answered** (4.0.0): the release always answers `200` and the server repeats a failed cleanup in the background; the antenna is held meanwhile (reserve: `409 / 1005`; `GET /status`: `cleanup_failed`). A failed cleanup before a create quarantines the antenna (polling: `404`, `reservation_invalidated`). Kept reserved. | — |
| 1005 | `no_device_available` | 409 | no | reserve | Every antenna is reserved, or the requested `interface` is. Adds `next_available_at` (UTC) and `next_available_in` (seconds), both `null` when no release is scheduled. | REPEAT after `next_available_in`, or a backoff |
| 1006 | `device_busy` | 503 | 2 | `GET` and `DELETE /access-point/{reservation_id}`, Internet, TX power, QoS profile; the create only for the same body on a running network (its `200` case); never the release or `GET /reservations/{id}` | Another operation (for example an AP start or a stop) held the antenna for more than 5 s. Nothing was changed. While a create is starting, `GET /access-point/{reservation_id}` answers at once and never `1006`. | REPEAT |
| 1007 | `access_point_not_active` | 409 | no | Internet, TX power, QoS profile, `DELETE /access-point/{reservation_id}` | The reservation is valid but no network is running. | FIX (create the network first); DONE for a stop |
| 1008 | `access_point_already_active` | 409 | no | create | A network with **different** settings runs or is starting on this reservation. The same body answers `202` (starting) or `200` (running) instead. | FIX: read it with `GET /access-point/{reservation_id}`; `DELETE /access-point/{reservation_id}` first to replace it |
| 1009 | `restoration_in_progress` | 409 | no | create | The watchdog is repairing this network (`restoring_ap`, `restoring_dhcp`, `dhcp_failed`). | WAIT until `runtime_state` is `null`, then create only if `active` is `false` |
| 1010 | `qos_profile_already_active` | 409 | no | start a QoS profile | A profile already runs on this network. | FIX: stop it first |
| 1011 | `qos_profile_not_active` | 409 | no | stop a QoS profile | No profile runs on this network. | DONE |
| 1012 | `stop_incomplete` | `DELETE /access-point/{reservation_id}`: 503; create, Internet, TX power, QoS profile: 409 | DELETE: 5; others: no | `DELETE /access-point/{reservation_id}`; create; Internet; TX power; QoS profile | The stop did not complete even after the server repeated it every 2 s for 15 s, usually hostapd stuck in the kernel after a driver firmware timeout. The network is half stopped (`runtime_state: stop_failed`) and the watchdog leaves it alone. A create, Internet, TX power or QoS profile request on that reservation answers `409 / 1012` until the stop completes. Only the owner's stop marks it: a failed expiry, rollback or background cleanup is `cleanup_failed` in `/status`. | REPEAT the DELETE until `200`; after a create's `409 / 1012`, repeat the DELETE, then the create |
| 1013 | `startup_failed` | — | no | `GET /access-point/{reservation_id}`, in `error` with `runtime_state: start_failed` | The asynchronous create failed for a non-radio reason and was rolled back; the reservation is kept. `error.stage`: `hostapd`, `interface`, `gateway`, `dhcp`, `captive_portal`, `nat`, `internet_block`, `isolation` or `host_guard`; `null` when the start ended with an unexpected error. Not an HTTP error: the `GET` answers `200`. | STOP (a new create starts again; release the ID if you give up) |

## Generic codes (the HTTP status)

Errors without a domain meaning use the HTTP status as `code`.

| Code | Reason | When | Action |
|---|---|---|---|
| 401 | `unauthorized` | Missing or wrong `Authorization: Bearer` token. | FIX |
| 403 | `forbidden` | A Maintenance call without the right `X-Confirm-Password`, or with protected commands disabled. | FIX |
| 404 | `reservation_released`, `reservation_expired`, `reservation_invalidated`, `reservation_not_found` | **Every call with a reservation ID** (reservation get and release, network create, get and stop, Internet, TX power, QoS): the ID is no longer valid, and `reason` says why: released (by its owner or release-all), expired (also when it would expire before the next AP start), invalidated (its antenna was quarantined), not found (never existed, or ended more than an hour ago). These four values are **stable**, like the codes. | `reservation_invalidated`, `reservation_expired`: RESERVE AGAIN. `reservation_released`, `reservation_not_found`: nothing to do (on a release: DONE) |
| 404 | `not_found` | `GET /antennas/{interface}` and `.../capabilities`: no managed antenna has that interface; any unknown path. | FIX |
| 422 | `validation_error` | The request is invalid. The message starts with the path of the refused field, with dots: `radio.channel_width: ...`, `wifi.security.password: ...`, `profile_id: ...`, `interface: ...` (reserve: not a managed antenna). Also an antenna that cannot do what is asked (channel, width, generation, encryption, TX power not supported by the driver). | FIX |
| 500 | `internal_server_error` | An unexpected server error. | STOP |
| 503 | `service_unavailable` | `GET /antennas/{interface}/capabilities`: the radio cannot be read now (unplugged or being reset). | REPEAT after a few seconds |

`404` never means anything else on a call with a reservation ID, and it always
carries one of the four reasons above: a missing QoS
profile in the catalogue is `422`, a missing running profile is `409 / 1011`,
and an unsupported TX power is `422`.

## `service.degraded_reasons` codes (`GET /status`)

Not errors: `GET /status` lists why the service is `degraded`, one
`{code, interface, message}` per cause (`interface` is `null` for the whole
service). The detail of each check is `checks` of the same answer.

| Code | `interface` | Meaning |
|---|---|---|
| `antenna_quarantined` | the antenna | `recovery_state` `recovering` (USB reset running) or `unavailable` (re-probed periodically). Not allocatable. |
| `access_point_being_repaired` | the antenna | The reserved network has `runtime_state` `restoring_ap`, `restoring_dhcp`, `dhcp_failed` or `restore_failed`. |
| `access_point_stop_incomplete` | the antenna | A `DELETE /access-point/{reservation_id}` answered `503 / 1012`: the network is half stopped (`runtime_state: stop_failed`) until its owner repeats the DELETE. Its stopped processes are not reported as `hostapd_not_running` or `dnsmasq_not_running`. |
| `hostapd_not_running` | the antenna | The AP process of that network is dead. |
| `dnsmasq_not_running` | the antenna | The DHCP process of that network is dead. |
| `nat_rule_missing` | the antenna | The network has Internet enabled but its NAT rule is missing. |
| `command_stuck` | `null` | A host command did not exit even after SIGKILL (hung driver). |
| `loop_stalled` | `null` | A background loop has not run for 3 minutes. |
| `cleanup_failed` | the antenna | The cleanup after a release or expiry failed (for example hostapd stuck in the kernel). The antenna is held, not allocatable; the server repeats the cleanup after 5 s, 15 s, 60 s, then every 5 min. |
