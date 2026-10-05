# Wi-Lab

Wi-Lab turns a Linux machine with multiple USB WiFi adapters into a shared, API-controlled Access Point lab. Each physical WiFi interface can be **reserved** by a user for a configurable time window, used to spin up an isolated AP with its own SSID, channel, DHCP range, and optional Internet access, then released for the next user. Everything is driven through a REST API (FastAPI + Swagger UI) and a companion Angular web frontend.

Typical use-cases: automated wireless testing, RF/antenna benchmarking, classroom labs, CI pipelines that need on-demand WiFi networks.

---

## How It Works

1. **Multiple WiFi interfaces** — each USB adapter is declared in `config.yaml` and managed independently.
2. **Reservation system** — before touching an interface you acquire a time-limited (or unlimited) reservation token via the API. The token is an 8-char hex string; when it expires the AP is torn down automatically.
3. **Device capabilities** — each adapter declares in `config.yaml` what it may be used for (currently the `2.4ghz` and `5ghz` bands). A reservation can ask for the capabilities it needs and Wi-Lab assigns the **least capable device that satisfies the request**, so a dual-band adapter stays free for whoever actually needs 5 GHz.
4. **One AP per interface** — while reserved, you can create a WiFi network (hostapd), configure DHCP (dnsmasq), enable/disable Internet (iptables NAT), and adjust TX power — all via REST calls.
5. **Web frontend** — an Angular SPA shows every interface as a card (available / owned / occupied), lets you reserve, configure, and monitor networks from the browser. The auth token is entered at runtime via a login dialog.
6. **Web API** — every operation is also available programmatically (`/api/v1/…`), with full Swagger UI at `http://<host>:8080/docs`. Useful for scripting, SDKs, or CI integration.

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
nano config.yaml          # set auth_token, networks[].interface + capabilities, dhcp_base_network, dns_server

# 3. Check the configuration before installing (optional - the installer does it too)
python3 main.py --validate-config

# 4. Install (creates venv, installs deps, builds frontend, enables systemd service)
sudo bash install.sh
```

The installer **aborts before enabling the service** if `config.yaml` does not validate,
so a bad configuration can never leave a half-installed system behind.

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
cors_origins: []                        # [] disables CORS; otherwise list allowed origins

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
    capabilities:
      "2.4ghz": true
      "5ghz": false                     # a 2.4-only adapter
  - interface: "wlx7820512451b4"
    display_name: "bench-antenna-2"
    capabilities:
      "2.4ghz": true
      "5ghz": true                      # dual-band
```

**Every key is mandatory.** Wi-Lab validates `config.yaml` at startup and refuses to
start if anything is missing or wrong — it never guesses a value and never edits the file.

### Device capabilities

`capabilities` is your **declaration** of what an adapter may be used for. Wi-Lab never
probes the hardware to fill it in, so you can legitimately declare `"5ghz": false` on a
dual-band adapter to keep that band for another bench.

| Rule | Meaning |
|------|---------|
| Valid ids | `2.4ghz`, `5ghz` |
| Every id on every device | A missing key is an error, not a silent `false` |
| At least one `true` | A device with no enabled band could never host an access point |

When a reservation requests capabilities, Wi-Lab picks the **least capable free device**
that satisfies them. With no capabilities requested, any free device will do — and the
same "least capable first" rule applies, so scarce dual-band hardware is left alone
whenever a simpler adapter would do.

> **Warning:** `dhcp_base_network` must use a subnet different from your host LAN. A conflict will break host networking and may require a physical reboot.

---

## Validating the Configuration

`config.yaml` can be checked at any time, on any machine, without starting the service:

```bash
python3 main.py --validate-config                  # structure, types and values
python3 main.py --validate-config --check-hardware  # also: interfaces exist, no subnet clash
make validate-config                                # the same, through the venv
```

The validator reports **every** problem in one pass, each with the fix, so a file can be
completed in a single editing session:

```
Wi-Lab configuration validation FAILED
File: /opt/wilab/config.yaml
2 error(s), 0 warning(s)

ERROR   networks[0].capabilities
        Missing required key.
        -> Add a capabilities block declaring: 2.4ghz, 5ghz

ERROR   cors_origins
        Missing required key.
        -> Add 'cors_origins: []' to disable CORS, or list the allowed origins
```

| Exit code | Meaning |
|-----------|---------|
| `0` | Valid (warnings may still be printed) |
| `1` | Invalid — see the report |
| `2` | The file could not be read or parsed at all |

`--validate-config` starts no server, touches no interface and changes nothing, so it is
safe to run on a production host. `--check-hardware` adds the checks that need the real
machine (interfaces present, `dhcp_base_network` not colliding with a host route); omit it
to validate on a laptop or in CI. Starting the service normally always runs both.

> **Upgrading from 3.x?** This is a breaking release. `capabilities`, `cors_origins` and
> `allow_unlimited_reservation` are now required in `config.yaml`: run `--validate-config`,
> fix everything it lists, and restart. Capability values have to be typed by hand on
> purpose. API clients must also send `required_capabilities` — see
> [Migration from older versions](TODOs/completed/device-capabilities.md#19-migration-from-older-versions).

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

Configuration:
  make validate-config   Validate config.yaml and exit (no service started)

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
# 1. Reserve a device for 15 minutes (900 seconds). Both fields are mandatory:
#    required_capabilities lists what you need, [] meaning "any device"
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900, "required_capabilities": []}'

# Response:
# {
#   "reservation_id": "a1b2c3d4",
#   "interface": "wlxbc071dc527d6",
#   "display_name": "bench-antenna-1",
#   "expires_at": "2026-04-16T15:15:00Z",
#   "expires_in": 900,
#   "capabilities": ["2.4ghz"]
# }

# 1b. ...or ask for a device that can do 5 GHz
curl -X POST http://localhost:8080/api/v1/device-reservation \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds": 900, "required_capabilities": ["5ghz"]}'

# 2. Create a WiFi network on the reserved device
curl -X POST http://localhost:8080/api/v1/network/a1b2c3d4 \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"ssid": "TestNetwork", "channel": 6, "band": "2.4ghz", "encryption": "wpa2", "password": "mypassword"}'
```

You never choose the antenna: Wi-Lab assigns the least capable free device that provides
what you asked for. `GET /api/v1/status` lists the capabilities of every device plus a catalogue of what the
lab as a whole can offer, so a client can decide what to ask for before reserving.

A reservation request that cannot be satisfied is answered precisely:

| Status | Meaning |
|--------|---------|
| `422` (missing field) | `duration_seconds` or `required_capabilities` is absent — the body lists every missing field |
| `409` | Matching devices exist but are all reserved — **retry later**; the body carries `next_available_in` (`null` when every holder has an unlimited reservation) |
| `422` | No device can *ever* provide what was asked — **change the request** |

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

Planned features and ideas are tracked in the `TODOs/` folder; the design documents of
features already shipped live in `TODOs/completed/`.

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues (interface compatibility, subnet conflicts, service failures, API errors) and the diagnostic scripts in `diagnostics/troubleshooting/`.

If the service does not start at all, run `python3 main.py --validate-config` first: a
configuration error is the most common cause and the report says exactly what to fix.

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
