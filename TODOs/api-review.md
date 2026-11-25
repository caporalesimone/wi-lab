# API review: points to discuss

**Priority:** 2 (MEDIUM)
**Status:** TO DISCUSS (listed on 2026-11-25)

Points left open after the 4.0.0 API changes (sections, Antennas API,
monitoring, error codes, `/reservations` paths). To be discussed before
implementing.

## Breaking, to decide before 4.0.0 is released

- **Actions as paths (Fable API-7).** Replace `POST .../internet/enable`,
  `.../internet/disable` and `POST .../txpower` with one `PATCH .../network`
  that takes the same sections as the create body, e.g.
  `{"internet": {"enabled": false}, "radio": {"tx_power_level": 2}}`.
- **The create answers only a sentence (Fable API-5).** Return the network, as
  `GET .../network` does, so the client saves a call.
- **`/api/v2` prefix.** Explained on 2026-11-25, not decided: change only the
  prefix, without keeping `/api/v1`.

## Additions (not breaking)

- **Reserve a given antenna:** optional `interface` in the reservation
  request. Natural for the future control center, now that `/antennas` lists
  them.
- **Request id for the create (`Idempotency-Key` header).** Removes the
  ambiguity after a transport error: the same key returns the same result
  instead of a second create.
- **Extend a reservation** without releasing it.
- **Remove `/debug`.** Deprecated in 4.0.0; decide when, maybe together with
  the growth of `/monitoring`.
- **Duplicated data (Fable API-1)** between reservation, network and
  `/status`. The sections removed most of it; check what is left.
