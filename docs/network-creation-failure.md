# Network creation failure and recovery

This contract applies to `POST /api/v1/interface/{reservation_id}/network`.
Use an authenticated request and keep the original reservation ID while Wi-Lab
allows retries. Network creation failure is not the same as failing to acquire
a reservation.

All API errors use an object in `detail`. For example, a generic startup
failure returns `{"detail":{"code":500,"reason":"internal_server_error","message":"Failed to start AP"}}`.
Recovery codes keep their existing payloads. Treat `detail.message` as
display text, not as a retry signal.

## Client contract

| Response | `detail.code` / `detail.reason` | Client action |
|---|---|---|
| `200` | None | The network is running. Stop retrying. |
| `409` with `Retry-After` | `1001` / `retry_later` | Keep the current reservation. Wait the specified seconds, then repeat the same create using the same ID. |
| `409` without code `1001` | Legacy conflict, e.g. an active AP | Do not blindly retry. |
| `500` without `Retry-After` | `1003` / `device_unavailable` | Stop creation attempts and discard the invalidated ID. Do not send a release for it. |
| `404` | Unknown, expired, or invalidated ID | Stop using the ID. |
| `401`, `422`, or `500` without code `1003` | Authentication, validation, or non-classified startup error | Do not automatically retry creation. A generic `500` does not invalidate the reservation; release it if no longer needed. |

Example after the first classified failure:

```http
HTTP/1.1 409 Conflict
Retry-After: 5
Content-Type: application/json

{"detail":{"code":1001,"reason":"retry_later","reservation_invalidated":false}}
```

Wi-Lab allows three attempts in a sequence of classified failures. It starts
cooldowns of **5 seconds** and **10 seconds** after the first and second
failures, respectively. A request received during cooldown returns the
remaining whole seconds (rounded up), without launching the AP or consuming
an attempt. Reservation expiry does not move. Use one in-flight request per
reservation. A lost HTTP response is ambiguous: query the existing network
using the same ID before deciding what to do; do not treat a transport timeout
as `1001`.

The existing internal retry for a 2.4 GHz startup segfault is limited to the
first request in a failure sequence. Classified failures include a segfault
or a timeout preparing the radio or waiting for the AP to become ready. An
isolated `hostapd` exit code `1`, gateway failure, or DHCP failure does not
consume the radio retry allowance if cleanup succeeds.

After the third classified failure, or immediately if startup cleanup is
unsafe, Wi-Lab invalidates the reservation and quarantines the antenna before
responding. The response is final for that ID, even if recovery later succeeds:

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{"detail":{"code":1003,"reason":"device_unavailable","reservation_invalidated":true}}
```

## New reservations during recovery

`POST /api/v1/device-reservation` can still return `200` for another free
adapter. If no adapter can be assigned and recovery is in progress, it returns
`503 / 1002` with `Retry-After: 10`. This is a polling interval, not a promise
that a reset will run or complete by then. Retry **the reservation POST**, not
creation with the invalidated ID. If all adapters are quarantined and none is
recovering, the response is `503 / 1003` without an automatic retry suggestion.
Ordinary contention returns `409 / 1005`. A cleanup failure that prevents
an API operation is `503 / 1004`, with no automatic retry recommendation.

`GET /api/v1/status` continues to return `200`. The affected entry contains
`recovery_state: recovering` or `recovery_state: unavailable`, and overall
status is `degraded`. A quarantined adapter can have `reserved: false` but
is **not** allocatable.

## Failures after an AP has started

The watchdog checks each active network every five seconds. A stopped `hostapd`
process triggers recovery at the next check; an unresponsive or non-enabled AP
must fail three consecutive checks. Having no stations connected is not a failure.
Wi-Lab tries one AP restart per running network, keeping the original reservation,
expiry and AP settings. Clients may need to reconnect. Traffic shaping and active
QoS profiles are cleared by AP teardown and need to be reapplied after a restart.
A repeated AP failure or a classified radio failure during restart can invalidate
the reservation and quarantine the device. An unclassified failure with successful
cleanup leaves the reservation valid and the network stopped.

An isolated DHCP failure gets one DHCP-only restart, without restarting the AP
or scheduling a USB reset. If DHCP cannot restart, the AP stays available but a
new client may be unable to get a lease. An unsafe DHCP cleanup quarantines the
adapter without scheduling a USB reset.

`GET /api/v1/status` and `GET /api/v1/interface/{reservation_id}/network`
can report `runtime_state`: `restoring_ap`, `restoring_dhcp`, or `dhcp_failed`.
The UI shows these states; do not send a new create during either restoration
state. If the ID has been invalidated, the per-network endpoint returns `404`.
A release or expiry prevents a new restart; if commands are already running,
Wi-Lab finishes cleanup under the device lock before the antenna can be reassigned.

## Enabling automatic USB reset

Automatic USB reset is disabled unless `usb_recovery_port` is set on that
network entry. Use only a verified, dedicated Wi-Lab USB adapter and physical
port, never a shared adapter, hub, controller, or management link. Install
`usbreset` from the operating system's USB utilities and grant the Wi-Lab
service the required privileges. Example:

```yaml
networks:
  - interface: "wlx001122334455"
    display_name: "lab-antenna"
    usb_recovery_port: "2-1"
```

`usb_recovery_port` is the Linux USB topology name for the port attached to
that specific Wi-Fi interface, not its MAC address or current USB device number.
For example `2-1` is port 1 on USB bus 2; `2-1.3` is downstream port 3 of
the device attached at `2-1`. Check it with
`readlink -f /sys/class/net/<interface>/device`: if the last component is
`2-1:1.0`, the port name is `2-1`. Recheck the mapping after moving an adapter
or changing the host or VM USB topology. Omitting the key leaves the watchdog
and cooldowns enabled, but does not authorize an automatic USB reset.

The service matches the configured interface to the exact USB port and refuses
to reset a hub, a multifunction device, or an interface that is not idle
and in `managed/DOWN`. If cleanup fails, the worker can retry cleanup but
cannot reset the USB device until it succeeds. An unclassified failure with
unsafe cleanup quarantines the adapter without authorizing a USB reset.

On an opted-in adapter with a classified radio fault, Wi-Lab schedules at most
10 recovery rounds, with at least 60 seconds between rounds. Each round can
reset only the matched USB device; a failed safety check skips the reset.
Recovery succeeds only if the expected interface returns with the same MAC at
the authorized port and can be brought up in managed mode. Before clearing
quarantine, Wi-Lab also starts a hidden, WPA2-protected test AP with a random
unshared key on the channel that failed, assigns the gateway, and verifies that
the AP is enabled and its DHCP daemon is running. The probe does not enable NAT
or advertise a default route or DNS and does not appear as a user network. It
must be torn down successfully and the radio returned to `managed/DOWN`.
This is a server-side check; actual association and DHCP lease acquisition
require a separate Wi-Fi station. Other adapters remain available.

If recovery is disabled or fails, the adapter stays quarantined for the
running service instance. Quarantine and reservations are in memory; do not
use a service restart as a substitute for checking the hardware. Use the
[manual recovery procedure](recovery.md) before returning a failed device to
service.
