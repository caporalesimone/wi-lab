# Feature: Throughput Server on the Gateway

**Priority:** 4  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

A speed test server on the gateway of each network (iperf3, or a LibreSpeed web
page), so clients measure the Wi-Fi link without the Internet line in between.

## Context

On 2026-11-27 a phone measured about 60 Mbit/s with an Internet speed test; the
VM, not the radio, was the limit ([vm-performance.md](../infrastructure/vm-performance.md)).
A local server separates the Wi-Fi link from the rest of the path.

## Implementation Tasks

- [ ] Optional create field `throughput_server` (default false)
- [ ] Start `iperf3 -s -B <gateway>` (and/or a LibreSpeed page) for the network; stop it with the network
- [ ] Open only that port in the host guard, only on that interface
- [ ] Show the address in `GET /access-point/{reservation_id}`

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "throughput_server": {
    "enabled": true,
    "kinds": [
      "iperf3",
      "web"
    ]
  }
}
```

Response `202`:

```json
{
  "runtime_state": "starting",
  "active": false
}
```

Errors: `422` with the field path for an invalid value.

### `GET /api/v2/access-point/{reservation_id}`

The values in use, in the same section of the answer.

Request: no body.

Response `200`:

```json
{
  "throughput_server": {
    "enabled": true,
    "iperf3": "192.168.120.1:5201",
    "web": "http://192.168.120.1:8082/"
  }
}
```

## Testing

- [ ] Unit tests for the process lifecycle and the host guard rule
- [ ] Real radio: a phone measures throughput against the gateway

## Benefits

- **Measurement:** Wi-Fi throughput without the Internet line

## Breaking Changes

- None (optional field)

## Success Criteria

- ✅ Clients reach the server and nothing else on the host
