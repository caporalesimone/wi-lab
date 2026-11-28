# Feature: Webhooks

**Priority:** 7  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Call external URLs when events happen (reservation ended, client connected,
access point failed), for CI systems and chat notifications.

## Implementation Tasks

- [ ] Webhooks configured in `config.yaml` or per reservation: URL, event types, secret
- [ ] Signed payloads (HMAC header), retries with backoff, timeout
- [ ] Built on the event stream ([event-stream.md](event-stream.md))

## Testing

- [ ] Unit tests for signing, retries and filtering with a fake receiver

## Benefits

- **Integration:** CI and notification systems without polling

## Breaking Changes

- None (new option)

## Success Criteria

- ✅ Subscribed events reach the receiver, signed, with retries
