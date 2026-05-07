# Wi-Lab

Wi-Lab turns a Linux machine with multiple USB WiFi adapters into a shared, API-controlled Access Point lab. Each physical WiFi interface can be **reserved** by a user for a configurable time window, used to spin up an isolated AP with its own SSID, channel, DHCP range, and optional Internet access, then released for the next user. Everything is driven through a REST API (FastAPI + Swagger UI) and a companion Angular web frontend.

Typical use-cases: automated wireless testing, RF/antenna benchmarking, classroom labs, CI pipelines that need on-demand WiFi networks.

---

## How It Works

1. **Multiple WiFi interfaces** — each USB adapter is declared in `config.yaml` and managed independently.
2. **Reservation system** — before touching an interface you acquire a time-limited (or unlimited) reservation token via the API. The token is an 8-char hex string; when it expires the AP is torn down automatically.
3. **One AP per interface** — while reserved, you can create a WiFi network (hostapd), configure DHCP (dnsmasq), enable/disable Internet (iptables NAT), and adjust TX power — all via REST calls.
4. **Web frontend** — an Angular SPA shows every interface as a card (available / owned / occupied), lets you reserve, configure, and monitor networks from the browser. The auth token is entered at runtime via a login dialog.
5. **Web API** — every operation is also available programmatically (`/api/v1/…`), with full Swagger UI at `http://<host>:8080/docs`. Useful for scripting, SDKs, or CI integration.

---

## Requirements

| Category | Requirement |
|----------|-------------|
| **OS** | Ubuntu 25+ (tested on 25.04) |
| **Hardware** | One or more USB WiFi adapters with AP-mode support (`iw list \| grep AP`) |
| **Network** | Ethernet interface with Internet access (for NAT uplink) |
| **RAM** | 2 GB+ |

All system packages (hostapd, dnsmasq, iptables, iw, python3 …) are installed automatically by the installer.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/caporalesimone/wi-lab
cd wi-lab

# 2. Copy and edit configuration
cp config.example.yaml config.yaml
nano config.yaml          # set auth_token, networks[].interface, dhcp_base_network, dns_server

# 3. Install (creates venv, installs deps, builds frontend, enables systemd service)
sudo bash install.sh
```

After installation Wi-Lab is running on port **8080** and will autostart on reboot.
Open `http://<host>:8080` for the web UI or `http://<host>:8080/docs` for the Swagger API.

To **uninstall** and remove the systemd service:

```bash
sudo bash uninstall.sh
```

---

## Configuration

File: `config.yaml` (copy from `config.example.yaml`).

Key sections:

```yaml
auth_token: "change-me"                 # Bearer token for API authentication
api_port: 8080

# Reservation timeouts
max_timeout: 86400                      # 24 h
min_timeout: 60                         # 1 min (hard floor: 10 s)
allow_unlimited_reservation: false      # allow duration_seconds=0

# Networking
dhcp_base_network: "192.168.120.0/24"   # MUST NOT overlap with host network!
upstream_interface: "auto"
dns_server: "208.67.222.222"
internet_enabled_by_default: true
country_code: "IT"                      # WiFi regulatory domain

# Managed interfaces
networks:
  - interface: "wlxbc071dc527d6"
    display_name: "bench-antenna-1"
  - interface: "wlx7820512451b4"
    display_name: "bench-antenna-2"
```

> **Warning:** `dhcp_base_network` must use a subnet different from your host LAN. A conflict will break host networking and may require a physical reboot.

---

## Service Management

Everything is managed through the **Makefile**. Run `make` (no arguments) to see all targets:

```
Wi-Lab Development Targets

Virtual Environment:
  make venv              Create local Python virtual environment
  make clean-venv        Remove virtual environment

Testing (Local - uses venv):
  make test-local        Run all tests with verbose output
  make test-local-quick  Run tests with minimal output
  make test-local-cov    Run tests with coverage report (HTML)

Code Quality:
  make lint              Run ruff linter
  make lint-fix          Fix code style issues with ruff
  make type-check        Run mypy type checker

Frontend:
  make build-frontend    Build minified production frontend (via Docker)

Service Management (requires root):
  make stop              Stop Wi-Lab systemd service
  make start             Start Wi-Lab systemd service
  make restart           Restart Wi-Lab systemd service
```

---

## API Example

All requests require the header `Authorization: Bearer <auth_token>`.

```bash
# 1. Reserve a device for 15 minutes (900 seconds)
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900}'

# Response:
# {
#   "reservation_id": "a1b2c3d4",
#   "interface": "wlxbc071dc527d6",
#   "display_name": "bench-antenna-1",
#   "expires_at": "2026-04-16T15:15:00Z",
#   "expires_in": 900
# }

# 2. Create a WiFi network on the reserved device
curl -X POST http://localhost:8080/api/v1/network/a1b2c3d4 \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"ssid": "TestNetwork", "channel": 6, "band": "2.4ghz", "encryption": "wpa2", "password": "mypassword"}'
```

For the full endpoint reference, open **Swagger UI** at `http://<host>:8080/docs` or **ReDoc** at `http://<host>:8080/redoc`.

---

## Documentation

Detailed guides live in the `docs/` folder:

| Document | Topic |
|----------|-------|
| [swagger.md](docs/swagger.md) | API exploration via Swagger UI |
| [networking.md](docs/networking.md) | Subnet layout, iptables, NAT internals |
| [unit-testing.md](docs/unit-testing.md) | Test suite structure and pytest usage |
| [troubleshooting.md](docs/troubleshooting.md) | Common issues, diagnostics scripts, debugging |
| [readme-dev.md](docs/readme-dev.md) | Developer setup and contribution workflow |

Planned features and ideas are tracked in the `TODOs/` folder.

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues (interface compatibility, subnet conflicts, service failures, API errors) and the diagnostic scripts in `diagnostics/troubleshooting/`.

---

## Tested Hardware

| Commercial Name | Chipset | Driver | Driver Version | Kernel Version | OS | AP Mode |
|-----------------|---------|--------|----------------|----------------|----|---------|
| BrosTrend AXE3000 | MediaTek MT7921U | mt7921u | FW ____010000 | 7.0.0-15-generic | Ubuntu 26.04 LTS | ✅ Working |
| TP-Link Archer T3U Plus | Realtek RTL8822BU | rtw88_8822bu | FW 30.20.0 | 7.0.0-15-generic | Ubuntu 26.04 LTS | ❌ Broken (no beacon TX) |

> **Note:** The Realtek RTL8822BU with the in-kernel `rtw88_8822bu` driver fails to transmit beacons in AP mode (firmware reports `failed to get tx report from firmware`). This is a [known upstream issue](https://github.com/lwfinger/rtw88/issues/241). MediaTek-based adapters are recommended for reliable AP operation.

---

## License

MIT — see [LICENSE](LICENSE).
