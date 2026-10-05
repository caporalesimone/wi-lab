# Wi-Lab Networking Guide

## Overview

Wi-Lab manages WiFi Access Points by directly controlling network settings on the host system. This document explains how Wi-Lab modifies the network, potential risks, and how to diagnose and recover from issues.

---

## System Modifications

### 1. IP Forwarding

**What:** Enables `net.ipv4.ip_forward=1` globally  
**When:** When NAT is enabled for a WiFi network  
**Impact:** Allows routing between interfaces (required for Internet access)  
**Reversible:** Yes - disabled when all networks are stopped

### 2. NAT Rules (iptables)

**What:** Adds MASQUERADE rule in NAT table  
**When:** Network created with Internet access enabled  
**Impact:** WiFi clients can reach external networks via upstream interface  
**Reversible:** Yes - removed when network stops

```bash
# Example NAT rule
iptables -t nat -A POSTROUTING -s 192.168.120.0/24 -o eth0 -j MASQUERADE
```

### 3. FORWARD Rules (iptables)

**What:** ACCEPT/DROP rules in FORWARD chain  
**When:** When WiFi networks are created  
**Impact:** Controls traffic routing between interfaces  
**Reversible:** Yes - removed when networks stop

### 4. WiFi Interface State

**What:** Interface switched to AP mode  
**When:** Network is created  
**Impact:** Interface unavailable for other applications (e.g., NetworkManager)  
**Reversible:** Yes - restored to managed mode when network stops

---

## Safety Protections

### Subnet Isolation

Each WiFi network operates on an isolated subnet:
- First network: `192.168.120.0/24`
- Second network: `192.168.121.0/24`
- Third network: `192.168.122.0/24`

Clients on one network **cannot** communicate with clients on other networks by default (via iptables isolation rules).

### Specific Rule Application

All iptables rules use specific source/destination filters to prevent affecting unrelated traffic:

```bash
# Correctly scoped NAT rule
iptables -t nat -A POSTROUTING -s 192.168.120.0/24 -o ens18 -j MASQUERADE

# NOT a global MASQUERADE (which would be dangerous)
```

### SSH Protection Considerations

When network isolation is enabled, Wi-Lab adds rules to explicitly protect SSH connections. However, isolation is **currently disabled** to prevent unintended networking issues during development.

---

## ⚠️ CRITICAL: Subnet Conflicts

### The Problem

If your **host network** uses the same subnet as the WiFi network, it creates a routing conflict that can **completely block host networking**, including SSH access.

**Example conflict:**
- Host IP: `192.168.10.113` (subnet: `192.168.10.0/24`)
- WiFi configured: `192.168.10.0/24` ❌ **CONFLICT!**

### Symptoms

- WiFi network creation causes immediate SSH disconnection
- Host loses all network connectivity
- System requires physical reboot or console access to recover

### Solution

**Use a different subnet for WiFi:**

```yaml
# In config.yaml

# Step 1: Check your host subnet
# $ ip addr show | grep "inet "
# Example: inet 192.168.10.113/24

# Step 2: Use a different subnet for WiFi
# ✅ CORRECT
dhcp_base_network: "192.168.120.0/24"

# ❌ WRONG (if host is on 192.168.10.x)
dhcp_base_network: "192.168.10.0/24"
```

### Automatic Detection

Since 4.0.0 this conflict is **detected before anything is started**. The configuration
validator computes the `/24` it would allocate to each managed device — sequential from
`dhcp_base_network`, one per device — and compares every one of them against the host's
own routing table (`ip route`):

```bash
python3 main.py --validate-config --check-hardware
```

```
ERROR   dhcp_base_network
        Planned WiFi subnet 192.168.10.0/24 overlaps the existing host route 192.168.10.0/24.
        -> A collision breaks host networking and can drop your SSH session. Pick a range your host does not route.
```

This check runs automatically every time the service starts, so a collision now stops the
service with a readable report instead of taking the host's networking down with it. It
is part of the **hardware phase**, which means:

- It needs the real machine, so it is skipped by a plain `--validate-config` — that form
  stays usable on a laptop or in CI where there is no meaningful route table.
- It checks **all** planned subnets, not just the base one. A base of `192.168.9.0/24`
  with three devices allocates `.9`, `.10` and `.11`, and a host on `192.168.10.x` is
  still a conflict.
- If `ip route` cannot be read the check stays silent rather than guessing: an unreadable
  route table is not a configuration error.

The manual check above is still worth doing when planning a deployment — the validator
tells you that a range collides, not which range to pick instead.

---

## Diagnostics and Monitoring

### Check WiFi Interface Status

```bash
# List WiFi interfaces
iw dev

# Check current mode (should be "managed" when not in use)
iw dev wlx782051245264 link

# Check TX power capabilities
iw dev wlx782051245264 info | grep -i "tx power"
```

### Check iptables Rules

```bash
# View FORWARD chain (routing rules)
sudo iptables -L FORWARD -n -v -x

# View NAT table (Internet access rules)
sudo iptables -t nat -L POSTROUTING -n -v -x

# Check IP forwarding status
cat /proc/sys/net/ipv4/ip_forward
# Output: 1 (enabled) or 0 (disabled)
```

### Check Active Networks

```bash
# Use Swagger UI to inspect active networks and interface state:
# http://localhost:8080/docs

# Check hostapd processes
ps aux | grep "[h]ostapd"

# Check dnsmasq processes
ps aux | grep "[d]nsmasq"
```

### View Service Logs

```bash
# Real-time logs
sudo journalctl -u wi-lab.service -f

# Last 50 lines
sudo journalctl -u wi-lab.service -n 50

# Since last boot
sudo journalctl -u wi-lab.service -b

# Errors only
sudo journalctl -u wi-lab.service | grep -i "error\|critical"

# Last hour
sudo journalctl -u wi-lab.service --since "1 hour ago"
```

---

## Troubleshooting Reference

Operational troubleshooting is maintained in [troubleshooting.md](troubleshooting.md).

Use that document for:
- service startup failures
- network creation/client connectivity failures
- SSH loss and emergency recovery procedures
- TX power and performance diagnostics

---

## Best Practices

### Pre-Deployment Testing

1. **Verify host subnet:** `ip addr show | grep "inet "`
2. **Choose non-conflicting WiFi subnet:** e.g., `192.168.120.0/24`
3. **Test network creation/deletion:** Verify SSH remains accessible
4. **Test client connectivity:** Connect device, verify IP assignment
5. **Monitor logs:** Check for errors: `sudo journalctl -u wi-lab.service -f`

### Ongoing Monitoring

```bash
# Monitor WiFi processes
watch -n 2 'ps aux | grep -E "[h]ostapd|[d]nsmasq"'

# Monitor iptables changes
watch -n 2 'sudo iptables -L FORWARD -n | tail -10'

# Monitor service health
watch -n 5 'sudo systemctl status wi-lab.service'
```

### Configuration Backup

```bash
# Backup current iptables state BEFORE running Wi-Lab
sudo iptables-save > ~/.iptables-backup-pre-wilab.rules

# If needed, restore
sudo iptables-restore < ~/.iptables-backup-pre-wilab.rules

# Backup config and service file
cp config.yaml config.yaml.backup
sudo cp /etc/systemd/system/wi-lab.service /etc/systemd/system/wi-lab.service.backup
```

### Device Capabilities and Bands

Each managed device declares in `config.yaml` which bands it may be used for:

```yaml
networks:
  - interface: "wlxbc071dc527d6"
    display_name: "bench-antenna-1"
    capabilities:
      "2.4ghz": true
      "5ghz": false
```

**This is a declaration, never a probe.** Wi-Lab does not query the driver, does not run
`iw phy channels`, and never edits `config.yaml` to fill anything in. The values are an
administrative statement of what the adapter *may* be used for on this bench, which is not
the same thing as what its silicon can do — declaring `"5ghz": false` on a dual-band
adapter to reserve that band for another bench is a legitimate and supported choice. A
missing key is an error, not a silent `false`, and a device with no enabled band is
rejected because it could never host an access point.

**How this relates to `band` at AP creation.** The two use the same vocabulary
(`2.4ghz`, `5ghz`) deliberately, so no mapping layer exists between them:

| Layer | What happens |
|-------|--------------|
| Reservation | A request may ask for capabilities; Wi-Lab assigns the least capable free device that provides them |
| Frontend | The band dropdown in the network form only offers bands the reserved device declares, and defaults to one it can serve |
| AP creation | `band` must be a band the device declares (otherwise `422`); it then selects the channel range and the hostapd hardware mode |

The declaration is **enforced at AP creation**: `POST /interface/{reservation_id}/network`
with a `band` the reserved device does not declare (`dual` needs both) is refused at once
with `422`, without looking at the hardware. The configuration is authoritative: a device
declared 2.4 GHz-only provides only 2.4 GHz, even if the adapter could do more. The frontend
filters the band dropdown the same way, purely as a convenience.

Capabilities have **no effect on subnets, NAT or iptables** — a device's `/24` is still
allocated from `dhcp_base_network` by its position in the `networks` list, regardless of
what it declares.

---

### Reservation-Driven Timeout

Network lifetime is controlled by device reservations. When a reservation
expires, the associated network is automatically stopped and cleaned up.

Users must first reserve a device via the reservation API which specifies
`duration_seconds`. The reservation expiry becomes the authoritative
network lifetime.

This ensures networks don't run indefinitely and prevents orphaned rules.

---

## Pre-Deployment Checklist

Before deploying Wi-Lab to production:

- [ ] `python3 main.py --validate-config --check-hardware` exits 0
- [ ] Verified host subnet: `ip addr show | grep "inet "`
- [ ] Set WiFi subnet to different range (e.g., `192.168.120.0/24`)
- [ ] Declared `capabilities` on every device, matching what each adapter may be used for
- [ ] Tested network creation and deletion
- [ ] Verified SSH remains accessible during tests
- [ ] Set up monitoring of service logs
- [ ] Backed up iptables rules
- [ ] Documented network configuration
- [ ] Documented recovery procedures
- [ ] Tested autostart on reboot

---

## Additional Resources

- **iptables documentation:** https://linux.die.net/man/8/iptables
- **iw usage:** https://wireless.wiki.kernel.org/en/users/Documentation/iw
- **hostapd:** https://w1.fi/hostapd/
- **dnsmasq:** http://www.thekelleys.org.uk/dnsmasq/doc.html
- **systemd journalctl:** `man journalctl`

---

**Network configuration complete! 🔒**

Your WiFi access points are isolated and secure.
