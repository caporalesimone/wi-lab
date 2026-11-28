# Feature: Management Frame Capture with the Spare Antenna

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Put a free antenna in monitor mode on the channel of a running network and
capture its 802.11 management frames (beacons, probes, authentication,
association requests and responses), to see what a client asks for and why the
AP refuses it.

## Context

On 2026-11-27 a manual scan with the spare antenna showed what the AP announced
(Wi-Fi 6 capabilities, `BSS Color Disabled`, the HE membership selector). A
capture of the phone's association request would have shown directly whether it
offered Wi-Fi 6.

## Implementation Tasks

- [ ] Use an antenna that is not reserved; refuse if none is free
- [ ] Monitor interface on the AP's channel and width; `tcpdump` with a management frame filter
- [ ] Download as pcap; decoded summary of association requests (capabilities offered: HT, VHT, HE) in the API
- [ ] Restore the antenna to managed and down at the end

## API Proposal

### `POST /api/v2/access-point/{reservation_id}/monitor`

Capture the management frames of the access point's channel with a free antenna.

Request:

```json
{
  "duration_seconds": 60,
  "frames": [
    "probe",
    "auth",
    "assoc"
  ],
  "client": "aa:bb:cc:dd:ee:ff"
}
```

Response `201`:

```json
{
  "monitor_id": "m-1",
  "antenna": "wlx7419f817651c",
  "channel": 36,
  "state": "running"
}
```

Errors: `409 / 1007 access_point_not_active` without a running access point; `503 / 1003 device_unavailable` when no antenna is free for monitoring.

### `GET /api/v2/access-point/{reservation_id}/monitor`

State and decoded association requests.

Request: no body.

Response `200`:

```json
{
  "monitor_id": "m-1",
  "state": "done",
  "download_url": "/api/v2/access-point/{reservation_id}/monitor/m-1.pcap",
  "association_requests": [
    {
      "time": "2026-11-28T10:00:12Z",
      "mac": "aa:bb:cc:dd:ee:ff",
      "offered": {
        "ht": true,
        "vht": true,
        "he": false,
        "max_nss": 2
      },
      "response_status": 124
    }
  ]
}
```

## Testing

- [ ] Unit tests for the setup and the restore
- [ ] Real radio: the association request of a phone shows its capabilities

## Benefits

- **Diagnosis:** Client capabilities and refusal reasons straight from the air

## Breaking Changes

- None (new endpoints)

## Success Criteria

- ✅ Association requests of a client are captured and decoded
- ✅ The antenna is back in the pool afterwards
