# Feature: Wi-Lab backend in Docker, and enterprise foundations

**Priority:** 10 (not now)
**Status:** ANALYZED (2026-11-28)

Regulatory domains are done: `country_code` in `config.yaml`, applied with
`iw reg set` at startup; the channels offered follow the country. Multi-SSID and
WPA-Enterprise / RADIUS are in [ap-improvements.md](ap-improvements.md) (items 2
and 19). The web frontend container is a separate plan:
[todo-frontend.md](todo-frontend.md).

## Part 1: The backend in a container

### Verdict

Possible for about 80-90% of Wi-Lab, but only as a **privileged container in the
host's network namespace**. Wi-Lab does not own isolated resources: it drives the
host's Wi-Fi adapters, firewall, routing and USB ports. The gain is packaging
(pinned hostapd, dnsmasq, iptables and Python; the same install everywhere), not
isolation: such a container can do almost anything root can do on the host.

Not now: the test bench features in [testbench-features.md](testbench-features.md)
and the network settings in [ap-improvements.md](ap-improvements.md) are worth
more. It becomes interesting when Wi-Lab must be installed on several machines or
distributions, or to ship a fixed hostapd (see [crash-hostapd.md](crash-hostapd.md))
without building it on the host.

### What the container needs

- `network_mode: host`: the `wlx...` interfaces, the host's iptables rules,
  `ip_forward`.
- `NET_ADMIN` and `NET_RAW`, in practice `privileged: true`: hostapd, `iw`,
  iptables, `tc`, IFB devices.
- `/sys` read-write (radio discovery, USB `authorized`, mt76 debugfs under
  `/sys/kernel/debug`) and `/dev/bus/usb` (`usbreset`).
- `/run/reboot-required` (read-only) for the host reboot check.
- `config.yaml` mounted from the host; runtime directories (`/run/wilab`) inside
  the container.

### Component by component

| Part of Wi-Lab | In the container | Notes |
|---|---|---|
| API, reservations, watchdog, discovery | yes | Host network and `/sys` mounted |
| hostapd, dnsmasq | yes, a gain | Pinned versions in the image; a patched hostapd without building on the host |
| iptables (NAT, isolation, host guard), `tc` for QoS | yes | The rules live in the host; startup cleanup still works. The container's iptables must use the same backend as the host (nft or legacy), or the two see different rule sets |
| `iw reg set`, radio capabilities, captive portal | yes | |
| USB reset of the antennas | yes | `/dev/bus/usb` and writable `/sys` |
| Driver reload (`--reload-drivers`, `modprobe`) | no | Needs the host's kernel modules and `SYS_MODULE`: stays a host script |
| Radios excluded from systemd-networkd, NetworkManager and wpa_supplicant checks | no | Host configuration: stays in the host installer |
| systemd watchdog (`Type=notify`, self-restart only when idle) | to redo | Docker health check plus `restart: unless-stopped`, keeping the rule "restart only with no valid reservation and no USB recovery" |
| Journal with priorities (`journalctl -u wi-lab -p err`) | partly | Docker's `journald` log driver keeps the journal; check that the `<N>` priority prefixes survive |
| `restart_required` (security updates) | changes meaning | Replaced libraries are the image's: it becomes "pull a new image"; the host reboot comes from the mounted `/run/reboot-required` |
| Installer, `make start/stop` | to redo | Compose instead of the systemd unit; the installer keeps the host steps |

### Plan (when it is time)

1. **Container as an alternative.** An image (Ubuntu base, same packages as the
   installer), a compose file for the host, and the installer split in "host
   preparation" (networkd, NetworkManager, wpa_supplicant, modules, sudo-free
   commands) and "Wi-Lab service" (systemd unit or compose).
2. Replace the systemd watchdog with a health check that keeps the
   restart-only-when-idle rule; check journal priorities through Docker.
3. Run the unit tests in the image and the e2e and long-run tests against the
   container on the lab machine.
4. **Container as the only install** only after a long run passes.

### Compose sketch

```yaml
services:
  wilab:
    image: ghcr.io/caporalesimone/wi-lab:<version>
    network_mode: host
    privileged: true
    restart: unless-stopped
    volumes:
      - /etc/wilab/config.yaml:/app/config.yaml:ro
      - /sys:/sys
      - /dev/bus/usb:/dev/bus/usb
      - /run/reboot-required:/run/reboot-required:ro
    logging:
      driver: journald
    healthcheck:
      test: ["CMD", "curl", "-fs", "http://127.0.0.1:8080/api/v2/status", "-o", "/dev/null", "-w", "%{http_code}"]
```

(`/api/v2/status` needs the token: the health check needs an unauthenticated
liveness endpoint, or the token from a secret.)

### Success criteria

- The same unit, e2e and long-run results with the container as with the
  systemd service.
- A host prepared by the installer runs the container with one compose file.
- Driver reload and host preparation stay documented host steps.

## Part 2: Other enterprise foundations (planning)

- [ ] **Persistent state.** Reservations and running networks are in memory
  and are lost on restart. Options: a JSON file, SQLite. Decide what must survive
  (reservations? networks restored after a restart?).
- [ ] **Scale and deployment.** How many antennas per host before CPU or USB
  limits (see the infrastructure notes in [testbench-features.md](testbench-features.md#infrastructure));
  several hosts behind one frontend.
