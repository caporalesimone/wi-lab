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
- [ ] Endpoint to download the CA certificate, so clients can validate the server (recent Android requires a CA and a domain)
- [ ] Optional: generate client certificates for EAP-TLS tests, downloadable once

## Part 2: API

### Implementation Tasks
- [ ] Encryptions `wpa2-enterprise` (`wpa_key_mgmt=WPA-EAP`, `ieee8021x=1`) and `wpa3-enterprise` (`WPA-EAP-SHA256`, `ieee80211w=2`)
- [ ] `wifi.security.eap`: allowed methods (`peap`, `ttls`, `tls`) and users (`{identity, password}`) or accepted client certificates
- [ ] Never log passwords or private keys; decide whether `GET /access-point` returns the user list
- [ ] Refusal reasons (wrong password, unknown user, untrusted or expired certificate) in the client events ([client-events.md](../../events/client-events.md))
- [ ] 192-bit mode only if the MT7921U supports GCMP-256

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
