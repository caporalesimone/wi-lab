# API review: points to discuss

**Priority:** 2 (MEDIUM)
**Status:** TO DISCUSS (listed on 2026-11-25)

Points left open after the 4.0.0 API changes (sections, Antennas API,
monitoring, error codes, `/reservations` paths). To be discussed before
implementing.

## Breaking, postponed (decided 2026-11-25: not now)

- **Actions as paths (Fable API-7).** Replace `POST /access-point/{id}/internet/enable`
  and `.../internet/disable` with one `PATCH /access-point/{id}` that takes the
  same sections as the create body, e.g. `{"internet": {"enabled": false}}`.

## Additions (not breaking)

- **Extend a reservation** without releasing it.

## Decided

- `Idempotency-Key` (2026-11-25): not done. Replaced by a simpler rule: the
  same create body on a running network answers `200` with the network.
- Moving a reservation to another antenna after a quarantine (2026-11-25):
  not done; it does not help when the other antennas are reserved.
