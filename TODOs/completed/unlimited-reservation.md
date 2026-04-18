# Unlimited Reservation

Allow creating reservations with no expiry (`duration_seconds: 0`) when `allow_unlimited_reservation: true` in config.
The reservation stays active until explicitly released. `expires_at` and `expires_in` will be `null` in API responses.

Hard constraint: `min_timeout` can never be lower than 10 seconds (hardcoded).

Note: the original TODO mentions a flat `/status.allow_unlimited_reservation` field. The final implementation evolved to `reservation_policy.allow_unlimited`, which is what the frontend now consumes.

---

## Config & Documentation

- [x] **config.py** — Add `allow_unlimited_reservation: bool = False` to `AppConfig` after `min_timeout`
- [x] **config.py** — Add validator for `min_timeout` that rejects values < 10 (hardcoded floor)
- [x] **config.example.yaml** — Add documented `allow_unlimited_reservation` parameter below `min_timeout`
- [x] **config.example.yaml** — Add comment about hardcoded `min_timeout >= 10` constraint
- [x] **config.yaml** — Align comments with the same changes from the example file (without touching environment-specific values)
- [x] **tests/test.config.yaml** — Add `allow_unlimited_reservation: false`

## Backend — Reservation Logic

- [x] **wilab/reservation.py** — Modify `Reservation` dataclass: `expires_at` becomes `Optional[float]` (None = unlimited)
- [x] **wilab/reservation.py** — `Reservation.expires_in`: return `None` when `expires_at is None`
- [x] **wilab/reservation.py** — `Reservation.is_expired`: return `False` when `expires_at is None`
- [x] **wilab/reservation.py** — `ReservationManager.create()`: if `duration_seconds == 0` → set `expires_at = None`
- [x] **wilab/reservation.py** — `ReservationManager._purge_expired()`: skip reservations with `expires_at is None`
- [x] **wilab/reservation.py** — `ReservationManager._soonest_expiry()`: exclude unlimited reservations from calculation

## Backend — API Routes

- [x] **wilab/api/routes/reservation.py** — `ReservationCreateRequest`: change `gt=0` to `ge=0`, validate that `duration_seconds == 0` is only accepted when `allow_unlimited_reservation` is true in config
- [x] **wilab/api/routes/reservation.py** — Add validation of `duration_seconds` against `min_timeout` / `max_timeout` from config (currently missing)
- [x] **wilab/api/routes/reservation.py** — `ReservationResponse`: make `expires_at` and `expires_in` `Optional` (`None` when unlimited)
- [x] **wilab/api/routes/reservation.py** — In POST handler: build response with `expires_at=None, expires_in=None` when unlimited
- [x] **wilab/api/routes/status.py** — `reservation_remaining_seconds` in `/status`: return `null` for unlimited reservations

## Backend — Status Endpoint

- [ ] **wilab/api/routes/status.py** — Expose `allow_unlimited_reservation` in the `/status` response (for the frontend)

## Tests

- [ ] **tests/test_reservation.py** — Test: create unlimited reservation (`duration_seconds=0`) with flag enabled → success, `expires_at is None`
- [ ] **tests/test_reservation.py** — Test: create unlimited reservation with flag disabled → rejected (422)
- [x] **tests/test_reservation.py** — Test: unlimited reservation is not purged by `_purge_expired()`
- [x] **tests/test_reservation.py** — Test: unlimited reservation `is_expired` returns False
- [x] **tests/test_reservation.py** — Test: unlimited reservation `expires_in` returns None
- [x] **tests/test_reservation.py** — Test: `_soonest_expiry()` ignores unlimited reservations
- [x] **tests/test_config.py** — Test: `min_timeout < 10` rejected at config validation
- [x] **tests/test_config.py** — Test: `allow_unlimited_reservation` defaults to False
- [x] **tests/test_api.py** — Test: POST reservation with `duration_seconds=0` and flag enabled → 200, response with `expires_at: null`
- [x] **tests/test_api.py** — Test: POST reservation with `duration_seconds=0` and flag disabled → 422
- [x] **tests/test_api.py** — Test: POST reservation with `duration_seconds < min_timeout` (and != 0) → 422
- [x] **tests/test_api.py** — Test: POST reservation with `duration_seconds > max_timeout` → 422
- [ ] **tests/test_api.py** — Test: `/status` exposes `allow_unlimited_reservation`
- [x] **tests/test_api.py** — Test: `/status` shows `reservation_remaining_seconds: null` for unlimited reservation

## Frontend — Models

- [x] **models/network.models.ts** — `ReservationResponse`: make `expires_at` and `expires_in` nullable (`string | null`, `number | null`)
- [ ] **models/network.models.ts** — Add `allow_unlimited_reservation: boolean` field to status response model (create model if it doesn't exist)

## Frontend — Reservation Dialog

- [x] **reservation-dialog.component.ts** — Retrieve `allow_unlimited_reservation` from status (via service or input)
- [x] **reservation-dialog.component.ts** — Add "Unlimited" checkbox control, visible only when `allow_unlimited_reservation` is true
- [x] **reservation-dialog.component.ts** — When checkbox active: disable duration field, set `duration_seconds = 0`
- [x] **reservation-dialog.component.html** — Add "Unlimited reservation (no expiry)" checkbox above the duration field
- [x] **reservation-dialog.component.html** — Visually disable the duration field when checkbox is active

## Frontend — Network Card (own reservation)

- [x] **network-card.component.ts** — Detect unlimited reservation: `expires_in === null`
- [x] **network-card.component.ts** — When unlimited: do not start countdown, do not emit `released`
- [x] **network-card.component.html** — Show "∞ Unlimited" instead of the countdown timer
- [x] **network-card.component.html** — Hide progress bar for unlimited reservations

## Frontend — Network Card (other user's reservation — Occupied)

- [x] **network-card.component.ts** — Handle `reservation_remaining_seconds === null` as occupied unlimited
- [x] **network-card.component.html** — Show "Occupied — No expiry" instead of "Occupied — 00:00:00"

## Frontend — App Component

- [x] **app.component.ts** — Pass `allow_unlimited_reservation` from `/status` to the reservation dialog
- [x] **app.component.ts** — Handle reservation response with `expires_in: null` (do not start capacity timer)
