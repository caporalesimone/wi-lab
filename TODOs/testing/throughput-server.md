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

## Testing

- [ ] Unit tests for the process lifecycle and the host guard rule
- [ ] Real radio: a phone measures throughput against the gateway

## Benefits

- **Measurement:** Wi-Fi throughput without the Internet line

## Breaking Changes

- None (optional field)

## Success Criteria

- ✅ Clients reach the server and nothing else on the host
