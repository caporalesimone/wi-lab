# API review: points to discuss

**Priority:** 2 (MEDIUM)
**Status:** TO DISCUSS (listed on 2026-11-25)

Points left open after the 4.0.0 API changes (sections, Antennas API,
monitoring, error codes, `/reservations` paths). To be discussed before
implementing.

## Breaking, postponed (decided 2026-11-25: not now)

- **Actions as paths (Fable API-7).** Replace `POST .../internet/enable`,
  `.../internet/disable` and `POST .../txpower` with one `PATCH .../network`
  that takes the same sections as the create body, e.g.
  `{"internet": {"enabled": false}, "radio": {"tx_power_level": 2}}`. It would
  also settle the TX power field name (`level` vs `radio.tx_power_level`).

## Additions (not breaking)

- **Extend a reservation** without releasing it.
- **Remove `/debug`.** Deprecated in 4.0.0. It duplicates `/monitoring`; its
  only own data are the raw iptables rules and every client's
  `reservation_id` (the SEC-2 concern). Proposal: remove it in 4.0.0.

## Duplicated data (Fable API-1): analysis of 2026-11-25, to discuss

The sections removed most of it. What is left:

1. **`stop_failed` is missing from `/status`.** `GET .../network` reports
   `runtime_state: stop_failed` after `503 / 1012`; `/status` shows only the
   watchdog state, has no `degraded_reasons` entry for it, and the network
   still counts in `active_networks` (the dnsmasq check can report it as
   `dnsmasq_not_running`, which misleads). Fix: `runtime_state: stop_failed`
   in the antenna entry and a reason such as `network_stop_incomplete`.
2. **Same value, two names.** `/status` has `reservation_remaining_seconds`;
   reservation and network call it `expires_in` inside
   `reservation{expires_at, expires_in}`. Use that object in `/status` too
   (small breaking change).
3. **Missing rather than duplicated.** `/status` gives `active_networks` as a
   count but no per-antenna flag: a reserved antenna with and without a
   network look the same. Add `network_active` per antenna (addition).
4. **`/debug`** duplicates `/monitoring` (see above).
5. **Kept on purpose:** `display_name` and `interface` in reservation,
   antennas and status; `status` and `degraded_reasons` in both `/status` and
   `/monitoring`.

## Decided

- `Idempotency-Key` (2026-11-25): not done. Replaced by a simpler rule: the
  same create body on a running network answers `200` with the network.
- Moving a reservation to another antenna after a quarantine (2026-11-25):
  not done; it does not help when the other antennas are reserved.
