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
| `WILAB_E2E_RESTART=1` | off | Allow tests that kill and restart the service (every client loses its reservations). |
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
| `test_e2e_device_loss.py` (usb) | Antenna gone at create and back during the server's 5 s pause: one create answers `200`, no quarantine. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb) | Free antenna unplugged and replugged: no quarantine, next create `200`. | WD-5 | unplug |
| `test_e2e_device_loss.py` (usb) | Antenna gone for a whole create: the polling ends with `404` (`reservation_invalidated`) after the server's 5 s and 10 s pauses; antenna `recovering` and service `degraded`; back to free through USB recovery after the replug. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb, active AP) | Antenna gone for 30 s with a network running: the network is restored, or the reservation is invalidated and the antenna recovers; never permanently `unavailable`. | WD-5 | unplug, journal |
| `test_e2e_device_loss.py` (usb, slow) | Antenna gone for more than 11 minutes: USB recovery exhausts and the antenna becomes `unavailable`; after the replug the re-probe makes it free again without a restart. | WD-4 | unplug, journal |
| `test_e2e_watchdog.py` | hostapd killed twice with `kill -9`: each time the watchdog restores the AP (`active`, no `runtime_state`), with no quarantine and the reservation kept. | WD-1 | `kill`, `iw`, journal |
| `test_e2e_watchdog.py` | hostapd killed with `kill -SEGV` (as the 47 crashes of the 2-hour run): the control connection notices, wakes the watchdog, and a new hostapd brings the network back in under 15 s (printed), `restarts.ap` 1 with `hostapd_not_running`, one restore in the journal, no quarantine, "Control connection ... lost" in the journal. | PERF-4, WD-1 | `kill`, journal |
| `test_e2e_watchdog.py` | hostapd killed while UDP port 67 is held on the interface, so the restore fails on dnsmasq: `runtime_state: restore_failed`, `active: false`, service `degraded`, no quarantine; after the port is freed a retry restores the AP. | WD-2 | `kill`, port 67 holder, journal |
| `test_e2e_watchdog.py` | Same failure, then `DELETE /access-point/{reservation_id}`: `200`, retries stop, the reservation stays valid and a new create works. | WD-2 | `kill`, port 67 holder |
| `test_e2e_watchdog.py` | dnsmasq killed twice: each time the watchdog restarts DHCP alone, the AP stays up, no network restore and no quarantine. | WD-3 | `kill`, journal |
| `test_e2e_watchdog.py` | dnsmasq killed while UDP port 67 is held: the DHCP restart fails, the watchdog restores the whole network, which fails on DHCP too (`restore_failed`); after the port is freed the network comes back. | WD-3, WD-2 | `kill`, port 67 holder, journal |
| `test_e2e_watchdog.py` | hostapd killed once, then dnsmasq once: `GET /access-point/{reservation_id}` reports `restarts.ap` 1 with `last_reason: hostapd_not_running`, then `restarts.dhcp` 1 with `dnsmasq_not_running`, `last_at` inside the test; a stop and a new create keep the counters, a new reservation starts from zero. | e2e-test-6 | `kill` |
| `test_e2e_watchdog.py` | hostapd killed, then a create with another SSID sent in a loop while the watchdog restores the AP: only `409 / 1009` (seen at least once, or `runtime_state: restoring_ap`), `409 / 1008` or `503 / 1006`, never a `202` or a second hostapd; afterwards the network's own body answers `200`. | e2e-test-7 | `kill`, `pgrep` |
| `test_e2e_start_stop.py` | UDP port 67 held on the interface before the create: the polling ends in `runtime_state: start_failed` with `error` 1013, stage `dhcp`; the reservation stays, no hostapd, no AP, no Wi-Lab rule, `/status` not `degraded`; `DELETE /access-point/{reservation_id}` answers `200` and a new create works. | e2e-test-1 | port 67 holder, `iw`, `iptables -S` (root) |
| `test_e2e_start_stop.py` | `DELETE /access-point/{reservation_id}` during a start (on DFS channel 52 when offered, so the stop lands in the radar check): `200`, or `503 / 1006` and then `200`; the reservation stays, `active: false` with no `runtime_state`, nothing left, the next create works. | e2e-test-2 | `iw`, `iptables -S` (root) |
| `test_e2e_start_stop.py` | hostapd frozen with `SIGSTOP`, then `DELETE /access-point/{reservation_id}`: the answer comes within 20 s; `200` (SIGKILL ends a stopped process), or `503 / 1012` with `Retry-After: 5`, `stop_failed` in `GET`, a create `409 / 1012`, and after `SIGCONT` the DELETE answers `200`. Nothing left either way; the next create works. | e2e-test-8 | `kill -STOP/-CONT`, `iw`, `iptables -S` (root) |
| `test_e2e_start_stop.py` | A reservation of `min_seconds` (60 s) expires with its network running: within about 10 s `GET /access-point/{reservation_id}` answers `404 reservation_expired`, the radio is not an AP, no rule is left, `/status` shows `reservation: null` and `access_point_active: false`. About 75 s. | e2e-test-9 | `iw`, `iptables -S` (root) |
| `test_e2e_captive_portal.py` | A captive portal on every antenna, created at the same time: each `captive_portal.url` is `http://<gateway>:8081/`, the nat chain `wilab-cp-<if>` sends port 80 to it, the host guard accepts 8081 and never the API port 8080, the page answers from the gateway; the chain and the listener go with the network. | e2e-test-10 | `iptables -S` (root), `ss` |
| `test_e2e_firewall.py` | The host guard jump and chain removed by hand (IPv4 and IPv6): the network check restores the network (`restarts.ap` 1, `last_reason: network_check_failed`), the guard is back, no quarantine, the stop answers `200`. | e2e-test-11 | `iptables`/`ip6tables -D`, `-F`, `-X` (only Wi-Lab's own), journal |
| `test_e2e_network_check.py` | Internet disabled with `internet/disable`: no MASQUERADE rule for the subnet, `wilab-block-<if>` rules present, `internet.enabled: false`, and the same 40 s later (one network check), with no "repaired in place" in the journal. | e2e-test-12 | `iptables -S` (root), journal |
| `test_e2e_network_check.py` | The AP gateway address and the network's MASQUERADE rule are removed by hand: within 45 s the watchdog restores both in place, the network stays active with no `runtime_state`, no quarantine. | WD-7 | `ip addr del`, `iptables -D` (only Wi-Lab's own), journal |
| `test_e2e_unclean_restart.py` (service_restart) | A network runs a QoS profile; the service main process gets `SIGKILL` and systemd restarts it: no netem/HTB qdisc and no IPv4 address left on the radio, no `wilab-ifb` device, no "Existing dnsmasq PID file", and a new create returns `200`. | STAB-4 | `systemctl kill`, `tc`, `ip`, journal |
| `test_e2e_firewall.py` | Parallel create/delete on every antenna while `/status` is polled every 0.2 s: all `200`, no quarantine, no "xtables lock" error in the journal. | NET-1 | journal |
| `test_e2e_firewall.py` | Host guard, with and without captive portal: the `wilab-in-<if>` jump is first in IPv4 and IPv6 `INPUT`, the chain accepts DHCP and ICMP (and DNS with the portal), never the API or SSH, ends with `REJECT`, and is removed with the network. A real client is needed to test the connection itself (phone test in Fable-Notes.md, 5.4). | SEC-3 | `iptables -S`, `ip6tables -S` (root) |
| `test_e2e_firewall.py` | Legacy backend only: another process holds the xtables lock for 2 s; a create waits and returns `200`. Skipped on nf_tables. | NET-1 | `flock /run/xtables.lock` |
| `test_e2e_firewall.py` | A `200` create has the firewall it reports: with `internet_enabled: true` the MASQUERADE and FORWARD rules exist in iptables, with `false` there is no MASQUERADE rule; the journal shows "Isolation rules applied" and never "Isolation disabled for testing"; delete removes the rules. The failure path has no safe live trigger and is covered by unit tests. | NET-2, NET-4 | `iptables -S` (root), journal |
| `test_e2e_api.py` | API-only checks from the tester's plan: path traversal on static files (SEC-1), `/debug` removed and no reservation IDs in `/status` (SEC-2), unknown create field (API-10), create response body (API-5), asynchronous create (`202` at once with the schema of `GET /access-point/{reservation_id}`, polling ends with the network, the same body again answers `200`), release during a start (`200` within seconds, then `404` with `reservation_released`; no hostapd, dnsmasq, Wi-Lab rule or IPv4 address left, and a reserve and create on the same antenna work at once: e2e-test-3), reserve with `interface` (that antenna; again `409 / 1005` with the first one's expiry; the other antenna still free; unknown interface `422`: e2e-test-4), `404` reasons on every call with an ID for a released, an expired (60 s wait) and an unknown ID (e2e-test-5; `reservation_invalidated` is checked in the quarantine tests of `test_e2e_device_loss.py`), Antennas API (every antenna readable with the token only, no 6 GHz channel), status code of actions without a network (API-2), every encryption checked with `hostapd_cli get_config` and `wpa` refused with `422` (HAP-10), channel width and Wi-Fi generation read back from `iw` and `GET /access-point/{reservation_id}` (HAP-11), `/status` with an Internet-less network (BUG-2), TX power reported vs `iw` (BUG-7), TX power change time (PERF-6), `/status` read in a tight loop during create/delete (RACE-2), `GET /access-point/{reservation_id}` polled by 8 threads during creates: every answer is `200` or `503 / 1006` with `Retry-After: 2` within the busy limit (RACE-1, not xfail). | SEC-1, SEC-2, API-2, API-5, API-10, HAP-10, HAP-11, BUG-2, BUG-7, PERF-6, RACE-1, RACE-2, e2e-test-3, 4, 5 | `iw` (BUG-7, HAP-11); `sudo` for `hostapd_cli` (HAP-10, HAP-11) and `iptables -S` (e2e-test-3) |

In this table a create that "returns `200`" is the outcome read by the helper `WiLab.create()`: it
sends the `POST` (answered `202`) and polls `GET /access-point/{reservation_id}` until `runtime_state` is no longer
`starting`, so it returns that `GET` answer (`200` with the running network, or `404`), or the `POST` answer
itself when it is not `202`. A start that ends in `start_failed` is returned as a `500` whose
`detail` is the `error` of the `GET` (code 1013), so a test that expects `200` fails on it.

Most tests in `test_e2e_api.py` use only the public API, so they give the same result from an
external machine; the exceptions read the host (`iw` for BUG-7 and HAP-11, `hostapd_cli` for
HAP-10, `pgrep`, `ip` and `iptables -S` for e2e-test-3). Tests for IDs that are not fixed yet are
marked `xfail` (not strict): pytest reports them as `XFAIL` until the fix lands and as `XPASS`
afterwards, when the mark is removed.

The watchdog budgets (3 AP restores and 3 DHCP restarts per hour per antenna) live in the running
service, so tests that kill hostapd or dnsmasq, or remove the host guard (e2e-test-11), use them up. A full run needs more AP restores than two antennas have in an hour, so the last of those tests skip themselves. Each of those tests counts the
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
- Mark tests with `@pytest.mark.usb`, `@pytest.mark.usb_active_ap`, `@pytest.mark.slow` or
  `@pytest.mark.service_restart` when they need the matching flag.
- Assert on the API response (status, `detail.code`, `Retry-After`), on `/status`, and on the
  journal lines that prove the code path, as the existing tests do.
