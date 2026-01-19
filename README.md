# Wi-Lab

WiFi Access Point management REST API for testing and laboratory environments.

Wi-Lab provides programmatic control over multiple WiFi interfaces in Access Point (AP) mode through a REST API with token authentication and Swagger UI documentation.

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/your-org/wi-lab.git
cd wi-lab

# 2. Configure WiFi interface in config.yaml
nano config.yaml
# Update: auth_token, networks[].interface, dns_server, dhcp_base_network

# 3. Run automated setup (installs everything!)
sudo bash setup.sh

# 4. Verify installation
curl http://localhost:8080/api/v1/health
# Output: {"status":"ok"}

# 5. Access API documentation
# Open in browser: http://localhost:8080/docs
```

**That's it!** Wi-Lab is running and will autostart on reboot. 🚀

---

## What is Wi-Lab?

Wi-Lab simplifies WiFi Access Point management for testing:

- ✅ **Dynamic AP Creation:** Create/destroy WiFi networks on demand via REST API
- ✅ **Multi-Interface Support:** Manage multiple WiFi interfaces simultaneously
- ✅ **Flexible Configuration:** SSID, channel, band (2.4/5 GHz), encryption, hidden SSID
- ✅ **Client Control:** Enable/disable Internet access per network (NAT)
- ✅ **TX Power Management:** Control transmit power level (1-4 scale)
- ✅ **Network Isolation:** WiFi networks isolated from each other
- ✅ **Auto-Expiry:** Networks automatically stop after configured timeout
- ✅ **REST API:** Full programmatic control with Swagger documentation
- ✅ **Production Ready:** Systemd integration, autostart, comprehensive logging

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│  REST API (FastAPI on port 8080)    │
│  • Token authentication             │
│  • Swagger UI documentation         │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│  Network Lifecycle Manager          │
│  • Create/destroy WiFi networks     │
│  • Manage timeouts & expiry         │
│  • Control Internet access (NAT)    │
│  • TX power management              │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│  System Integration                 │
│  • hostapd (AP mode)                │
│  • dnsmasq (DHCP)                   │
│  • iptables (NAT/isolation)         │
│  • iw/ip commands (WiFi control)    │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│  WiFi Interfaces (AP mode)          │
│  • 192.168.120.0/24 (Network 1)     │
│  • 192.168.121.0/24 (Network 2)     │
│  • ... (more networks as needed)    │
└─────────────────────────────────────┘
```

---

## Requirements

### Hardware
- WiFi interface with AP mode support
- Ethernet interface for Internet uplink
- 2GB+ RAM
- Ubuntu 20.04+ or Debian 11+

### System Packages
The setup script automatically installs:
- `hostapd` - Access Point daemon
- `dnsmasq` - DHCP server
- `iptables` - Firewall/NAT
- `iw` - Wireless management
- `python3` - Runtime

---

## Documentation

Comprehensive guides available in `docs/` directory:

| Document | Purpose |
|----------|---------|
| [installation-guide.md](docs/installation-guide.md) | Installation, configuration, WiFi interface setup |
| [swagger.md](docs/swagger.md) | API testing via Swagger UI, endpoint examples |
| [unit-testing.md](docs/unit-testing.md) | Running tests, test structure, pytest usage |
| [networking.md](docs/networking.md) | Networking details, iptables rules, diagnostics |
| [troubleshooting.md](docs/troubleshooting.md) | Common issues, service management, debugging |

---

## API Example

### Create a WiFi Network

```bash
TOKEN="your-auth-token"
INTERFACE="wlx782051245264"

curl -X POST "http://localhost:8080/api/v1/interface/$INTERFACE/network" \
  -H "Authorization: Bearer $TOKEN" \
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

### Get Connected Clients

```bash
curl "http://localhost:8080/api/v1/interface/$INTERFACE/clients" \
  -H "Authorization: Bearer $TOKEN"
```

### Disable Internet Access

```bash
curl -X POST "http://localhost:8080/api/v1/interface/$INTERFACE/internet/disable" \
  -H "Authorization: Bearer $TOKEN"
```

See [docs/swagger.md](docs/swagger.md) for complete API reference and examples.

---

## Development

For development setup and contribution guidelines, see [README-DEV.md](README-DEV.md).

Quick development start:

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run development server
python main.py

# Run tests
pytest tests/ -v
```

---

## Troubleshooting

For detailed troubleshooting information, see [docs/troubleshooting.md](docs/troubleshooting.md).

This includes:
- WiFi interface compatibility and setup issues
- Network configuration and subnet conflicts
- Service management and startup problems
- API connectivity and response issues
- Common errors and solutions

---

## Support & Documentation

- **Full Documentation:** See files in `docs/` directory
- **API Reference:** `http://localhost:8080/docs` (Swagger UI)
- **GitHub Issues:** Report bugs and request features

---

## License

See [LICENSE](LICENSE) file.

---

**Ready to get started?** → Read [docs/installation-guide.md](docs/installation-guide.md)

**Want to contribute?** → Read [README-DEV.md](README-DEV.md)

**Need help?** → Check [docs/troubleshooting.md](docs/troubleshooting.md)


## Configuration

File: [config.yaml](config.yaml)

### Essential Parameters

```yaml
# Authentication
auth_token: "your-secret-token-12345-change-this"  # CHANGE THIS!

# API Configuration
api_port: 8080

# Network Configuration
dhcp_base_network: "192.168.120.0/24"  # ⚠️  Must NOT conflict with host network!
upstream_interface: "auto"              # Auto-detect upstream (recommended)
dns_server: "192.168.10.21"            # Your network's DNS server IP
internet_enabled_by_default: true

# Timeout Configuration
default_timeout: 3600  # 1 hour
max_timeout: 86400     # 24 hours
min_timeout: 60        # 1 minute

# Managed WiFi Interfaces
networks:
  - net_id: "ap-01"
    interface: "wlx782051245264"  # Your WiFi interface (see: iw dev)
```

### ⚠️ CRITICAL: Subnet Configuration

**ALWAYS ensure WiFi subnet is different from your host network!**

```bash
# Check your host network
ip addr show | grep "inet "
# Example: inet 192.168.10.113/24

# If host is on 192.168.10.x, use different subnet for WiFi:
dhcp_base_network: "192.168.120.0/24"  # ✅ SAFE
```

Using the same subnet will **block your host networking** and require a reboot!

---

## API Usage

### Authentication

All API requests require Bearer token authentication:

```bash
curl -H "Authorization: Bearer your-token" http://localhost:8080/api/v1/health
```

### Create WiFi Network

```bash
curl -X POST http://localhost:8080/api/v1/network/ap-01/network \
  -H "Authorization: Bearer secret-token-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "ssid": "TestAP",
    "channel": 6,
    "band": "2.4ghz",
    "encryption": "wpa2",
    "password": "secure-password-123",
    "internet_enabled": true,
    "timeout": 3600
  }'
```

### Control Internet Access

```bash
# Disable Internet
curl -X POST http://localhost:8080/api/v1/network/ap-01/internet/disable \
  -H "Authorization: Bearer secret-token-12345"

# Enable Internet
curl -X POST http://localhost:8080/api/v1/network/ap-01/internet/enable \
  -H "Authorization: Bearer secret-token-12345"
```

### List Connected Clients

```bash
curl http://localhost:8080/api/v1/network/ap-01/clients \
  -H "Authorization: Bearer secret-token-12345"
```

### Stop Network

```bash
curl -X DELETE http://localhost:8080/api/v1/network/ap-01/network \
  -H "Authorization: Bearer secret-token-12345"
```

### API Documentation

**Swagger UI:** http://localhost:8080/docs  
**ReDoc:** http://localhost:8080/redoc

---

## Service Management

Wi-Lab runs as a systemd service after installation:

```bash
# Start service
sudo systemctl start wi-lab.service

# Stop service
sudo systemctl stop wi-lab.service

# Restart service
sudo systemctl restart wi-lab.service

# Check status
sudo systemctl status wi-lab.service

# View logs (real-time)
sudo journalctl -u wi-lab.service -f

# View logs (last 50 lines)
sudo journalctl -u wi-lab.service -n 50
```

---

---

## Development

See [README-DEV.md](README-DEV.md) for:
- Development environment setup
- Running tests
- Code structure
- Contributing guidelines

---

## Documentation

- **Installation Guide:** [docs/installation-guide.md](docs/installation-guide.md)
- **Troubleshooting:** [docs/troubleshooting.md](docs/troubleshooting.md)
- **Networking:** [docs/networking.md](docs/networking.md)
- **API Documentation:** http://localhost:8080/docs (Swagger UI)

---

## License

See [LICENSE](LICENSE) file.

---

## Support

- **GitHub Issues:** Report bugs and feature requests
- **Documentation:** Check docs/ folder for detailed guides
- **Logs:** `sudo journalctl -u wi-lab.service -f`

---

**Wi-Lab: Professional WiFi AP Management** 🚀
