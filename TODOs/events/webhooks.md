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

## API Proposal

### `POST /api/v2/webhooks`

Subscribe a URL to events.

Request:

```json
{
  "url": "https://ci.example/wilab-hook",
  "events": [
    "reservation.expired",
    "access_point.start_failed"
  ],
  "reservation": null,
  "secret": "hook-secret"
}
```

Response `201`:

```json
{
  "webhook_id": "w-3",
  "url": "https://ci.example/wilab-hook",
  "events": [
    "reservation.expired",
    "access_point.start_failed"
  ],
  "reservation": null
}
```

Errors: `422 validation_error` with the field path (`url: must be http or https`).

### `GET /api/v2/webhooks`

The subscriptions (the secret is never returned).

Request: no body.

Response `200`:

```json
[
  {
    "webhook_id": "w-3",
    "url": "https://ci.example/wilab-hook",
    "events": [
      "reservation.expired"
    ],
    "last_delivery": {
      "time": "2026-11-28T10:00:00Z",
      "status": 200
    }
  }
]
```

### `DELETE /api/v2/webhooks/{webhook_id}`

Remove a subscription.

Request: no body.

Response `200`:

```json
{
  "detail": "Webhook w-3 removed"
}
```

Delivery: `POST` to the URL with the event JSON of [event-stream.md](event-stream.md) and the header `X-Wilab-Signature: sha256=<HMAC of the body with the secret>`; retried with backoff on errors.

## Testing

- [ ] Unit tests for signing, retries and filtering with a fake receiver

## Benefits

- **Integration:** CI and notification systems without polling

## Breaking Changes

- None (new option)

## Success Criteria

- ✅ Subscribed events reach the receiver, signed, with retries
