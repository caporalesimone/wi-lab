# Feature: Device Busy Tag & WiFi Network Reservation

## Overview

Implement logical network reservation system that marks WiFi networks as exclusively busy during active usage or testing sessions. Once reserved, a network cannot be modified or re-initialized until the reservation expires.

## Purpose

Allow users to reserve a WiFi network for a specific duration, preventing accidental modifications or concurrent access conflicts. The system uses a timer-based approach that automatically releases the network once the reservation timeout expires.

---

## Device Busy Tag Structure

The Device Busy Tag consists of two primary pieces of information:

- **`is_busy`** (Boolean): Indicates whether the network is currently reserved/busy
- **`available_at`** (Timestamp): When the network will become available again
  - Unix epoch timestamp (numeric)
  - Human-readable format (ISO 8601)

### Timeout Behavior

1. **Reservation Timer**: When a user requests a network reservation, a timer is set for the requested duration
2. **Expiration Logic**:
   - If network is deactivated before timer expires: Network becomes free immediately when timer expires
   - If network remains active: Network is automatically released when timer expires
3. **Timer State**: The timer runs independently and is persisted across API calls

---

## Frontend Implementation

### UI Components

- [ ] **Device Busy Badge**: Visual indicator showing network reservation status
  - Display near network name/status
  - Color-coded: Green (available) / Red (busy)
  
- [ ] **Countdown Timer**: Real-time countdown display
  - Shows remaining time in MM:SS format
  - Updates every second during active reservation
  - Hides when network is available

- [ ] **Reserve Button**: New action button in network control panel
  - Opens modal/dialog for reservation
  - Input field for duration (minutes)
  - Validation: Prevent invalid durations (0, negative, excessive values)
  - Disabled during ongoing reservation

### Reservation Dialog

- [ ] Duration input field with validation
- [ ] Confirm/Cancel buttons
- [ ] Display current network status
- [ ] Show estimated release time in human-readable format

### Status Display

- [ ] Update network status card to show Device Busy Tag information
- [ ] Integrate countdown into existing status display
- [ ] Show "Reserved until: HH:MM:SS on YYYY-MM-DD" format

---

## API Implementation

### Reservation Endpoint

**POST** `/api/networks/{network_name}/reserve`

Request Body:
```json
{
  "duration_seconds": 3600
}
```

Response:
```json
{
  "success": true,
  "network_name": "wifi-network-1",
  "reserved_until": "2026-01-29T14:30:45Z",
  "available_at_epoch": 1743397845
}
```

Error Cases:
- [ ] Network already busy: Return 409 Conflict
- [ ] Invalid duration: Return 400 Bad Request
- [ ] Network not found: Return 404 Not Found

### Network Status Endpoints

Update existing status endpoints to include Device Busy Tag:

**GET** `/api/networks/{network_name}/status`
**GET** `/api/networks/status` (all networks)

Add to response:
```json
{
  "network_name": "wifi-network-1",
  "status": "active",
  "device_busy_status": {
    "is_busy": true,
    "available_at": "2026-01-29T14:30:45Z",
    "available_at_epoch": 1743397845
  },
  ...
}
```

### Release Endpoint (Optional for v1.4.0)

**POST** `/api/networks/{network_name}/release`

Allows early manual release of reservation:
```json
{
  "success": true,
  "released_at": "2026-01-29T13:45:00Z"
}
```

---

## Backend Implementation

### Database/State Storage

- [ ] Add `device_busy_tag` field to network state persistence
- [ ] Store: `is_busy` (boolean), `available_at` (epoch timestamp)
- [ ] Implement timer mechanism for automatic expiration

### Timer Management

- [ ] Create background task to check expiration timers
- [ ] Update network state when timer expires
- [ ] Handle edge cases:
  - [ ] Server restart with active timers
  - [ ] Network deactivation during reservation
  - [ ] Concurrent reservation requests

### Validation & Safety

- [ ] Prevent operations on busy networks (modify, reinit, etc.)
- [ ] Duration limits: Min 60 seconds, Max 24 hours
- [ ] Return descriptive error when operation blocked due to busy state

---

## Testing

### Unit Tests

- [ ] Test reservation creation with valid durations
- [ ] Test error handling for invalid durations
- [ ] Test timer expiration logic
- [ ] Test network state updates after expiration

### Integration Tests

- [ ] Reservation through API endpoint
- [ ] Status endpoint returns correct Device Busy Tag info
- [ ] Timer countdown accuracy
- [ ] Early release functionality (if implemented)
- [ ] Network operations blocked during reservation
- [ ] State persistence across server restart

### Frontend Tests

- [ ] Countdown timer updates correctly
- [ ] Reservation dialog validates input
- [ ] UI reflects busy state appropriately
- [ ] Badge displays during and after reservation

---

## Documentation

- [ ] Update API documentation with new endpoints
- [ ] Add reservation flow to user guide
- [ ] Document timeout behavior and edge cases
- [ ] Provide example use cases

---

## Acceptance Criteria

- ✅ Network can be reserved via API with specified duration
- ✅ Device Busy Tag shows correct status and countdown
- ✅ Frontend displays countdown timer and reserve button
- ✅ Reservation automatically expires after timeout
- ✅ Network state reflects busy status in all endpoints
- ✅ Operations blocked on busy networks with appropriate error messages
- ✅ All tests pass (unit, integration, frontend)
- ✅ API documentation updated

---

## 🔶 To Be Confirmed

### Frontend Enhancements (TBD)

#### Active Reservations Status Panel
- [ ] Display all active network reservations in a dedicated UI panel
- [ ] Show real-time countdown timer for each reservation
- [ ] Add visual progress bar showing reservation time remaining
  - Linear progress bar: 0-100% representing elapsed time
  - Color transition: Green → Yellow → Red as time runs out
- [ ] Allow sorting/filtering of active reservations

#### Reservation History Log (TBD)
- [ ] Display log of recent reservations (in-memory, no DB persistence)
  - Network name
  - Reservation duration (requested vs actual)
  - Start time and end time
  - Status (Active / Expired / Released)
- [ ] Configurable log size (e.g., last 50 reservations)
- [ ] Clear history option
- [ ] **Decision needed:** Persistence scope
  - Current proposal: In-memory only (cleared on service restart)
  - Alternative: Session-based persistence
  - Alternative: Full database persistence

### Security Enhancement (TBD)

#### Reservation Code / Token System
- [ ] Reservation endpoint returns a random security code/token
  - Format: Random alphanumeric string (e.g., 12-16 chars)
  - Example: `aBcD9eF2gH1jKl3m`
- [ ] All subsequent API calls on the reserved device MUST include this code
  - Add `Authorization` header or query parameter: `reservation_code`
  - Example: `POST /api/networks/wifi-1/activate?reservation_code=aBcD9eF2gH1jKl3m`
- [ ] Prevent operations without valid code during active reservation
  - Return 403 Forbidden with message: "Reservation code required or invalid"
- [ ] Code expires when reservation expires or is manually released

#### Benefits
- Prevents accidental/unauthorized modifications during active reservation
- Ensures only the entity that made the reservation can operate on it
- Defense-in-depth security layer
- Useful in multi-user or automated testing scenarios

#### Implementation Considerations
- [ ] Include code in all network operation endpoints
- [ ] Validate code on every request targeting busy network
- [ ] Log all requests with/without valid code
- [ ] Clear code when reservation expires

---

## Implementation Notes

- This v1.4.0 implementation focuses on core reservation logic
- Future versions may add:
  - Reservation priority queue
  - Reservation history/audit log
  - Reservation conflicts detection
  - Reservation extension API
  - User-specific reservations with auth
