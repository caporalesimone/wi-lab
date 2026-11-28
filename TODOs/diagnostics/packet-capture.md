# Feature: Packet Capture Download

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Capture the traffic of a network and download it as a pcap file for Wireshark.

## Implementation Tasks

- [ ] `POST /access-point/{reservation_id}/capture` with a duration or size limit; `GET .../capture` for its state; `GET .../capture/{capture_id}.pcap` downloads the file; `DELETE .../capture` stops it early
- [ ] `tcpdump` on the AP interface, with an optional filter (host, port)
- [ ] Limits: one capture per network, maximum size, removed at the end of the reservation

## API Proposal

### `POST /api/v2/access-point/{reservation_id}/capture`

Start a capture on the access point interface.

Request:

```json
{
  "duration_seconds": 60,
  "max_megabytes": 50,
  "filter": "port 53 or port 67"
}
```

Response `201`:

```json
{
  "capture_id": "c-1",
  "state": "running",
  "ends_at": "2026-11-28T10:01:00Z"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `409 / 1019 capture_running` (new code) when one is already running; `422 validation_error` with the field path (invalid filter).

### `GET /api/v2/access-point/{reservation_id}/capture`

State of the capture.

Request: no body.

Response `200`:

```json
{
  "capture_id": "c-1",
  "state": "done",
  "size_bytes": 1830400,
  "packets": 5210,
  "download_url": "/api/v2/access-point/{reservation_id}/capture/c-1.pcap"
}
```

### `GET /api/v2/access-point/{reservation_id}/capture/{capture_id}.pcap`

Download the file.

Request: no body.

Response `200`: no body.

Response `200`: `application/vnd.tcpdump.pcap`. Removed when the reservation ends.

### `DELETE /api/v2/access-point/{reservation_id}/capture`

Stop a running capture early (the file stays downloadable).

Request: no body.

Response `200`:

```json
{
  "capture_id": "c-1",
  "state": "done"
}
```

## Testing

- [ ] Unit tests for the limits and the cleanup
- [ ] Real radio: a capture contains the phone's DHCP and DNS traffic

## Benefits

- **Diagnosis:** Protocol-level analysis of client problems

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ A capture can be started, downloaded and is removed at the end
