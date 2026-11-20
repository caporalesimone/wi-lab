# Wi-Lab backend architecture

This document describes how the Wi-Lab backend works: components, startup,
threads and locks, the reservation lifecycle, the AP creation pipeline in
detail, the retry layers, the watchdog and automatic USB recovery. The client
side of AP creation is described in [AP creation procedure](ap-creation-procedure.md).

## 1. Overview

Wi-Lab is a single Python process (FastAPI served by Uvicorn) that turns Wi-Fi
adapters into isolated access points on demand. It does not implement Wi-Fi
itself: it drives standard Linux tools and keeps all orchestration state in
memory.

```mermaid
flowchart LR
    subgraph Clients
        UI["Angular dashboard"]
        API["API clients / Swagger"]
    end

    subgraph Process["Wi-Lab process (Uvicorn + FastAPI)"]
        R["Routes /api/v1<br/>reservation, network, internet,<br/>txpower, qos, status"]
        D["dependencies.py<br/>singletons and discovery service"]
        RM["ReservationManager<br/>reservations, quarantine"]
        NM["NetworkManager<br/>AP lifecycle, device locks"]
        WD["NetworkWatchdog<br/>one thread per antenna"]
        RR["RadioRecovery<br/>USB reset worker"]
        CM["ChannelManager<br/>channel cache"]
        DISC["discovery.py<br/>antenna detection"]
        subgraph Drivers["Linux wrappers"]
            HA["HostapdManager"]
            DH["DhcpServer"]
            NAT["NatManager"]
            ISO["IsolationManager"]
            QOS["QosManager / QosProfileManager"]
        end
    end

    subgraph Linux
        HOSTAPD["hostapd + hostapd_cli"]
        DNSMASQ["dnsmasq"]
        IPT["iptables"]
        TC["tc / ifb"]
        IPIW["ip / iw / nmcli / udevadm"]
        USB["usbreset / sysfs"]
    end

    UI --> R
    API --> R
    R --> D
    D --> RM
    D --> NM
    D --> CM
    D --> DISC
    NM --> WD
    NM --> RR
    NM --> HA
    NM --> DH
    NM --> NAT
    NM --> ISO
    NM --> QOS
    HA --> HOSTAPD
    HA --> IPIW
    DH --> DNSMASQ
    NAT --> IPT
    ISO --> IPT
    QOS --> TC
    DISC --> IPIW
    CM --> IPIW
    RR --> USB
```

### Source layout

| Path | Responsibility |
|---|---|
| `main.py` | Process entry point: logging, safety checks, configuration, Uvicorn. |
| `wilab/config.py` | YAML configuration, antenna selection for each scan (names, `disable`, order). |
| `wilab/wifi/discovery.py` | Detects AP-capable Wi-Fi interfaces, udev readiness, USB port, default routes. |
| `wilab/api/__init__.py` | FastAPI app, lifespan (startup/shutdown), error handlers, frontend static files, OpenAPI. |
| `wilab/api/dependencies.py` | Lazily created singletons, `hold_reservation`, device scan and discovery service. |
| `wilab/api/routes/*.py` | HTTP endpoints. `network.py` contains the creation retry contract. |
| `wilab/reservation.py` | In-memory reservation store, expiry, quarantine state. |
| `wilab/wifi/manager.py` | `NetworkManager`: start/stop pipeline, device locks, expiry loop, TX power. |
| `wilab/wifi/hostapd.py` | hostapd configuration, process ownership, readiness check. |
| `wilab/wifi/watchdog.py` | Post-start supervision and bounded AP/DHCP restoration. |
| `wilab/wifi/recovery.py` | Automatic USB reset and verification of quarantined antennas. |
| `wilab/wifi/channels.py` | Regulatory domain and per-interface channel cache. |
| `wilab/network/dhcp.py` | dnsmasq configuration and process tracking. |
| `wilab/network/nat.py`, `isolation.py` | iptables NAT to the upstream interface and inter-AP isolation. |
| `wilab/network/qos.py`, `qos_profile.py` | Traffic shaping (HTB, netem, IFB) and QoS profiles. |
| `wilab/network/commands.py` | Bounded command execution, foreground process ownership. |

## 2. Startup and device discovery

Wi-Lab starts **without antennas**. A device discovery service, started with the
API, finds them and keeps looking for new ones for the whole life of the process.

```mermaid
sequenceDiagram
    autonumber
    participant SD as systemd
    participant M as main.py
    participant C as config.py
    participant U as Uvicorn
    participant L as lifespan
    participant NM as NetworkManager
    participant D as device-discovery thread
    participant RM as ReservationManager

    SD->>M: start wi-lab.service
    M->>M: log version, host impact warning
    M->>M: check leftover Wi-Lab iptables rules
    M->>C: load_config()
    C->>C: read config.yaml and validate (no antenna managed yet)
    C-->>M: AppConfig with an empty antenna pool
    M->>U: run app on 0.0.0.0:8080
    U->>L: lifespan startup
    L->>C: get_config() (runtime instance)
    L->>NM: get_manager() creates NetworkManager
    NM->>NM: start expiry thread (every 5 s)
    L->>L: set regulatory domain (iw reg set)
    L->>D: start device discovery
    L-->>U: ready, serve requests
    D->>RM: first scan, immediately: create ReservationManager,<br/>start watchdogs, add the antennas found
    loop for the whole process lifetime
        D->>D: wait 5 s while no antenna is managed, otherwise 30 s
        D->>RM: scan again and add new antennas
    end
```

Notes:

- `main.py` loads the configuration only to fail fast on an invalid file. The
  runtime instance is loaded again in the lifespan through `get_config()`.
- Until the first scan adds an antenna, reservations return `503 / 1003`. The
  first scan runs as soon as the API starts, so this window is normally short.
- The first scan creates `ReservationManager` through
  `get_reservation_manager()`: it receives the device-lock provider and
  `release_device` as its cleanup callback, connects the expiry hook and starts
  the watchdog. Each antenna added later gets its own watchdog thread.

### Discovery service

```mermaid
flowchart TD
    S["device-discovery thread starts with the API"] --> SC["scan now<br/>(only the first scan logs configuration warnings)"]
    SC --> A{"new AP-capable antennas?"}
    A -->|yes| ADD["append to the pool, register in ReservationManager,<br/>start a watchdog, warm the channel cache"]
    A -->|no| N
    ADD --> N{"pool still empty?"}
    N -->|yes| F["wait 5 s"]
    N -->|no| SL["wait 30 s"]
    F --> SC
    SL --> SC
    F -.->|shutdown| X["stop"]
    SL -.->|shutdown| X
```

Each scan (`scan_devices()`):

1. Serializes with the scan lock.
2. Re-reads `networks` from `config.yaml`, so new display names and `disable`
   flags apply to antennas found later.
3. Discovers radios and keeps only those not already managed (by interface and
   by phy), not disabled and not upstream.
4. Appends them to the pool: existing antennas keep their position and subnet.

A scan never removes, disables or renames an antenna already in the pool; that
requires a service restart. A failed scan (for example an invalid
`config.yaml`) is logged once and retried at the next interval. Periodic scans
log at debug level, so they do not fill the journal.

The cost is small: on a host with two USB antennas a scan takes about 30 ms of
wall time and about 20 ms of CPU, running 7 short commands (`ip`, `iw`,
`udevadm`). A scan does not take device locks and does not touch the radios, so
it does not disturb running APs.

### Antenna detection

```mermaid
flowchart TD
    A["iw dev: list phy and interfaces"] --> B{"phy supports AP mode?<br/>(iw phy info)"}
    B -->|no| X1["skip"]
    B -->|yes| C{"udev initialized and<br/>INTERFACE, IFINDEX, ID_NET_NAME<br/>match the current name?"}
    C -->|"no, rename in progress"| W["wait 0.25 s and enumerate again<br/>(up to 5 snapshots)"]
    W --> A
    C -->|yes| P["read USB port from sysfs<br/>(2-1:1.0 belongs to port 2-1)"]
    P --> E{"interface carries a default route<br/>or is upstream_interface?"}
    E -->|yes| X2["skip"]
    E -->|no| F{"listed with disable: true?<br/>(excludes the whole radio)"}
    F -->|yes| X3["skip"]
    F -->|no| G{"already managed, or another interface<br/>of the same phy already selected?"}
    G -->|yes| X4["skip"]
    G -->|no| H["add NetworkEntry<br/>display_name from config or interface name"]
    H --> O["order within one scan: configured entries first<br/>(config order), then others sorted by name"]
```

An interface still being renamed by udev is skipped, never saved under its
temporary kernel name; the next scan picks it up with its final name.

The AP allocator scans `/24` subnets from `dhcp_base_network` in antenna pool
order, skipping overlaps with host IPv4 routes and subnets assigned to other
antennas. It checks routes before a new AP start and reuses the antenna's previous
assignment if still safe. Newly discovered antennas are appended; active APs
keep their subnet. Antennas found by the same scan follow the configured order.

## 3. Concurrency model

Route handlers are synchronous (`def`), so Starlette runs them in its worker
thread pool, not in the event loop. Every Linux command is therefore blocking
but isolated to one worker thread.

```mermaid
flowchart TB
    subgraph EventLoop["Main thread"]
        EL["Uvicorn asyncio event loop"]
    end
    subgraph Pool["Starlette worker threads"]
        H1["request handler"]
        H2["request handler"]
    end
    subgraph Background["Daemon threads"]
        EX["expiry loop (5 s)<br/>stop expired APs, sweep reservations"]
        WDT["ap-watchdog-ANTENNA (5 s)<br/>one per antenna"]
        UR["usb-recovery-ANTENNA<br/>one per quarantined USB antenna"]
        DS["device-discovery<br/>every 5 s while no antenna, then every 30 s"]
        CC["channel-cache-scan<br/>one-shot per added antenna"]
    end
    subgraph Children["Child processes"]
        HP["hostapd (foreground child, one per AP)"]
        DQ["dnsmasq (daemon, PID file)"]
        SC["short commands: ip, iw, hostapd_cli,<br/>iptables, tc, nmcli, udevadm, usbreset"]
    end
    EL --> Pool
    Pool --> Children
    Background --> Children
```

### Locks

| Lock | Owner | Protects |
|---|---|---|
| Device lock (`RLock` per antenna) | `NetworkManager.device_lock()` | Start, stop, status, cleanup, watchdog restore and USB recovery of one antenna. Different antennas never wait for each other. |
| Store lock | `ReservationManager._lock` | Reservation maps and quarantine state. Held only briefly. |
| Firewall lock | `NetworkManager._firewall_lock` | iptables changes (NAT, isolation) shared by all antennas. |
| Scan lock | `dependencies._scan_lock` | One device scan at a time. |
| Singleton lock | `dependencies._singleton_lock` | Lazy creation of the managers. |

Rules:

- Lock order is **device lock, then store lock**. Code never waits for a
  device lock while holding the store lock.
- `hold_reservation()` takes the device lock and re-checks that the
  reservation is still current, so a concurrent release cannot free the
  antenna in the middle of an operation.
- Background loops (expiry, watchdog) use non-blocking acquisition: a busy
  antenna is skipped until the next tick instead of blocking the loop.
- `GET /api/v1/status` reads snapshots and never waits for a device lock or
  runs cleanup, so it stays responsive while an antenna is slow. It still runs
  host health commands and is not a latency guarantee.

## 4. Reservation lifecycle

```mermaid
stateDiagram-v2
    state "Free" as Free
    state "Reserved" as Reserved
    state "Releasing (cleanup under device lock)" as Releasing
    state "Quarantined, recovering" as Recovering
    state "Quarantined, unavailable" as Unavailable

    [*] --> Free
    Free --> Reserved: POST device-reservation
    Reserved --> Reserved: create, stop, restart AP
    Reserved --> Releasing: DELETE reservation or expiry
    Releasing --> Free: cleanup succeeded
    Releasing --> Reserved: cleanup failed, 503 1004, antenna still held
    Reserved --> Recovering: terminal failure on a USB antenna
    Reserved --> Unavailable: terminal failure, no USB reset allowed
    Recovering --> Free: reset and AP/DHCP probe verified
    Recovering --> Unavailable: 10 rounds failed
    Unavailable --> [*]: until service restart
```

- A reservation holds `reservation_id` (8 hex chars), `device_id`,
  `expires_at` (`None` when unlimited), the radio failure counter
  `radio_failures`, the cooldown deadline `retry_at` and a counter of releases
  in progress.
- **Allocation** picks the first antenna in pool order that is neither reserved
  nor quarantined. When none is free, expired reservations are purged first;
  then the response is `409 / 1005` (busy), `503 / 1002` (an antenna is
  recovering) or `503 / 1003` (all quarantined, or no antenna).
- **Expiry** is enforced in two places: lazily when the ID is used (the request
  gets `404` after cleanup) and by the expiry loop every 5 seconds.
- **Release** cleans up first and frees the antenna only if cleanup succeeded.
- **Quarantine** removes the reservation and marks the antenna as blocked in a
  single store operation, so the ID becomes `404` and the antenna cannot be
  allocated.
- Everything is in memory. A restart loses reservations and quarantine; it does
  not repair a failing radio.

## 5. AP creation in detail

### 5.1 Request pipeline

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as network.py route
    participant RM as ReservationManager
    participant CH as ChannelManager
    participant NM as NetworkManager
    participant HA as HostapdManager
    participant OS as ip / iw / hostapd
    participant DH as DhcpServer
    participant FW as NAT / isolation

    C->>R: POST /interface/{id}/network
    R->>R: require_token (401)
    R->>RM: resolve_reservation (404 if unknown, expired, invalidated)
    R->>R: watchdog restoring this AP? (409)
    R->>RM: hold_reservation: take device lock, re-check (404)
    R->>R: cooldown retry_at in the future? (409 / 1001, remaining)
    R->>CH: validate_channel (422)
    R->>NM: start_network(allow_internal_retry = no failures yet)
    NM->>NM: retry deadline = now + 5 s, capped by expiry
    NM->>NM: known antenna, not already active (409)
    NM->>NM: release_device: clear leftovers of a failed start
    NM->>NM: select available subnet, gateway .1
    NM->>OS: validate interface exists, is wireless, supports AP
    NM->>OS: nmcli device set unmanaged (best effort)
    NM->>HA: start(ssid, channel, band, encryption, ...)
    HA->>HA: write hostapd.conf in a private temp dir with ctrl socket
    HA->>OS: ip link down, iw set type managed, ip addr flush
    HA->>OS: spawn hostapd in foreground
    loop until ENABLED, DISABLED or timeout (10 s, 75 s for DFS)
        HA->>OS: process alive? hostapd_cli status on private socket
    end
    HA-->>NM: AP enabled for this interface and SSID
    NM->>OS: ip addr add gateway
    NM->>DH: start: write config, dnsmasq --test, launch, read PID
    alt any step failed
        NM->>NM: release_device rollback
        NM->>NM: internal retry once, or raise StartupFailure
    end
    NM->>OS: set TX power level (best effort)
    NM->>FW: enable NAT if internet_enabled (best effort, firewall lock)
    NM->>FW: add isolation rules (best effort, firewall lock)
    NM->>NM: active[antenna] = NetworkStatus
    NM-->>R: status
    R->>R: reset radio_failures and retry_at
    R-->>C: 200
```

### 5.2 hostapd startup and readiness

hostapd is started as a **foreground child process** owned by Wi-Lab, not as a
daemon. Wi-Lab therefore knows immediately when it exits, and how:

- exit by `SIGSEGV` → `HostapdSegfault` (a classified radio failure);
- any other exit code → `HostapdError` (unclassified);
- timeout of `ip link down`, `iw set type managed` or `ip addr flush` →
  `HostapdRadioFailure` ("radio preparation timed out");
- `hostapd_cli status` timing out → `HostapdRadioFailure`;
- state `DISABLED`, or not `ENABLED` with the right interface and SSID within
  the timeout → `HostapdRadioFailure` ("AP not ready").

The AP is ready only when `hostapd_cli` on the instance's private control
socket reports `state=ENABLED`, `bss[0]` equal to the interface and `ssid[0]`
equal to the requested SSID. The timeout is 10 seconds, or 75 seconds for
5 GHz DFS channels 52–144 because of the radar check. The configuration enables
`ieee80211d` on all bands and `ieee80211h` on 5 GHz.

Only after the AP is confirmed does Wi-Lab assign the gateway and start DHCP:
the order is **AP → gateway → DHCP**.

On readiness failure, Wi-Lab logs one `hostapd startup failure` entry with the
interface, elapsed time and budget, socket presence, last known state, last
probe outcome, and any observed exit code. The child output is continuously
drained; only the last twelve allowlisted event labels are kept in memory and
included in the failure entry. This diagnostic never includes raw child
output, SSIDs or credentials and creates no additional file. It does not change
readiness deadlines or retry classification. An exit code of `1` alone does
not identify the cause.

### 5.3 Rollback and teardown

On any failure the start is rolled back with `release_device()`, which runs the
normal teardown. The same teardown is used by stop, release, expiry, watchdog
and recovery:

```mermaid
flowchart LR
    A["clear QoS profile and tc rules"] --> B["stop hostapd: terminate, then kill<br/>remove config and ctrl socket"]
    B --> C["interface down, managed mode, flush addresses"]
    C --> D["disable NAT (firewall lock)"]
    D --> E["remove isolation rules"]
    E --> F["stop dnsmasq"]
    F --> G{"any step failed?"}
    G -->|no| H["remove from active networks"]
    G -->|yes| I["RuntimeError: antenna stays held<br/>(unsafe cleanup)"]
```

Every step runs even if an earlier one fails, and errors are reported together.
The radio is always left `managed` and `DOWN` between networks.

## 6. Retry layers

Wi-Lab recovers from radio problems at three levels, from fastest to most
drastic.

```mermaid
flowchart TD
    S["POST create"] --> CD{"cooldown active?"}
    CD -->|yes| R0["409 / 1001 with remaining seconds<br/>no radio work, attempt not consumed"]
    CD -->|no| ST["start AP"]
    ST --> OUT{"outcome"}
    OUT -->|success| OK["200, counter reset"]
    OUT -->|"segfault on 2.4 GHz, first attempt of the sequence,<br/>at least 1.5 s of the 5 s budget left"| IR["layer 1: rollback, wait 0.75 s,<br/>retry once inside the same request"]
    IR --> OUT2{"retry outcome"}
    OUT2 -->|success| OK
    OUT2 -->|"AP start failed again"| CL
    OUT2 -->|"gateway or DHCP failed"| G
    OUT -->|"unclassified: exit code, gateway, DHCP,<br/>interface validation"| G["500 generic<br/>reservation kept, no counter change"]
    OUT -->|classified radio failure| CL["radio_failures += 1"]
    OUT -->|rollback failed| Q
    CL --> N{"radio_failures"}
    N -->|1| R5["layer 2: 409 / 1001, Retry-After 5"]
    N -->|2| R10["layer 2: 409 / 1001, Retry-After 10"]
    N -->|3| Q["layer 3: quarantine antenna, invalidate reservation<br/>500 / 1003"]
    Q --> U{"USB antenna, radio fault,<br/>not upstream?"}
    U -->|yes| REC["schedule USB recovery<br/>recovery_state = recovering"]
    U -->|no| UN["recovery_state = unavailable"]
```

| Layer | Where | Trigger | Limit |
|---|---|---|---|
| 1. Internal retry | Inside one request (`NetworkManager`) | hostapd segfault on 2.4 GHz, first request of the sequence | Once, within a 5 s budget capped by expiry. If the AP fails to start again, it counts as a radio failure. |
| 2. Client retry with cooldown | Across requests (route + `Reservation`) | Classified radio failure | 3 attempts per sequence, cooldowns 5 s and 10 s. Success resets the counter. |
| 3. Quarantine and USB recovery | Background worker | 3rd classified failure, unsafe rollback, or a failed watchdog restart | 10 rounds at least 60 s apart, USB antennas only. |

An unclassified startup failure with successful rollback returns `500 / 500`
without `Retry-After`. It does not consume the radio budget, but the reservation
still holds the antenna. `release_device()` in the rollback cleans up the
network; it does not delete the reservation. The client can release the ID
explicitly when it no longer needs it. Success after releasing and reserving
the same antenna again shows reuse worked, not that retrying with the original
ID would have worked.

Do not classify an isolated hostapd exit code `1` as a radio failure based on
the exit code alone: that would also make persistent non-radio failures eligible
for quarantine after three attempts. A more specific transient failure signal
would be needed before routing these exits through the cooldown path.

## 7. After start: watchdog

Each antenna has a watchdog thread that wakes up every 5 seconds.

```mermaid
flowchart TD
    T["tick every 5 s"] --> L{"device lock free?"}
    L -->|no| T
    L -->|yes| A{"active AP with a current reservation,<br/>not expired, not being released?"}
    A -->|no| CLR["clear runtime_state"] --> T
    A -->|yes| P{"hostapd process alive?"}
    P -->|no| RA
    P -->|yes| E{"AP ENABLED?"}
    E -->|no| M["misses += 1"] --> M3{"3 misses in a row?"}
    M3 -->|no| T
    M3 -->|yes| RA
    E -->|yes| DH{"dnsmasq running?"}
    DH -->|yes| T
    DH -->|"no, first time"| RD["restoring_dhcp: restart dnsmasq only"]
    DH -->|"no, already restarted"| DF["runtime_state = dhcp_failed<br/>AP stays up"]
    RA{"AP already restarted once<br/>for this network?"}
    RA -->|no| RS["restoring_ap: teardown, start again with the<br/>original settings, no internal retry"]
    RA -->|yes| Q["quarantine, invalidate reservation"]
    RS -->|success| T
    RS -->|"radio failure or unsafe cleanup"| Q
    RS -->|"other failure"| STOP["AP stopped, reservation kept"]
    RD -->|"cleanup unsafe"| Q2["teardown, quarantine without USB reset"]
```

- No connected stations is not a failure.
- The restart keeps the reservation and its expiry. Clients must reconnect; QoS
  is cleared by the teardown and must be reapplied.
- Release or expiry cancels a pending restart. If a restart already ran, its
  result is cleaned up under the device lock before the antenna can be reused.
- `POST create` returns `409` while `restoring_ap` or `restoring_dhcp` is set.

## 8. Quarantine and automatic USB recovery

A quarantined antenna is excluded from allocation. If it is a USB adapter
(detected from sysfs at discovery), the failure was a radio fault and it is not
the upstream interface, Wi-Lab starts a recovery worker for it.

```mermaid
sequenceDiagram
    autonumber
    participant RT as Route or watchdog
    participant RM as ReservationManager
    participant WK as Recovery worker
    participant NM as NetworkManager
    participant K as Kernel / USB / sysfs

    RT->>RM: quarantine(reservation, recovering)
    RT->>WK: schedule(antenna, port, band, channel)
    loop up to 10 rounds, at least 60 s apart
        WK->>NM: take device lock, release_device
        WK->>K: precheck: managed, DOWN, no default route
        WK->>K: map interface to port: function port:1.0, not a hub,<br/>single function, single netdev
        WK->>K: same MAC as the first round
        WK->>K: usbreset BUS/DEV (timeout 15 s)
        WK->>K: wait up to 10 s for the same MAC on the same port
        WK->>K: down, managed, up, down, idle again
        WK->>NM: probe: hidden WPA2 AP with random key on the failed channel,<br/>gateway, DHCP without router and DNS
        NM->>K: AP ENABLED and dnsmasq running?
        WK->>NM: teardown probe, require managed and DOWN
        Note over WK: success leaves the loop
    end
    WK->>RM: finish_recovery(recovered)
    Note over RM: recovered: antenna allocatable again<br/>otherwise: unavailable until restart
```

- A failed precheck skips the reset for that round.
- The probe is a server-side check only: it does not prove that a real station
  can associate and get a lease.
- Other antennas stay fully available during recovery.
- For hardware that does not recover, use the
  [manual recovery procedure](manual_recovery.md).

## 9. Expiry and shutdown

```mermaid
sequenceDiagram
    participant EX as Expiry thread
    participant NM as NetworkManager
    participant RM as ReservationManager

    loop every 5 s
        EX->>NM: for each active AP past expires_at
        NM->>NM: stop_network (skip if the device lock is busy)
        EX->>RM: expire(): release expired reservations, cleanup first
    end
```

On shutdown (`SIGTERM` from systemd) the lifespan stops device discovery, waits
briefly for it and calls `shutdown_all()`: it stops the recovery
worker and the watchdogs, then runs `release_device()` for every antenna so that
no hostapd, dnsmasq, iptables or tc state is left behind.

## 10. Host state and files

| State | Location | Lifetime |
|---|---|---|
| Reservations, quarantine, active networks, watchdog states | Process memory | Lost on restart. |
| hostapd configuration and control socket | `/tmp/wilab-hostapd/ap-*/` | Removed at teardown. Contains the WPA passphrase. |
| dnsmasq configuration, leases, PID | `/tmp/wilab-dnsmasq/` | Removed at teardown. |
| NAT and isolation rules | iptables `nat` and `FORWARD` | Removed at teardown. Leftovers are reported at startup. |
| Traffic shaping | tc qdiscs, IFB devices | Removed at teardown. |

The upstream interface is resolved from the default route on first use and
cached; set `upstream_interface` to force it.

## 11. Observability

- Every API `5xx` logs `API failure operation=<route> http_status=<code>
  detail_code=<code>` without IDs, tokens or bodies:
  `journalctl -u wi-lab.service -g 'API failure operation='`.
- Discovery logs every added antenna with its USB port (or `non-USB`) and
  subnet. The first scan also logs skipped interfaces with the reason.
- `GET /api/v1/status` exposes `runtime_state` (watchdog) and `recovery_state`
  (quarantine) per antenna. `GET /api/v1/debug` gives a detailed, slower
  snapshot for troubleshooting.

## 12. Known limitations

- **A USB reset stuck in the kernel blocks its antenna.** If `usbreset` enters
  an uninterruptible kernel state, its timeout cannot terminate it. The recovery
  thread then waits forever while holding that antenna's device lock: the
  antenna stays `recovering`, and service shutdown also waits on that lock until
  systemd kills the process. Other antennas keep working. Recovering the adapter
  then requires unplugging it or restarting the VM or host.
- Antennas are added at runtime but never removed: an antenna unplugged while in
  the pool stays listed until the service restarts.
- All coordination state is in memory and assumes a single Wi-Lab process per
  host.
