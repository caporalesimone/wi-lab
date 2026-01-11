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
# Via API
curl http://localhost:8080/api/v1/interfaces

# Check hostapd processes
ps aux | grep "[h]ostapd"

# Check dnsmasq processes
ps aux | grep "[d]nsmasq"
```

### View Service Logs

```bash
# Real-time logs
sudo journalctl -u wilab.service -f

# Last 50 lines
sudo journalctl -u wilab.service -n 50

# Since last boot
sudo journalctl -u wilab.service -b

# Errors only
sudo journalctl -u wilab.service | grep -i "error\|critical"

# Last hour
sudo journalctl -u wilab.service --since "1 hour ago"
```

---

## Troubleshooting

### Issue: SSH Connection Lost After Network Creation

**Cause:** Host network conflicts with WiFi subnet.

**Diagnosis:**
```bash
# Check host subnet
ip addr show | grep "inet " | head -1
# Example: inet 192.168.10.113/24

# Check WiFi subnet in config
grep "dhcp_base_network:" config.yaml
# Example: dhcp_base_network: "192.168.10.0/24"
```

**Solution:**
1. Use system console or IPMI access
2. Stop Wi-Lab: `sudo systemctl stop wilab.service`
3. Update `config.yaml` with different subnet: `192.168.120.0/24`
4. Restart: `sudo systemctl restart wilab.service`

**Prevention:**
```bash
# Before configuration, always check host subnet
ip addr show | grep "inet "

# Choose WiFi subnet that doesn't conflict
# Good examples: 192.168.120.0/24, 10.0.0.0/24, etc.
```

### Issue: iptables Rules Interfering with SSH

**Symptoms:** SSH connections drop when Wi-Lab runs specific isolation rules.

**Diagnosis:**
```bash
# Check if isolation is enabled
grep -A 5 "isolation_enabled" /etc/systemd/system/wilab.service

# View isolation rules
sudo iptables -L FORWARD -n -v | grep "192.168"
```

**Solution:**
Isolation is currently **disabled** by default. If you've enabled it and SSH is affected:

```bash
# Temporarily stop Wi-Lab
sudo systemctl stop wilab.service

# Flush FORWARD rules (WARNING: clears all routing!)
sudo iptables -F FORWARD

# Restart
sudo systemctl restart wilab.service
```

### Issue: Slow WiFi Performance

**Cause:** Channel congestion or interference.

**Diagnosis:**
```bash
# Check current channel and power
iw dev wlx782051245264 info

# Scan for nearby networks
sudo iw dev wlx782051245264 scan | grep -E "channel|SSID"
```

**Solution:**
Create WiFi networks on less congested channels:
- 2.4 GHz: Use channels 1, 6, or 11 (non-overlapping)
- 5 GHz: More channels available, typically less congestion

Specify channel when creating network via API.

### Issue: DHCP Clients Not Getting IPs

**Diagnosis:**
```bash
# Check dnsmasq is running
ps aux | grep "[d]nsmasq"

# Check dnsmasq logs
sudo journalctl -u wilab.service | grep -i "dnsmasq"

# Check client connections
curl http://localhost:8080/api/v1/interface/wlx782051245264/clients
```

**Solution:**
```bash
# Restart WiFi network
curl -X DELETE http://localhost:8080/api/v1/interface/wlx782051245264/network

# Recreate network
curl -X POST http://localhost:8080/api/v1/interface/wlx782051245264/network \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "ssid": "TestAP",
    "channel": 6,
    "band": "2.4ghz",
    "encryption": "wpa2",
    "password": "test1234",
    "tx_power_level": 4
  }'
```

---

## Emergency Recovery

### Lost Network Access

If you lose SSH or network access after Wi-Lab operations:

**Option 1: Physical Console**
```bash
# At console, stop Wi-Lab
sudo systemctl stop wilab.service

# Verify SSH works
ssh user@host

# Check iptables state
sudo iptables -L -n -v
```

**Option 2: System Reboot**
```bash
# Reboot clears temporary iptables rules
sudo reboot
```

### Manual Cleanup

If you need to manually remove Wi-Lab's network modifications:

```bash
# Stop Wi-Lab service
sudo systemctl stop wilab.service

# Kill any remaining processes
sudo pkill -f hostapd
sudo pkill -f dnsmasq

# Flush iptables rules (WARNING: removes ALL custom rules)
sudo iptables -F FORWARD
sudo iptables -F INPUT
sudo iptables -t nat -F POSTROUTING

# Disable IP forwarding
sudo sysctl -w net.ipv4.ip_forward=0

# Reset WiFi interfaces to managed mode
for iface in $(iw dev | grep Interface | awk '{print $2}'); do
    sudo ip link set "$iface" down
    sudo iw dev "$iface" set type managed
    sudo ip link set "$iface" up
done
```

---

## Best Practices

### Pre-Deployment Testing

1. **Verify host subnet:** `ip addr show | grep "inet "`
2. **Choose non-conflicting WiFi subnet:** e.g., `192.168.120.0/24`
3. **Test network creation/deletion:** Verify SSH remains accessible
4. **Test client connectivity:** Connect device, verify IP assignment
5. **Monitor logs:** Check for errors: `sudo journalctl -u wilab.service -f`

### Ongoing Monitoring

```bash
# Monitor WiFi processes
watch -n 2 'ps aux | grep -E "[h]ostapd|[d]nsmasq"'

# Monitor iptables changes
watch -n 2 'sudo iptables -L FORWARD -n | tail -10'

# Monitor service health
watch -n 5 'sudo systemctl status wilab.service'
```

### Configuration Backup

```bash
# Backup current iptables state BEFORE running Wi-Lab
sudo iptables-save > ~/.iptables-backup-pre-wilab.rules

# If needed, restore
sudo iptables-restore < ~/.iptables-backup-pre-wilab.rules

# Backup config and service file
cp config.yaml config.yaml.backup
sudo cp /etc/systemd/system/wilab.service /etc/systemd/system/wilab.service.backup
```

### Secure Timeout Configuration

Networks auto-expire and clean up after their configured timeout:

```yaml
# In config.yaml
default_timeout: 3600  # 1 hour - network auto-stops
max_timeout: 86400     # 24 hours - maximum limit
min_timeout: 60        # 1 minute - minimum limit
```

This ensures networks don't run indefinitely and prevents orphaned rules.

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
