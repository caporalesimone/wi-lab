# Device Reservation Refactor (Full Rewrite)

## Objective

Redesign Wi-Lab reservation and network lifecycle so device ownership is controlled by a reservation token and not by static config `net_id`.

### User Experience Overview

From the user's perspective, the system will work as follows:

1. **Reservation First**: User opens the app and sees no networks. Only a prominent "Reserve Device" button is available.
2. **Claim Time Window**: User clicks reserve, specifies how long they need the device (in seconds), and submits. The API allocates the first free antenna and returns a unique reservation token.
3. **Network Card Appears**: Once reservation succeeds, a network card appears displaying the reserved device with WiFi controls (SSID, password, channel, etc.).
4. **Always-Visible Countdown**: A live countdown shows remaining reservation time as a progress bar (100% → 0%) with `hh:mm:ss` label. This stays visible whether the WiFi is on or off.
5. **Release & Cleanup**: When done, user clicks "Release Network" to free the device for others. The card vanishes. If the reservation expires naturally, the WiFi shuts down and the card also disappears.
6. **Full Capacity**: If all devices are reserved, the API returns a "no device available" error with the next-available timestamp, displayed in the UI.

The implementation is split into two phases:

- **Phase 1**: Backend API changes — introduce reservation endpoints, remove static `net_id`, bind network lifetime to reservation timeout only.
- **Phase 2**: Frontend UI changes — remove pre-loaded cards, add reservation dialog, show dynamic card post-reservation, implement always-on countdown + progress bar.

This document is the execution plan split into:
- Phase 1: API review
- Phase 2: Frontend refactor

---

## Functional Directives (Consolidated)

1. Remove `net_id` from configuration.
2. Wi-Lab manages devices internally with its own stable identifier (simple choice: physical interface name).
3. First API call by user must be reservation API.
4. Reservation checks if at least one antenna/device is free for use (free does not mean network off; it means not reserved).
5. If available, API returns random code used as `net_id` in subsequent APIs (reservation token).
6. Token becomes invalid immediately after release (`DELETE device reservation/{net_id}`).
7. If all devices are reserved, return 4xx with nearest availability information.
8. Reservation requires duration in seconds; this drives the next-availability estimate.
9. At reservation expiry, device is turned off and token becomes invalid.
10. Resolve naming conflict between old `net_id` and new random token.
11. Remove current WiFi create-time timeout; reservation timeout becomes the only lifetime driver.
12. Status API must report physical device name + reservation remaining seconds.
13. Get Network API must always expose `expires_at` and `expires_in`, even when network is off.

Frontend alignment:
- At time 0, no network cards shown; only reservation button.
- On successful reservation, network card appears.
- Card has release button; card disappears when token is no longer accepted.
- `GET network` provides remaining time in any state.
- Remaining time is always visible (seconds + progress bar 100% to 0%) with `hh:mm:ss` text.

---

## Core Design Decisions

### 1. Identifier Model (Conflict Resolution)

To avoid ambiguity between legacy static `net_id` and new random token:
- Use `device_id` for internal stable identifier (mapped to interface name, e.g. `wls16`).
- Use `reservation_id` for random external token returned by reservation API.
- Keep backward compatibility for a short transition only if necessary, but target model is:
  - Config/API internals never rely on static `net_id` from config.
  - Client-facing operations are keyed by `reservation_id`.

### 2. Config Model

Replace networks section from:
- `net_id` + `interface`

to:
- `interface` (required)
- optional human label (non-key), e.g. `display_name`

Example target:
```yaml
networks:
  - interface: "wls16"
    display_name: "bench-antenna-1"
```

### 3. Reservation-Led Lifecycle

- Reservation creates exclusive ownership window (`duration_seconds`).
- Network lifetime is bounded by reservation expiry only.
- At expiry:
  - force network stop if active,
  - invalidate reservation token.
  - release device,
  
---

## Phase 1: API Review

- [ ] Task 1 - Replace Static Config Identity with Internal Device Identity
- [ ] Task 2 - Introduce Reservation APIs as Mandatory Entry Point
- [ ] Task 3 - Enforce Reservation Availability Semantics and 4xx with ETA
- [ ] Task 4 - Make Reservation Timeout the Single Lifetime Source
- [ ] Task 5 - Propagate Reservation Context to Existing Network APIs
- [ ] Task 6 - Update Status and Get Network Contracts
- [ ] Task 7 - Migration and Naming Cleanup

### Task 1 - Replace Static Config Identity with Internal Device Identity

Subtasks:
- Remove `net_id` from config schema and validation.
- Introduce internal `device_id = interface` mapping in runtime state.
- Ensure all internal lookups use `device_id`.

Test logic to add:
- Config parsing test: configuration without `net_id` is valid.
- Config rejection test: configuration with `net_id` (legacy) returns explicit validation error (or warning during transition if chosen).
- Runtime mapping test: each configured interface has unique `device_id` and deterministic loading order.

### Task 2 - Introduce Reservation APIs as Mandatory Entry Point

Target endpoints:
- `POST /api/v1/device-reservation`
- `GET /api/v1/device-reservation/{reservation_id}`
- `DELETE /api/v1/device-reservation/{reservation_id}`

Subtasks:
- Implement `POST` with payload `{ "duration_seconds": <int> }`.
- Allocate first available non-reserved device.
- Generate cryptographically secure random `reservation_id`.
- Return reservation metadata: `reservation_id`, `device_id`, `expires_at`, `expires_in`.
- Implement `GET` to fetch reservation status by token.
- Implement `DELETE` to release reservation and invalidate token.

Test logic to add:
- Happy path: reservation is created and token is returned.
- Randomness/uniqueness test: repeated reservations do not collide.
- `GET` valid token test: returns current state and remaining time.
- `DELETE` valid token test: releases device and invalidates token.
- Post-release invalidation test: subsequent `GET`/network operations with same token return 4xx.

### Task 3 - Enforce Reservation Availability Semantics and 4xx with ETA

Subtasks:
- Define “available” = not currently reserved.
- If all devices reserved, return 4xx (recommended `409 Conflict`) with fields:
  - `next_available_in`
  - `next_available_at`
- Compute ETA from soonest reservation expiry.

Test logic to add:
- Full-capacity test: all devices reserved returns 4xx.
- ETA correctness test: response uses nearest expiry among active reservations.
- Edge test: simultaneous expiries choose non-negative minimal ETA.

### Task 4 - Make Reservation Timeout the Single Lifetime Source

Subtasks:
- Remove timeout parameter/effective use from create network API logic.
- Bind network shutdown scheduler to reservation expiry only.
- On expiry: stop WiFi network, free device, invalidate token.

Test logic to add:
- Create network ignores/removes old timeout behavior.
- Reservation expiry triggers automatic network stop.
- Expired token test: any follow-up operation returns 4xx invalid reservation.
- Regression test: no duplicate timers remain active from legacy network timeout.

### Task 5 - Propagate Reservation Context to Existing Network APIs

Subtasks:
- Require valid `reservation_id` (legacy field name `net_id` can temporarily carry the token in path/query while API evolves).
- Resolve token -> device association before network operations.
- Reject operations when token is invalid/expired/released.

Test logic to add:
- Protected operation without reservation token returns 4xx (recommended `401/403/404` based on chosen policy).
- Protected operation with invalid token returns 4xx.
- Protected operation with valid token reaches correct device.

### Task 6 - Update Status and Get Network Contracts

Subtasks:
- Status API includes, for each physical device:
  - `device_id` (or physical interface field)
  - `reservation_remaining_seconds`
- Get Network API always includes:
  - `expires_at`
  - `expires_in`
  even when network is off.

Test logic to add:
- Status payload test: remaining seconds present and monotonic decreasing.
- Status payload test: includes physical device identifier.
- Get network (active) test: `expires_at`/`expires_in` present.
- Get network (off) test: same fields still present with coherent values.

### Task 7 - Migration and Naming Cleanup

Subtasks:
- Replace documentation and code references from old `net_id` meaning to new model:
  - `device_id` internal
  - `reservation_id` external token
- Optionally support transition alias with deprecation warning.
- Remove obsolete docs about create-network timeout ownership.

Test logic to add:
- Contract test: OpenAPI examples reflect new reservation model.
- Deprecation test (if alias enabled): legacy path accepted but warns.
- Negative test: static config `net_id` is not used as operational key.

---

## Phase 2: Frontend Refactor

- [ ] Task 1 - Initial Empty State with Reservation-First UX
- [ ] Task 2 - Show Card Only After Successful Reservation
- [ ] Task 3 - Add Release Network Action and Card Removal
- [ ] Task 4 - Always Display Remaining Time
- [ ] Task 5 - Add Reservation Progress Bar with hh:mm:ss Label
- [ ] Task 6 - Error UX for No Available Devices

### Task 1 - Initial Empty State with Reservation-First UX

Subtasks:
- At app start show no network cards.
- Show primary action button: “Reserve device”.
- Reservation dialog asks for duration in seconds.

Test logic to add:
- Initial render test: zero cards shown, reservation CTA visible.
- Validation test: duration must be positive and within allowed bounds.
- Submit test: sends `POST /device-reservation` with seconds payload.

### Task 2 - Show Card Only After Successful Reservation

Subtasks:
- On successful reservation, render network card bound to `reservation_id`.
- Store reservation metadata (`reservation_id`, `expires_at`, `expires_in`, `device_id`).

Test logic to add:
- Success flow test: card appears only after 2xx reservation response.
- Failure flow test: card does not appear on 4xx/5xx reservation response.
- State binding test: card uses returned reservation token for subsequent calls.

### Task 3 - Add Release Network Action and Card Removal

Subtasks:
- Add `Release Network` button on card.
- Call `DELETE /device-reservation/{reservation_id}`.
- On success, remove card and clear local reservation state.
- If backend reports token invalid, force card removal and reset UI.

Test logic to add:
- Release success test: delete call made, card disappears.
- Release invalid-token test: UI handles 4xx by removing stale card.
- Idempotency UX test: repeated clicks cannot keep stale active UI.

### Task 4 - Always Display Remaining Time

Subtasks:
- Poll `GET network` (or reservation status endpoint) to refresh remaining time.
- Show remaining seconds in all states (active/off).
- Keep display consistent with backend `expires_at` and `expires_in`.

Test logic to add:
- Polling test: countdown updates over time.
- Off-state test: remaining time still displayed when network is off.
- Drift test: frontend countdown remains aligned with server values.

### Task 5 - Add Reservation Progress Bar with hh:mm:ss Label

Subtasks:
- Implement progress from 100% to 0% over reservation lifetime.
- Render formatted `hh:mm:ss` inside progress bar.
- Clamp at 0% when expired.

Test logic to add:
- Progress computation test: percentage decreases linearly with `expires_in`.
- Formatting test: `hh:mm:ss` formatting for multi-hour and sub-minute cases.
- Expiry boundary test: exactly at 0 seconds bar shows `00:00:00` and 0%.

### Task 6 - Error UX for No Available Devices

Subtasks:
- Show backend 4xx full-capacity message.
- Surface “next available in” hint in UI.
- Allow retry from same dialog/view.

Test logic to add:
- Full-capacity response test: UI displays ETA message.
- Retry test: new reservation attempt works once capacity returns.
- Accessibility test: error is visible and readable in keyboard flow.

---

## API Contract Sketch (Proposed)

### POST /api/v1/device-reservation
Request:
```json
{
  "duration_seconds": 3600
}
```

Success:
```json
{
  "reservation_id": "rsv_7f4a2c91",
  "device_id": "wls16",
  "expires_at": "2026-03-26T15:00:00Z",
  "expires_in": 3600
}
```

All devices reserved (4xx example):
```json
{
  "detail": "No device available",
  "next_available_at": "2026-03-26T14:22:04Z",
  "next_available_in": 124
}
```

### GET /api/v1/device-reservation/{reservation_id}
Success:
```json
{
  "reservation_id": "rsv_7f4a2c91",
  "device_id": "wls16",
  "state": "reserved",
  "expires_at": "2026-03-26T15:00:00Z",
  "expires_in": 3510
}
```

### DELETE /api/v1/device-reservation/{reservation_id}
Success:
```json
{
  "detail": "Reservation released"
}
```

---

## Acceptance Criteria

- Config no longer requires or supports static operational `net_id`.
- Reservation is mandatory before network operations.
- Random reservation token is the only client key for reserved operations.
- Token invalidation works on release and timeout expiry.
- Full-capacity reservation returns 4xx with nearest ETA.
- Reservation timeout is the only network lifetime timer.
- Status and Get Network always expose reservation remaining time.
- Frontend starts with reservation-only UX and then renders card post-reservation.
- Frontend shows always-on remaining time and progress bar with `hh:mm:ss`.
