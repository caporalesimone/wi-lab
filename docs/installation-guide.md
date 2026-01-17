# Wi-Lab: Installation and Configuration Guide

## Table of Contents

1. [System Requirements](#system-requirements)
2. [WiFi Interface Compatibility](#wifi-interface-compatibility)
3. [Prerequisites](#prerequisites)
4. [Quick Setup](#quick-setup)
5. [Manual Setup](#manual-setup)
6. [Verify Installation](#verify-installation)

---

## System Requirements

### Hardware

- **Processor:** x86_64 or ARM64
- **RAM:** Minimum 2GB (4GB+ recommended)
- **WiFi Interface:** At least one USB WiFi adapter with AP mode support
- **Network Interface:** One Ethernet interface for Internet uplink

### Software

| Component | Version | Purpose |
|---|---|---|
| Ubuntu/Debian | 20.04+ | Base system |
| Python | 3.9+ | API runtime |
| hostapd | 2.9+ | Access Point mode |
| dnsmasq | 2.80+ | DHCP server |
| iptables | 1.8+ | Firewall/NAT |
| iw | - | Wireless management |

---

## WiFi Interface Compatibility

### Check if Your Interface Supports AP Mode

Before installing Wi-Lab, verify that your WiFi interface supports AP (Access Point) mode:

```bash
# List all WiFi interfaces
iw dev

# Check for AP capability on each phy
iw list | grep -A 20 "Supported interface modes"
# Look for "AP" in the output
```

**Example output showing AP support:**
```
Supported interface modes:
    * IBSS
    * managed
    * AP              ← This is what we need!
    * AP/VLAN
    * monitor
```

If your interface does **NOT** show `AP`, it may not support AP mode. Check:
- WiFi driver documentation
- Firmware version (`ethtool -i <interface>`)
- Consider using a different USB adapter

### Find Your WiFi Interface Name

```bash
# List all interfaces with details
iw dev

# Typical output:
# phy#0
#     Interface wlx782051245264
#         ifindex 3
#         type managed
#         addr 78:20:51:24:52:64
```

Common naming patterns:
- `wlan0`, `wlan1` - Built-in or older adapters
- `wlx<MAC>` - USB adapters (name derived from MAC address)

**Save this interface name** - you'll need it in `config.yaml`.

---

## Prerequisites

### Verify Essential Tools

```bash
# Python 3.9+
python3 --version

# hostapd
which hostapd

# dnsmasq  
which dnsmasq

# iptables
which iptables

# iw
which iw
```

If any tools are missing, the `setup.sh` script will install them.

---

## Quick Setup

The `setup.sh` script automates the entire installation process:

```bash
# 1. Clone repository
git clone https://github.com/your-org/wi-lab.git
cd wi-lab

# 2. Edit config.yaml with your settings
nano config.yaml
# See below for configuration guide

# 3. Run automated setup
sudo bash setup.sh

# 4. Verify installation
curl http://localhost:8080/api/v1/health
# Expected output: {"status":"ok"}
```

The `setup.sh` script automatically:
- ✅ Verifies and installs all required system packages
- ✅ Creates Python virtual environment at `/opt/wilab-venv`
- ✅ Installs Python dependencies
- ✅ Configures systemd service
- ✅ Enables autostart on boot

**Note:** Setup requires `sudo` privileges.

---

## Manual Configuration (After Running setup.sh)

If you need to manually configure Wi-Lab after running `setup.sh`, or if you're deploying in a custom environment:

### Configure config.yaml

Edit `config.yaml` with your WiFi interface name and network settings:

```bash
sudo nano config.yaml
```

**Critical parameters:**
- `auth_token`: Strong API authentication token (change the default!)
- `networks[].interface`: Your WiFi interface name (from `iw dev`)
- `dns_server`: DNS server IP for clients (typically your gateway)
- `dhcp_base_network`: Client IP range (verify no conflict with host network!)

**Example:**
```yaml
auth_token: "your-strong-token-here"
api_port: 8080
default_timeout: 3600

dhcp_base_network: "192.168.120.0/24"
upstream_interface: "auto"
dns_server: "192.168.10.1"
internet_enabled_by_default: true

networks:
  - net_id: "ap-01"
    interface: "wlx782051245264"
```

### After Configuration Changes

Restart the service for changes to take effect:

```bash
# Reload config and restart
sudo systemctl restart wi-lab.service

# Check status
sudo systemctl status wi-lab.service

# View logs
sudo journalctl -u wi-lab.service -n 20
```

---

## Verify Installation

### Installation Checklist

```bash
# Check 1: Required tools installed
hostapd --version
dnsmasq --version
iw --version

# Check 2: WiFi interface available
iw dev

# Check 3: Config file exists and is valid
cat config.yaml | head -20

# Check 4: Virtual environment created
ls -la /opt/wilab-venv/bin/python

# Check 5: Service enabled and running
sudo systemctl is-enabled wi-lab.service
sudo systemctl is-active wi-lab.service

# Check 6: API responding
curl -s http://localhost:8080/api/v1/health | jq '.'

# Check 7: Service logs clean
sudo journalctl -u wi-lab.service --since "5 minutes ago" | tail -20
```

All checks should pass ✅ before proceeding to API testing.

### Test API

Access the Swagger UI documentation and testing interface:

```
http://localhost:8080/docs
```

Use your `auth_token` from `config.yaml` to authorize requests.

See [swagger.md](swagger.md) for detailed API testing guide.

---

## Configuration File Reference

The `config.yaml` file controls Wi-Lab behavior. See the file itself for inline documentation - all parameters are well-commented.

Key sections:
- **Authentication:** `auth_token` for API security
- **API:** Server port and documentation
- **Timeouts:** Network lifetime configuration
- **Network:** DHCP subnets and upstream interface
- **Networks:** WiFi interface definitions

For comprehensive configuration details, refer directly to `config.yaml` which includes detailed comments for each parameter.

---

## Next Steps

After successful installation:

1. **Access the API:** Open `http://localhost:8080/docs` in your browser
2. **Create your first WiFi network** using the API
3. **Connect a client device** to the WiFi network
4. **Monitor logs** with `sudo journalctl -u wi-lab.service -f`

For troubleshooting, see [troubleshooting.md](troubleshooting.md).

For detailed networking information, see [networking.md](networking.md).

---

**Installation complete! 🚀**

Wi-Lab is now running and will autostart on system reboot.
