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
