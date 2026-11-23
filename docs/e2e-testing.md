# Wi-Lab End-to-End Testing

The end-to-end (e2e) tests in `tests/e2e-tests/` exercise the real service on real Wi-Fi adapters.
Each test combines API calls with actions on the server: reading the journal, checking the air
interface with `iw`, and simulating a USB unplug through sysfs.

The unit tests in `tests/unit-tests/` mock every host command and run anywhere (see
[unit-testing.md](unit-testing.md)). The e2e tests do not replace them; they confirm on hardware
what the unit tests model.

## Where and when to run them

- Run them **on the Wi-Lab machine**, against the service that is running there. Server actions
  (`journalctl`, `iw`, `/sys/bus/usb/...`) are local.
- The service must run the code under test. After a change, restart it
  (`sudo systemctl restart wi-lab`).
- Run them only when nobody else is using the service. Every test first reads `/status` and skips
  itself if an antenna is reserved or not healthy, so it never takes over another run.
- The tests reserve antennas, create networks and release everything at the end. A simulated
  unplug is always undone at the end of the session, even when a test fails.

## Enabling the suite

The suite is skipped unless enabled through environment variables, so `pytest` and CI never
touch hardware by accident.

| Variable | Default | Purpose |
|---|---|---|
| `WILAB_E2E=1` | off | Enable the suite. |
| `WILAB_E2E_USB=1` | off | Allow simulated USB unplugs (`authorized` 0 → 1). |
| `WILAB_E2E_USB_ACTIVE_AP=1` | off | Also allow an unplug while an AP is running (see the warning below). |
| `WILAB_E2E_SLOW=1` | off | Allow long tests (15 minutes or more). |
| `WILAB_E2E_URL` | `http://localhost:8080` | API base URL. |
| `WILAB_E2E_TOKEN` | `auth_token` from the config | Bearer token. |
| `WILAB_E2E_CONFIG` | `<repo>/config.yaml` | Config file to read the token from. |
| `WILAB_E2E_SUDO_FILE` | `~/.wilabsudo` | File whose first line is the sudo password, mode `600`. Needed only for USB tests. |
| `WILAB_E2E_CYCLES` | `10` | Create/delete cycles per antenna in the stability test. |

```bash
make test-e2e                    # API + server checks, no USB unplug (about 20 s)
make test-e2e-usb                # also simulated unplugs without an active AP (about 2 min)
WILAB_E2E_SLOW=1 make test-e2e-usb   # also WD-4 and the 15-minute network (about 30 min)
WILAB_E2E_CYCLES=50 make test-e2e    # longer create/delete soak
```

The sudo password is used with `sudo -k -S` and is never printed. Only `tee` on the USB
`authorized` attribute runs as root.

## What the tests cover

| File | Test | Fable IDs | Server actions |
|---|---|---|---|
| `test_e2e_create_validation.py` | Invalid create requests return `422` and never reach hostapd. Valid ones, including SSIDs with UTF-8, quotes, backslashes or `hidden: true`, return `200` on the first attempt, and `iw` shows the expected SSID on the air. | BUG-1, HAP-1 | `iw dev <if> info` |
| `test_e2e_stability.py` | Create/delete cycles on every antenna in parallel: all `200`, no quarantine, no traceback in the journal. | HAP-1 | journal |
| `test_e2e_stability.py` (slow) | A network with a non-ASCII SSID stays up 15 minutes with no `runtime_state`, `recovery_state` or `degraded`. | HAP-1 | `iw`, journal |
| `test_e2e_device_loss.py` (usb) | Antenna gone at create: `409/1001` with `Retry-After: 5`, no quarantine, `200` after it is back. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb) | Free antenna unplugged and replugged: no quarantine, next create `200`. | WD-5 | unplug |
| `test_e2e_device_loss.py` (usb) | Antenna gone across three creates: `409/1001` (5 s), `409/1001` (10 s), `500/1003`; antenna `recovering` and service `degraded`; back to free through USB recovery after the replug. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb, active AP) | Antenna gone for 30 s with a network running: the network is restored, or the reservation is invalidated and the antenna recovers; never permanently `unavailable`. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb, slow) | Antenna gone for more than 11 minutes: USB recovery exhausts and the antenna becomes `unavailable`; after the replug the re-probe makes it free again without a restart. | WD-4 | unplug, journal |
| `test_e2e_watchdog.py` | hostapd killed twice with `kill -9`: each time the watchdog restores the AP (`active`, no `runtime_state`), with no quarantine and the reservation kept. | WD-1 | `kill`, `iw`, journal |
| `test_e2e_watchdog.py` | hostapd killed while UDP port 67 is held on the interface, so the restore fails on dnsmasq: `runtime_state: restore_failed`, `active: false`, service `degraded`, no quarantine; after the port is freed a retry restores the AP. | WD-2 | `kill`, port 67 holder, journal |
| `test_e2e_watchdog.py` | Same failure, then `DELETE .../network`: `200`, retries stop, the reservation stays valid and a new create works. | WD-2 | `kill`, port 67 holder |
| `test_e2e_watchdog.py` | dnsmasq killed twice: each time the watchdog restarts DHCP alone, the AP stays up, no network restore and no quarantine. | WD-3 | `kill`, journal |
| `test_e2e_watchdog.py` | dnsmasq killed while UDP port 67 is held: the DHCP restart fails, the watchdog restores the whole network, which fails on DHCP too (`restore_failed`); after the port is freed the network comes back. | WD-3, WD-2 | `kill`, port 67 holder, journal |
| `test_e2e_firewall.py` | Parallel create/delete on every antenna while `/status` is polled every 0.2 s: all `200`, no quarantine, no "xtables lock" error in the journal. | NET-1 | journal |
| `test_e2e_firewall.py` | Legacy backend only: another process holds the xtables lock for 2 s; a create waits and returns `200`. Skipped on nf_tables. | NET-1 | `flock /run/xtables.lock` |
| `test_e2e_firewall.py` | A `200` create has the firewall it reports: with `internet_enabled: true` the MASQUERADE and FORWARD rules exist in iptables, with `false` there is no MASQUERADE rule; the journal shows "Isolation rules applied" and never "Isolation disabled for testing"; delete removes the rules. The failure path has no safe live trigger and is covered by unit tests. | NET-2, NET-4 | `iptables -S` (root), journal |
| `test_e2e_api.py` | API-only checks from the tester's plan: path traversal on static files (SEC-1), reservation IDs in `/debug` (SEC-2), unknown create field (API-10), create response body (API-5), status code of actions without a network (API-2), `wpa2-wpa3` and `wpa` (HAP-10), `/status` with an Internet-less network (BUG-2), TX power reported vs `iw` (BUG-7), TX power change time (PERF-6), `/status` read in a tight loop during create/delete (RACE-2). | SEC-1, SEC-2, API-2, API-5, API-10, HAP-10, BUG-2, BUG-7, PERF-6, RACE-2 | `iw` (BUG-7 only) |

Tests in `test_e2e_api.py` use only the public API (except the `iw` comparison for BUG-7), so
they give the same result from an external machine. Tests for IDs that are not fixed yet are
marked `xfail` (not strict): pytest reports them as `XFAIL` until the fix lands and as `XPASS`
afterwards, when the mark is removed.

The watchdog budgets (3 AP restores and 3 DHCP restarts per hour per antenna) live in the running
service, so tests that kill hostapd or dnsmasq use them up. Each of those tests counts the
"Restoring AP on" and "Restarting DHCP on" lines in the journal for the last hour of the current
service run, reserves an antenna that still has the budget it needs, and skips itself when none
has: wait an hour or restart the service.

The tests pick the first antenna listed in `/status` and find its USB port from sysfs, so no
port is hard-coded.

## Warning: unplug with an active AP

On the mt7921u adapters in the Wi-Lab VM, re-authorizing a USB device right after an active AP
lost it has made the firmware time out, stalled the VM for about 60 seconds and made QEMU detach
the device from the VM. The adapter then needed a physical re-plug, because the Proxmox host no
longer saw it either. For this reason the active-AP test needs its own flag,
`WILAB_E2E_USB_ACTIVE_AP=1`. Run it only when someone can reach the machine.

## Adding a test

- Put helpers in `tests/e2e-tests/wilab_e2e.py` (`Server` for server actions, `WiLab` for the
  API) and fixtures in `tests/e2e-tests/conftest.py`.
- Reserve antennas only through `wilab.reserve()`, so they are released at the end.
- Mark tests with `@pytest.mark.usb`, `@pytest.mark.usb_active_ap` or `@pytest.mark.slow` when
  they need the matching flag.
- Assert on the API response (status, `detail.code`, `Retry-After`), on `/status`, and on the
  journal lines that prove the code path, as the existing tests do.
