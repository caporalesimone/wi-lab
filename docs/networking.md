# Wi-Lab Networking Guide

## Overview

Wi-Lab manages WiFi Access Points by directly controlling network settings on the host system. This document explains how Wi-Lab modifies the network, potential risks, and how to diagnose and recover from issues.

Each AP's masquerade rule matches only that AP's assigned subnet.
Disabling Internet blocks forwarded traffic, including existing connections,
for that AP; it does not disconnect its Wi-Fi clients. Subsequent TCP packets
from clients receive a reset so applications can detect the interruption.

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

### 4. Captive Portal Rules (iptables)

**What:** Per-AP chains `wilab-cp-<interface>` in the `nat` and `filter` tables, jumped
to from `PREROUTING` and `FORWARD` (comment `wilab-captive-<interface>`)  
**When:** Network created with `captive_portal: true`  
**Impact:** Unsigned clients' DNS and HTTP are redirected to the AP gateway and
other forwarded traffic is rejected. Signing in adds a `RETURN` rule for that
client's MAC and IP only.  
**Reversible:** Yes - chains are removed when the network stops; stale chains
are removed when Wi-Lab starts

```bash
# Inspect captive portal rules
sudo iptables -t nat -S | grep wilab-cp
sudo iptables -S | grep wilab-cp
```

### 5. Host Network Manager Exclusion

**What:** NetworkManager releases each Wi-Lab radio (`nmcli device set ... managed no`); a
runtime systemd-networkd rule marks the radios unmanaged  
**When:** Antennas are added by discovery  
**Impact:** Only Wi-Lab radios; NetworkManager's configuration is never written or reloaded  
**Reversible:** Yes - runtime state and the `/run` file disappear on reboot

```bash
cat /run/systemd/network/00-wilab-unmanaged.network
nmcli device status; networkctl list
```

Recommended: do not connect the Wi-Lab host via Wi-Fi, and do not use Wi-Fi adapters
outside Wi-Lab on it. If one is needed, list it with `disable: true`.

### 6. WiFi Interface State

**What:** Interface switched to AP mode  
**When:** Network is created  
**Impact:** Interface unavailable for other applications (e.g., NetworkManager)  
**Reversible:** Yes - restored to managed mode and left down when network stops.
On the next start, only hostapd brings up the radio. Wi-Lab verifies that
hostapd has enabled the expected AP via its private control socket before
assigning the gateway address and starting dnsmasq. DHCP never changes the
interface state. If startup fails, Wi-Lab attempts rollback before allowing
the adapter to be reused. This avoids an unnecessary up/down cycle; it does
not fix driver or firmware failures.

Wi-Lab runs hostapd in the foreground and verifies that the child process
has exited before resetting the interface. Startup timeout cleanup does
not depend on a PID file. If the process cannot be stopped or the radio
cannot be reset, the adapter is not reassigned.

If starting the AP fails because of the radio (hostapd `SIGSEGV`, a beacon
rejected during interface setup, or a radio or readiness timeout), Wi-Lab
starts it again on the same adapter within the original request, on either
band, up to 3 starts in total. It waits 1 s after each successful rollback and
retries only while the reservation is valid and enough of the 15-second
startup budget remains. This budget limits the retries, not rollback. A failed
retry is reported using the creation recovery contract. Once an AP has
started, a separate watchdog handles confirmed AP outages or DHCP failure.
See [Architecture](architecture.md) for
restart limits, quarantine and the post-reset AP/DHCP probe.

Startup and cleanup are serialized per adapter, not across all adapters.
An adapter remains held until cleanup succeeds, including after expiry. If
startup cleanup is unsafe, the ID is invalidated and quarantine prevents reuse.
System status reads allocation and recovery snapshots without running cleanup
or waiting for the adapter's startup to finish; it still performs host health
checks and is not a sub-second latency guarantee.

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

Before starting an AP, Wi-Lab checks host IPv4 routes and skips overlapping `/24`
subnets. For example, with base `192.168.9.0/24` and host LAN `192.168.10.0/24`,
the first two APs use `192.168.9.0/24` and `192.168.11.0/24`. The default route is
not treated as a collision. If routes cannot be read or no subnet is available
through third octet 255, the AP does not start; existing APs are unaffected.

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

---

## Diagnostics and Monitoring

### Check WiFi Interface Status

```bash
# List WiFi interfaces
iw dev

# Check mode and administrative state after a successful network stop
iw dev wlx782051245264 info
ip -br link show wlx782051245264

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

### Reservation-Driven Timeout

Network lifetime is controlled by device reservations. When a reservation
expires, the associated network is automatically stopped and cleaned up.

Users must first reserve a device via the reservation API which specifies
`duration_seconds`. The reservation expiry becomes the authoritative
network lifetime.

The device is not reassigned until its previous network has been cleaned up.
If cleanup fails, the device remains held; other free devices can still be
reserved. The API returns 503 when cleanup prevents an operation; retry after
resolving the error. A bulk release may have released some devices before
encountering an error.

---

## Pre-Deployment Checklist

Before deploying Wi-Lab to production:

- [ ] Verified host subnet: `ip addr show | grep "inet "`
- [ ] Set WiFi subnet to different range (e.g., `192.168.120.0/24`)
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
