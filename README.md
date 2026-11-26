# Wi-Lab

Wi-Lab turns a Linux machine with multiple USB WiFi adapters into a shared, API-controlled Access Point lab. Each physical WiFi interface can be **reserved** by a user for a configurable time window, used to spin up an isolated AP with its own SSID, channel, DHCP range, and optional Internet access, then released for the next user. Everything is driven through a REST API (FastAPI + Swagger UI) and a companion Angular web frontend.

Typical use-cases: automated wireless testing, RF/antenna benchmarking, classroom labs, CI pipelines that need on-demand WiFi networks.

> ⚠️ **Security warning (4.1.0): known, unfixed.** The route that serves the web frontend does not
> keep requests inside the frontend directory: anyone who can reach the API port can read **any file
> of the host without authentication** (for example `GET //etc/shadow`, or `config.yaml` with the
> auth token). It stays open until the frontend is rewritten. Do not expose the API port outside a
> trusted lab network.

---

## How It Works

1. **Multiple WiFi interfaces** — every AP-capable adapter is discovered automatically (`config.yaml` can give it a display name) and managed independently.
2. **Reservation system** — before touching an interface you acquire a time-limited (or unlimited) reservation token via the API. The token is an 8-char hex string; when it expires the AP is torn down automatically. A device is not reassigned until cleanup succeeds. If cleanup fails, the device stays held for retry; other free devices remain available.
3. **One AP per interface** — while reserved, you can create a WiFi network (hostapd), configure DHCP (dnsmasq), enable/disable Internet (iptables NAT), and adjust TX power (under debugging, not stable yet) — all via REST calls.
4. **Web frontend** — an Angular SPA shows every interface as a card (available / owned / occupied), lets you reserve, configure, and monitor networks from the browser. The auth token is entered at runtime via a login dialog.
5. **Web API** — every operation is also available programmatically (`/api/v2/…`), with full Swagger UI at `http://<host>:8080/docs`. Useful for scripting, SDKs, or CI integration.

---

## Requirements

| Category | Requirement |
|----------|-------------|
| **OS** | Ubuntu Server 25+ (tested on 26.04), network managed by systemd-networkd (netplan) |
| **NetworkManager** | Must not be installed, or must be disabled and masked. The installer detects it and offers to disable it; it never does so if NetworkManager manages the host's network. |
| **wpa_supplicant** | Not used by Wi-Lab. The installer offers to disable and mask it when the host does not use it as a Wi-Fi client. |
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
nano config.yaml          # set auth_token, antennas[] (interface, display_name, show_dfs_channels), dhcp_base_network, dns_server

# 3. Install (creates venv, installs deps, builds frontend, enables systemd service)
sudo bash install.sh
```

After installation Wi-Lab is running on port **8080** and will autostart on reboot.
Open `http://<host>:8080` for the web UI or `http://<host>:8080/docs` for the Swagger API.

For retry behavior and automatic USB reset, see
[AP creation procedure](docs/ap-creation-procedure.md) and [Architecture](docs/architecture.md).

To **uninstall** and remove the systemd service:

```bash
sudo bash uninstall.sh
```

---

## Configuration

File: `config.yaml` (copy from `config.example.yaml`).

Run `python main.py --validate-config --config config.yaml` to check configuration
without starting the service or probing antennas. It applies the same rules as the
service startup, so a file it accepts also lets the service start. Errors return exit code 1;
warnings identify ignored settings and the example token without printing secrets.

To share the current API documentation offline, run
`python scripts/export_api_docs.py --out api-docs`. The resulting ZIP contains
OpenAPI JSON, Swagger UI and ReDoc. Pinned renderer assets are downloaded when
building the bundle; the pages themselves do not require a running service.
Pull requests and pushes to `main` run backend tests, type-checking and the
frontend build in CI, and publish the documentation bundle as an artifact.
`make lint` remains a local check while existing Ruff findings are addressed.

Every setting is required: the service does not start if one is missing, so each value is a
deliberate choice. Only `hostapd_debug_dir` (diagnostics) and the `antennas` section may be left
out; `protected_commands_password` and `cors_origins` may be `null` to turn their feature off.
`config.example.yaml` documents each one.

```yaml
auth_token: "change-me"                 # Bearer token for API authentication
protected_commands_password: "change-me" # Maintenance endpoints; null disables them
api_port: 8080
captive_portal_port: 8081               # portal page on each AP gateway (not 80, not api_port)
cors_origins: null                      # or a list of trusted frontend origins

# Reservation timeouts
max_timeout: 86400                      # 24 h
min_timeout: 60                         # 1 min (hard floor: 10 s)
allow_unlimited_reservation: false      # allow duration_seconds=0

# Networking
dhcp_base_network: "192.168.120.0/24"   # Starting subnet for AP allocation
upstream_interface: "auto"
dns_server: "208.67.222.222"            # DNS handed to Wi-Fi clients
internet_enabled_by_default: true
country_code: "IT"                      # WiFi regulatory domain
# hostapd_debug_dir: "/var/log/wilab/hostapd"   # optional: reports of failed hostapd starts

# Optional names and DFS choice; every AP-capable Wi-Fi interface is discovered automatically
antennas:
  - interface: "wlxbc071dc527d6"
    display_name: "bench-antenna-1"
    show_dfs_channels: false            # required in each entry: offer the DFS channels (5 GHz 52-144)?
  - interface: "wlx7820512451b4"
    display_name: "bench-antenna-2"
    show_dfs_channels: false
```

Wi-Lab discovers Wi-Fi interfaces automatically (USB or built-in) and manages every radio that supports AP mode, except the upstream interface and any interface carrying a default route. `antennas` assigns display names and, with the required `show_dfs_channels`, whether the antenna offers DFS channels (5 GHz 52–144, which need about a minute of radar listening before the AP starts); unlisted interfaces are shown by interface name and offer DFS channels, and a listed interface that is missing does not stop the service. Set `disable: true` on an entry (`display_name` is then optional) to keep that radio out of Wi-Lab. USB adapters are detected automatically and are eligible for automatic port reset after repeated radio faults (see [Architecture](docs/architecture.md#8-quarantine-and-automatic-usb-recovery)).

Wi-Lab starts without antennas and a discovery service adds them: the first scan runs as soon as the API starts, then it repeats every 5 seconds while no antenna is available and every 30 seconds afterwards, for the whole life of the service. Antennas plugged in later are therefore added automatically within about 30 seconds, without a restart. Each scan re-reads `antennas` from `config.yaml` (display names, `disable` and `show_dfs_channels`) and only adds new AP-capable radios; antennas already in the pool are never removed or renamed and their reservations are not affected. Disabling or renaming an antenna that is already in use requires a service restart.

Wi-Lab skips `/24` subnets that overlap the host network when starting an AP.

---

## Service Management

Everything is managed through the **Makefile**. Run `make` (no arguments) to see all targets:

```
Wi-Lab Development Targets

Virtual Environment:
  make venv              Create local Python virtual environment
  make clean-venv        Remove virtual environment

Testing (Local - uses venv):
  make test-local        Run unit tests with verbose output
  make test-local-quick  Run unit tests with minimal output
  make test-local-cov    Run unit tests with coverage report (HTML)

Testing (E2E - on the Wi-Lab machine, against the running service):
  make test-e2e          API + server checks, no USB unplug
  make test-e2e-usb      Also simulate USB unplugs (WD-4/WD-5)
  Add WILAB_E2E_SLOW=1 for long tests; see docs/e2e-testing.md

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
curl -X POST http://localhost:8080/api/v2/reservations \
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

# 2. Create a WiFi network on the reserved device (asynchronous: answers 202, "runtime_state": "starting")
curl -X POST http://localhost:8080/api/v2/reservations/a1b2c3d4/network \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" \
  -d '{"radio": {"band": "2.4ghz", "channel": 6, "tx_power_level": 4},
       "wifi": {"ssid": "TestNetwork", "security": {"encryption": "wpa2", "password": "mypassword"}}}'

# 3. Poll every 1-2 s until "runtime_state" is no longer "starting" ("active": true: the AP is up)
curl http://localhost:8080/api/v2/reservations/a1b2c3d4/network \
  -H "Authorization: Bearer change-me"

# 4. Release the reservation when done (also stops the network)
curl -X DELETE http://localhost:8080/api/v2/reservations/a1b2c3d4 \
  -H "Authorization: Bearer change-me"
```

For the full endpoint reference, open **Swagger UI** at `http://<host>:8080/docs` or **ReDoc** at `http://<host>:8080/redoc`.

---

## Documentation

Detailed guides live in the `docs/` folder:

| Document | Topic |
|----------|-------|
| [ap-creation-procedure.md](docs/ap-creation-procedure.md) | Client guide: reservation, AP creation, retries |
| [architecture.md](docs/architecture.md) | Backend architecture, threads, AP pipeline, recovery, manual adapter recovery |
| [swagger.md](docs/swagger.md) | API exploration via Swagger UI |
| [error-codes.md](docs/error-codes.md) | Every API error code (`detail.code`), its HTTP status and the client action |
| [networking.md](docs/networking.md) | Subnet layout, iptables, NAT internals |
| [qos.md](docs/qos.md) | QoS profiles (experimental): catalogue, playback modes, API |
| [unit-testing.md](docs/unit-testing.md) | Test suite structure and pytest usage |
| [e2e-testing.md](docs/e2e-testing.md) | End-to-end tests against the running service on real adapters |
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
