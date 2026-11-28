# Feature: Wi-Lab Backend in Docker

**Priority:** 10 (not now)  
**Status:** ANALYZED (2026-11-28)  
**Estimated Effort:** ~3 days  

## Description

Run the Wi-Lab service in a container. Possible for about 80-90% of Wi-Lab, but
only as a privileged container in the host's network namespace: Wi-Lab drives the
host's Wi-Fi adapters, firewall, routing and USB ports. The gain is packaging
(pinned hostapd, dnsmasq, iptables, Python; one install everywhere; a patched
hostapd without building on the host), not isolation.

## Part 1: What the Container Needs

- `network_mode: host`; `NET_ADMIN`, `NET_RAW`, in practice `privileged: true`.
- `/sys` read-write (discovery, USB `authorized`, mt76 debugfs), `/dev/bus/usb` (`usbreset`).
- `/run/reboot-required` read-only; `config.yaml` from the host.

| Part of Wi-Lab | In the container | Notes |
|---|---|---|
| API, reservations, watchdog, discovery | yes | |
| hostapd, dnsmasq | yes, a gain | Pinned versions; a patched hostapd ([hostapd-segfault-fix.md](../reliability/hostapd-segfault-fix.md)) |
| iptables, `tc` | yes | Same iptables backend as the host (nft or legacy) |
| `iw reg set`, capabilities, captive portal | yes | |
| USB reset | yes | `/dev/bus/usb`, writable `/sys` |
| Driver reload (`modprobe`) | no | Host script |
| networkd exclusion, NetworkManager and wpa_supplicant checks | no | Host installer |
| systemd watchdog (restart only when idle) | to redo | Health check plus restart policy, same idle rule |
| Journal priorities | partly | `journald` log driver; check the `<N>` prefixes |
| `restart_required` | changes meaning | Image libraries: "pull a new image"; host reboot from the mounted file |

## Part 2: Implementation Tasks

- [ ] Image (Ubuntu base, same packages as the installer) and a compose file with the mounts above
- [ ] Split the installer: host preparation (networkd, NetworkManager, wpa_supplicant, modules) and the Wi-Lab service (systemd unit or compose)
- [ ] Unauthenticated liveness endpoint for the health check (`/status` needs the token)
- [ ] Health check plus `restart: unless-stopped`, keeping the restart-only-when-idle rule
- [ ] Container as an alternative first; the only install only after a long run passes

## Testing

- [ ] Unit tests in the image; e2e and long run against the container on the lab machine

## Benefits

- **Portability:** The same Wi-Lab on any host prepared by the installer
- **Reproducibility:** Pinned system tools, no surprises from distribution updates

## Breaking Changes

- None while it is an alternative to the systemd service

## Success Criteria

- ✅ The same test results with the container as with the systemd service
- ✅ A prepared host runs Wi-Lab with one compose file
