# Feature: WPA2/WPA3-Enterprise (802.1X)

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~2 days  

## Description

Networks where every user logs in with personal credentials checked by an
authentication server, as in companies: WPA2-Enterprise and WPA3-Enterprise
(802.1X). Today Wi-Lab offers only shared-password and open networks.

## Part 1: Authentication Server and Certificates

### Implementation Tasks
- [ ] Use hostapd's internal EAP server (`eap_server=1`, `eap_user_file`): no extra service. FreeRADIUS only if per-user VLANs or accounting are needed later
- [ ] Installer: create a lab CA and a server certificate (e.g. `radius.wilab.lan`) in `/etc/wilab/pki`, root only
- [ ] `GET /api/v2/pki/ca.pem` to download the CA certificate, so clients can validate the server (recent Android requires a CA and a domain)
- [ ] Optional: `POST /api/v2/pki/client-certificates` generates client certificates for EAP-TLS tests; the private key is returned once

## Part 2: API

### Implementation Tasks
- [ ] Encryptions `wpa2-enterprise` (`wpa_key_mgmt=WPA-EAP`, `ieee8021x=1`) and `wpa3-enterprise` (`WPA-EAP-SHA256`, `ieee80211w=2`)
- [ ] `wifi.security.eap`: allowed methods (`peap`, `ttls`, `tls`) and users (`{identity, password}`) or accepted client certificates
- [ ] Never log passwords or private keys; decide whether `GET /access-point` returns the user list
- [ ] Refusal reasons (wrong password, unknown user, untrusted or expired certificate) in the client events ([client-events.md](../../events/client-events.md))
- [ ] 192-bit mode only if the MT7921U supports GCMP-256

## API Proposal

### `POST /api/v2/access-point/{reservation_id}`

New optional fields in the create body (only the changed section is shown; omitted fields keep today's behaviour).

Request:

```json
{
  "wifi": {
    "ssid": "lab-corp",
    "security": {
      "encryption": "wpa2-enterprise",
      "eap": {
        "methods": [
          "peap",
          "ttls"
        ],
        "users": [
          {
            "identity": "alice",
            "password": "s3cret!"
          },
          {
            "identity": "bob",
            "password": "pa55word"
          }
        ],
        "client_certificates": []
      }
    }
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
  "wifi": {
    "ssid": "lab-corp",
    "security": {
      "encryption": "wpa2-enterprise",
      "server_certificate": {
        "subject": "CN=radius.wilab.lan",
        "not_after": "2028-11-28T00:00:00Z"
      },
      "eap": {
        "methods": [
          "peap",
          "ttls"
        ],
        "users": [
          "alice",
          "bob"
        ]
      }
    }
  }
}
```

Passwords are never returned. `encryption`: `wpa2-enterprise` or `wpa3-enterprise`; `methods`: `peap`, `ttls`, `tls`.

### `GET /api/v2/pki/ca.pem`

The lab CA certificate (PEM), to install on clients so they validate the server.

Request: no body.

Response `200`: no body.

Response `200`: `Content-Type: application/x-pem-file`, the certificate. No token needed: it is public.

### `POST /api/v2/pki/client-certificates`

Create a client certificate for EAP-TLS tests; the private key is returned once.

Request:

```json
{
  "identity": "device-01",
  "days": 7
}
```

Response `201`:

```json
{
  "identity": "device-01",
  "certificate_pem": "-----BEGIN CERTIFICATE-----...",
  "private_key_pem": "-----BEGIN PRIVATE KEY-----...",
  "not_after": "2026-12-05T00:00:00Z"
}
```

Errors: `422 validation_error` with the field path.

## Testing

- [ ] Unit tests for the hostapd and EAP user configuration
- [ ] Validation tests (methods, users, encryption combinations)
- [ ] Real radio: PEAP with user and password, EAP-TLS with a client certificate, wrong password refused

## Benefits

- **Coverage:** Company devices and their 802.1X settings
- **Negative tests:** Wrong credentials, wrong CA, wrong domain, expired or revoked certificates

## Breaking Changes

- None (new encryptions)

## Success Criteria

- ✅ A phone connects with PEAP and with EAP-TLS
- ✅ Wrong credentials are refused and the reason is visible in the API
- ✅ No secret appears in the journal
