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
sudo bash install.sh

# 4. Verify installation and access API
# Open in browser: http://localhost:8080/docs
```

**That's it!** Wi-Lab is running and will autostart on reboot. 🚀

---

## Installation and Uninstallation

Use the project scripts for lifecycle management:

```bash
# Install Wi-Lab and configure systemd/service dependencies
sudo bash install.sh

# Uninstall Wi-Lab and remove installed service artifacts
sudo bash uninstall.sh
```

Notes:
- Run from the repository root.
- Review `config.yaml` before installation.
- After installation, open `http://localhost:8080/docs` to validate service availability.

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
| [swagger.md](docs/swagger.md) | API testing via Swagger UI, endpoint examples |
| [unit-testing.md](docs/unit-testing.md) | Running tests, test structure, pytest usage |
| [networking.md](docs/networking.md) | Networking details, iptables rules, diagnostics |
| [troubleshooting.md](docs/troubleshooting.md) | Common issues, service management, debugging |

---

## Development

For development setup and contribution guidelines, see [README-DEV.md](README-DEV.md).

Quick development start using Makefile:

```bash
# Create virtual environment with all dependencies
make venv

# Activate the virtual environment
source .venv/bin/activate

# Run tests
make test-local           # Full test suite with verbose output
make test-local-quick     # Quick test run with minimal output
make test-local-cov       # Run tests with coverage report (HTML)

# Run development server
python main.py
```

For all available development tasks, see [Makefile](Makefile) or run `make help`.

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

**Ready to get started?** → Run `sudo bash install.sh`

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

> 💡 **Quick Tip:** For interactive API exploration, use the **Swagger UI** at http://localhost:8080/docs  
> You can test all endpoints directly without writing curl commands.

All API requests require Bearer token authentication in the `Authorization: Bearer <token>` header.

### Example: Create WiFi Network

```bash
curl -X POST http://localhost:8080/api/v1/interface/ap-01/network \
  -H "Authorization: Bearer secret-token-12345" \
  -H "Content-Type: application/json" \
  -d '{"ssid": "TestAP", "channel": 6, "band": "2.4ghz", "encryption": "wpa2", "password": "pass123"}'
```

For all other operations (stop network, enable/disable internet, get status, list clients, etc.), use the interactive **Swagger UI** at http://localhost:8080/docs.

### API Documentation

- **Interactive API:** http://localhost:8080/docs (Swagger UI)
- **Alternative docs:** http://localhost:8080/redoc (ReDoc)

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

## Documentation

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
