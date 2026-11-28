# Feature: QoS v2

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~3 days (API and engine), ~1 day (frontend), ~1 day (tests on real radio)  

## Description

QoS is experimental in 4.1: it works, but it is untested on real radios, its API
still follows the 4.0 style and some of its numbers do not mean what the
documentation says. This proposal lists every change worth making before QoS
leaves the experimental state. It is a breaking change of the QoS endpoints only;
everything else stays as it is.

How QoS works today:

- `wilab/network/qos.py` (`QosManager`): on the AP interface, an HTB root
  (`1:`) with one class (`1:10`) shapes the download (traffic towards the
  clients). An `ingress` qdisc redirects everything the clients send to an IFB
  device (`wilab-ifbN`), which has the same HTB tree for the upload. A `netem`
  qdisc under `1:10` adds loss, delay, jitter and corruption.
- `wilab/network/qos_profile.py` (`QosProfileManager`): loads the catalogue
  (`wilab/data/qos-profiles/*.json`, checked against `profile.schema.json`
  first and then against the Pydantic models), and runs one profile per
  interface in a thread that applies one step after another.
- `wilab/api/routes/qos_profile.py`: `GET /api/v2/qos/profiles`, and `POST`,
  `GET` and `DELETE /api/v2/reservations/{reservation_id}/qos/profile`.
  Inline parameters become a one-step `once-hold-last` profile.
- The stop of the access point (and so every watchdog AP restart) stops the
  profile and removes the `tc` rules. The frontend has no QoS controls.

## Problems Found

### Wrong or misleading numbers

1. **The delay counts twice in the round trip.** The same netem settings go on
   the download (AP interface) and on the upload (IFB). `delay_ms: 600` gives
   about 1200 ms of RTT. The table in `docs/qos.md` presents the values as the
   delay of the link, and `satellite_link` (600 ms) simulates a 1.2 s RTT, while
   a geostationary link has about 600 ms of RTT. Same for the quality table:
   quality 50 is 500 ms of RTT, not 250 ms.
2. **Loss also counts twice.** 30% loss in each direction loses about 51% of the
   request and answer pairs (1 − 0.7²). A ping test reads "50% loss" at quality 0.
3. **Jitter reorders packets.** netem with jitter and no `rate` sends packets in
   the order of their random delay, so TCP sees heavy reordering and its
   throughput collapses far more than on a real mobile link, where jitter does
   not reorder. Every catalogue profile using `quality` has jitter.
4. **Random loss, not bursts.** The loss is independent per packet. Radio loss
   comes in bursts (fading, handovers); netem supports this with
   `loss gemodel` (Gilbert-Elliott) or `loss state`.
5. **Quality 0 is not "no signal".** It is 30% loss and 1 s of delay. The
   `4g_train_tunnel` and `4g_rural` profiles use quality 0 for a tunnel or a
   drop, where a real link loses everything.
6. **netem queue limit.** netem keeps 1000 packets by default. With high delay
   and high rate (1 s at 100 Mbit/s is about 8300 packets) it drops packets that
   no setting asked to drop.
7. **Jitter without delay is ignored without a message.** `_build_netem_args`
   uses jitter and `delay_distribution` only when `delay_ms > 0`; the request
   answers `200` and the response does not show it.

### Scope of the impairment

8. **Everything on the interface is impaired**, including the services of the
   AP itself: DHCP, DNS, the captive portal page. At quality 0 a phone can fail
   to get an address and look "disconnected" instead of "slow", which is a
   different test. Traffic from client to client is impaired too.
9. **EAPOL (the WPA handshake) is probably not impaired** (hostapd sends it over
   nl80211 on recent kernels), but nobody checked. To verify on the real radio,
   because a reconnection during a bad step depends on it.
10. **One profile for the whole network.** Per-client shaping is a separate
    proposal ([Per-client rate limit](../clients/rate-limit.md)) and must share
    the same `tc` tree.

### API

11. **Path out of line with v2.** Everything else of a running network is under
    `/api/v2/access-point/{reservation_id}`; QoS is still under
    `/reservations/{reservation_id}/qos/profile`.
12. **Two names for the same field.** The inline body uses
    `download_speed_kbit`/`upload_speed_kbit`, the profile steps use
    `dl_speed_kbit`/`ul_speed_kbit`.
13. **`download_quality` and `upload_quality` must be equal**, so two fields
    describe one value. Either one field (`quality`) or two that really work
    on their own (an uplink worse than the downlink is a common real case).
14. **`steps` is a number in the state and a list in the catalogue.**
15. **No way to switch profile in one call.** `POST` with a running profile is
    `409 / 1010`; the client must `DELETE` first, which leaves a moment with no
    impairment.
16. **The state does not say what is applied.** `NetemParams` exists ("returned
    in QoS status responses") but no response uses it. The client cannot see
    the rate, loss and delay of the current step.
17. **`DELETE` answers `{"detail": "Profile '...' deactivated correctly."}`**:
    `detail` is the error field everywhere else, and the message is the only
    content. A failed stop is a `500` with a plain string.
18. **The inactive state is a list of nulls.** The other v2 answers leave unset
    fields out.
19. **A finished `once` profile looks like no profile.** `active: false` with
    no trace of what ran, when it ended or whether the thread failed (an
    exception is only logged, and the shaping is removed without a word).
20. **Inline profiles show nonsense.** The id is `a1b2c3d4:generated_static`,
    `source_file` is `"generated"`, the step has `duration_sec: 1` and
    `elapsed_sec` grows past it.
21. **`source_file` is an internal detail** exposed in the catalogue and the state.
22. **The catalogue has no single-profile `GET`**, and the client cannot send
    its own profile (steps) in the request: custom profiles need a file on the
    server and a service restart.
23. **OpenAPI descriptions are wrong:** `404 "Reservation or profile not found"`
    (an unknown profile is `422`), `404 "no active profile"` on `DELETE` (it is
    `409 / 1011`). `POST` answers `200`, not `201`.
24. **Speed from 1 kbit/s.** HTB with a minimum burst of 15000 bytes does not
    shape 1 kbit/s in any useful way; a lower limit around 64 kbit/s is honest.

### Engine

25. **The profile thread runs `tc` without the antenna lock.** An Internet
    toggle or a stop can run at the same moment as a step change. The stop
    joins the thread first, which helps, but the other calls do not.
26. **The partial-update logic of `QosManager.apply_qos`** (`_SENTINEL`,
    separate download and upload qualities in the state) is not used: every
    step sets all fields. It is complexity without a caller.
27. **Two validations of the catalogue.** `profile.schema.json` and the Pydantic
    models say the same thing in two places and can drift. The schema can be
    generated from the model (`QosProfile.model_json_schema()`).
28. **Custom profiles live in the package directory**
    (`wilab/data/qos-profiles/`), which an update or reinstall replaces.
29. **A watchdog AP restart removes the profile** and the client must notice it
    from `restarts.ap` and apply it again. Wi-Lab knows what was running and can
    apply it again itself.
30. **`_ensure_ifb` adds the redirect filter again** when the `ingress` qdisc is
    already there, which can leave duplicate filters after an error.

### Documentation (`docs/qos.md`)

31. The delay and loss tables do not say that they apply to each direction
    (points 1 and 2), nor which direction is "download" (towards the client).
32. The error table still says "Network not active" for `1007` (now
    `access_point_not_active`) and does not list `409 / 1012 stop_incomplete`,
    which the endpoints answer.
33. "QoS is cleared automatically when the network is stopped" and "Profiles do
    not survive a network restart" say the same thing; a watchdog AP restart,
    the case a tester does not trigger, is missing.
34. The quality formula is not written; only six sample rows are.
35. The units are not stated (`kbit` = 1000 bit/s), nor the limits of the
    fields (`delay_ms` up to 5000, `corruption_percent` up to 5).
36. "Custom profile files" asks to write in the package directory (point 28).

## Implementation Tasks

### API

- [ ] Move the endpoints to `/api/v2/access-point/{reservation_id}/qos`
- [ ] `PUT .../qos` starts or replaces what runs, in one call and without a gap (point 15); `GET` reads; `DELETE` stops
- [ ] One body: `profile_id`, **or** `profile` (a whole profile sent by the client), **or** `static` (one step held until stopped)
- [ ] One step format everywhere: `download_kbit`, `upload_kbit`, `quality`, `impairment`; the same names in the catalogue, the inline step and the state
- [ ] `quality` and `impairment` can be given for each direction (`download`, `upload`) or once for both
- [ ] The state shows the applied values of the current step (`applied.download`, `applied.upload`), with the RTT that results
- [ ] The state keeps the last run: `state: running | finished | failed | stopped`, `ended_at`, `error`
- [ ] Unset fields left out of the answer, as in the other v2 answers
- [ ] `DELETE` answers the final state (`state: stopped`), not a message in `detail`
- [ ] `GET /api/v2/qos/profiles/{profile_id}`; `source_file` removed
- [ ] Optional `apply_again_after_restart` (default true): after a watchdog AP restart the profile starts again from step 0, and `restarts.ap` still counts it
- [ ] Error codes: `409 / 1010` and `409 / 1011` are no longer needed with `PUT` and the idempotent `DELETE`; `404` only for the reservation, `422` for an unknown profile

### Engine

- [ ] Delay and loss mean **one direction**; the documentation says the RTT is the sum; the catalogue profiles are corrected (`satellite_link` 300 ms each way)
- [ ] No reordering: netem with `rate` or a `pfifo` child, so jitter does not reorder (check on the kernel in use)
- [ ] `loss_model: random | bursty` (Gilbert-Elliott via `loss gemodel`), `duplicate_percent`, `reorder_percent` as explicit options
- [ ] A step `outage: true` (100% loss) for tunnels and drops; `4g_train_tunnel` and `4g_rural` use it
- [ ] netem `limit` computed from rate and delay
- [ ] `jitter_ms` without `delay_ms` refused with `422`
- [ ] `scope: all | internet` (default `internet`): with `internet`, `tc` filters leave DHCP, DNS and traffic to the AP address unimpaired
- [ ] Step changes under the antenna lock, like every other operation
- [ ] `QosManager` simplified: one `apply(step)` that builds the whole tree, no partial updates
- [ ] One validation: `profile.schema.json` generated from the Pydantic model (or removed)
- [ ] Custom profiles in a configurable directory (`qos_profiles_dir` in `config.yaml`, default `/etc/wilab/qos-profiles`), loaded at startup
- [ ] `_ensure_ifb` checks for the filter before adding it
- [ ] The same `tc` tree hosts per-client classes ([rate limit](../clients/rate-limit.md)): the shared class `1:10` becomes the default class, and client classes are added beside it

### Frontend

- [ ] On the antenna card with a running access point: profile picker from the catalogue, static form (download, upload, quality), stop button
- [ ] Current step and applied values, refreshed with the card

### Documentation

- [ ] `docs/qos.md` rewritten for v2: directions, one-way values, the RTT, units and limits, the formula, the error table with `1007` and `1012`, the restart behaviour, the custom profile directory
- [ ] Migration chapter in the CHANGELOG for the moved and renamed fields

## API Proposal

### `GET /api/v2/qos/profiles`

List the catalogue. No authentication.

Request: no body.

Response `200`:

```json
[
  {
    "id": "satellite_link",
    "description": "Geostationary satellite: high latency, stable bandwidth.",
    "mode": "loop",
    "steps": [
      {
        "duration_sec": 60,
        "download_kbit": 15000,
        "upload_kbit": 3000,
        "impairment": {
          "delay_ms": 300,
          "jitter_ms": 15,
          "loss_percent": 0.5,
          "loss_model": "random"
        }
      }
    ]
  }
]
```

### `GET /api/v2/qos/profiles/{profile_id}`

One profile of the catalogue, in the same format as an item of the list.

Errors: `404 not_found` for an unknown id.

### `PUT /api/v2/access-point/{reservation_id}/qos`

Start a profile, or replace the one that runs, in one call. Exactly one of
`profile_id`, `profile`, `static`.

Request (from the catalogue):

```json
{
  "profile_id": "4g_urban_moving",
  "scope": "internet",
  "apply_again_after_restart": true
}
```

Request (a profile sent by the client):

```json
{
  "profile": {
    "mode": "once",
    "steps": [
      { "duration_sec": 20, "quality": 85 },
      { "duration_sec": 10, "outage": true },
      { "duration_sec": 20, "quality": { "download": 80, "upload": 60 } }
    ]
  }
}
```

Request (static, held until stopped):

```json
{
  "static": {
    "download_kbit": 8000,
    "upload_kbit": 3000,
    "impairment": { "delay_ms": 40, "jitter_ms": 10, "loss_percent": 1, "loss_model": "bursty" }
  }
}
```

Response `200`:

```json
{
  "interface": "wlx00c0caabcdef",
  "state": "running",
  "profile_id": "4g_urban_moving",
  "mode": "loop",
  "scope": "internet",
  "apply_again_after_restart": true,
  "started_at": "2026-11-28T10:15:00Z",
  "step": { "index": 0, "count": 7, "elapsed_sec": 0, "duration_sec": 15 },
  "applied": {
    "download": { "rate_kbit": null, "delay_ms": 22, "jitter_ms": 7, "loss_percent": 0.7 },
    "upload": { "rate_kbit": null, "delay_ms": 22, "jitter_ms": 7, "loss_percent": 0.7 },
    "rtt_added_ms": 44
  }
}
```

For a client profile `profile_id` is absent; for `static` the answer has
`"mode": "static"` and no `step`.

Errors: `409 / 1007 access_point_not_active`; `409 / 1012 stop_incomplete`;
`503 / 1006 device_busy` with `Retry-After`; `422 validation_error` with the
field path (`profile_id: not in the catalogue`, `static.impairment.jitter_ms:
needs delay_ms`, `body: exactly one of profile_id, profile, static`).

### `GET /api/v2/access-point/{reservation_id}/qos`

The state, in the format of the `PUT` answer. With nothing ever started:

```json
{
  "interface": "wlx00c0caabcdef",
  "state": "none"
}
```

After a `once` profile ended, or a failure:

```json
{
  "interface": "wlx00c0caabcdef",
  "state": "failed",
  "profile_id": "4g_train_tunnel",
  "started_at": "2026-11-28T10:15:00Z",
  "ended_at": "2026-11-28T10:16:02Z",
  "error": "tc: RTNETLINK answers: No such device"
}
```

Errors: `409 / 1007`, `409 / 1012`, `503 / 1006`.

### `DELETE /api/v2/access-point/{reservation_id}/qos`

Stop and remove every rule. Idempotent: with nothing running it answers the
same `200`.

Request: no body.

Response `200`:

```json
{
  "interface": "wlx00c0caabcdef",
  "state": "stopped",
  "profile_id": "4g_urban_moving",
  "ended_at": "2026-11-28T10:20:00Z"
}
```

Errors: `409 / 1007`, `409 / 1012`, `503 / 1006`.

## Testing

- [ ] Unit tests: the `tc` commands of each step, the one-way values, the `limit`, the `scope` filters, the state transitions (`running`, `finished`, `failed`, `stopped`), `PUT` replacing without a gap
- [ ] Real radio: ping and iperf3 through the AP, check that the measured RTT and loss match the profile (one direction each), that jitter does not reorder (`iperf3 -u` out-of-order count), that DHCP works at quality 0 with `scope: internet`
- [ ] Real radio: a phone reconnects during a bad step (EAPOL not impaired)
- [ ] E2E: watchdog AP restart with `apply_again_after_restart` true, the profile runs again

## Benefits

- **Correct numbers:** a profile that says 600 ms of RTT gives 600 ms
- **Realistic links:** bursty loss, outages, no artificial reordering
- **Simpler client code:** one `PUT`, a state that says what happens and what happened
- **Custom scenarios** without files on the server or a restart

## Breaking Changes

- QoS endpoints move from `/reservations/{reservation_id}/qos/profile` to `/access-point/{reservation_id}/qos`; `POST` becomes `PUT`
- Fields renamed: `dl_speed_kbit` / `download_speed_kbit` → `download_kbit`, `advanced` → `impairment`, `packet_loss_percent` → `loss_percent`, `download_quality` / `upload_quality` → `quality`
- State: `active` → `state`, `current_step` + `steps` → `step`, `total_elapsed_sec` → `started_at`, `source_file` removed
- Delay and loss values of the catalogue profiles change meaning (one direction)
- Error codes `1010` and `1011` no longer answered

## Success Criteria

- ✅ Measured RTT and loss match the profile within 10%
- ✅ Switching profile never leaves a moment without impairment
- ✅ A tester sees from `GET` what is applied now and how the last run ended
- ✅ DHCP and DNS keep working at the worst quality with `scope: internet`
- ✅ The frontend starts and stops a profile
