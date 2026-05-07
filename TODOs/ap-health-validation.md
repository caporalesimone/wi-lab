# AP Health Validation & Realtek Compatibility

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  
**Triggered by:** Realtek RTL8822BU (`rtw88_8822bu`) antennas reporting successful AP creation while the radio never transmits beacons — network invisible to external devices.

---

## Problem Statement

When Wi-Lab creates a network via hostapd, the only validation performed is checking that the hostapd **process starts without error**. However, a successful process start does not guarantee that the radio is actually transmitting. With Realtek RTL8822BU adapters (driver `rtw88_8822bu`), hostapd starts cleanly but the interface remains in `NO-CARRIER` / `state DOWN`, the firmware fails to transmit beacons (`failed to get tx report from firmware` in dmesg), and no client can ever see or connect to the network.

This is a **silent failure**: the API returns success, the user sees "Network started", but the WiFi network doesn't exist in the real world.

---

## Proposed Improvements

### 1. Post-Startup TX Beacon Verification

**What:** After hostapd starts, verify that the radio is actually transmitting beacons by monitoring TX packet counters.

**Why carrier check alone is insufficient:** Testing showed that Realtek `rtw88_8822bu` reports `carrier=1, operstate=up, type=AP` — all kernel-level checks pass — yet TX packets remain at 0. The firmware silently fails to transmit beacons. Only TX packet delta is a reliable indicator.

**How:**
- After `hostapd_start()` returns success, read TX packets from `/proc/net/dev` for the interface
- Wait 3–5s, then read TX packets again
- A healthy AP transmits ~10 beacons/sec → expect delta ≥ 20 in 5s
- If TX delta = 0 after timeout, treat as AP startup failure

**Fallback checks (supplementary, not sufficient alone):**
- `/sys/class/net/{interface}/carrier` = 1
- `/sys/class/net/{interface}/operstate` = `up`

**API Behavior on Failure:**
- Return HTTP 500 or 503 with a clear error: `"AP started but radio is not transmitting (0 TX packets in 5s). The WiFi adapter may not support AP mode reliably with the current driver."`
- Automatically stop hostapd, dnsmasq, and clean up NAT/iptables rules (rollback)

**Implementation Location:**
- `wilab/wifi/hostapd.py` — add TX packet verification after process start
- `wilab/wifi/manager.py` — handle the new failure case in `start_network()`

### 2. Driver Compatibility Warning at Startup

**What:** On service startup, check each configured interface's driver and log a warning if it's known to have AP mode issues.

**How:**
- Read driver name from `/sys/class/net/{interface}/device/uevent` (DRIVER= field) or via `ethtool -i`
- Maintain a small list of known-problematic drivers for AP mode:
  - `rtw88_8822bu`
  - `rtw88_8821cu`
  - `rtl8xxxu`
  - Other Realtek USB drivers with known AP issues
- On match, log a WARNING: `"Interface {name} uses driver {driver} which has known AP mode limitations. Consider using a MediaTek-based adapter for reliable AP operation."`

**Implementation Location:**
- `wilab/wifi/manager.py` — during interface validation at startup / channel cache warm-up

### 3. Network Health Status in API Response

**What:** Add a `health` or `radio_status` field to the network status API response so the frontend and users can see if the AP is actually functional.

**How:**
- After network start, include in `GET /api/v1/interface/{rid}/network` response:
  ```json
  {
    "radio_health": {
      "carrier": true,
      "operstate": "up",
      "driver": "mt7921u",
      "driver_warning": null
    }
  }
  ```
- For problematic states:
  ```json
  {
    "radio_health": {
      "carrier": false,
      "operstate": "down",
      "driver": "rtw88_8822bu",
      "driver_warning": "This driver has known AP mode limitations"
    }
  }
  ```

**Implementation Location:**
- `wilab/models.py` — add `RadioHealth` model
- `wilab/wifi/manager.py` — populate during network status gathering
- `wilab/api/routes/network.py` — include in response

### 4. dmesg Error Detection (Optional / Advanced)

**What:** After AP start, check recent kernel messages for driver-level errors that indicate radio failure.

**How:**
- Run `dmesg --since "30 seconds ago"` (or read `/dev/kmsg`) after hostapd start
- Search for patterns like `failed to get tx report from firmware`, `firmware error`, `timeout`
- If found, log as ERROR and optionally fail the AP start

**Caveats:**
- Requires root/CAP_SYSLOG to read dmesg
- Pattern matching is fragile across kernel versions
- Consider this as a supplementary diagnostic, not a primary check

**Implementation Location:**
- `wilab/wifi/hostapd.py` — optional diagnostic after start

---

## Success Criteria

- [ ] AP start on Realtek `rtw88_8822bu` is correctly detected as failed (carrier check)
- [ ] API returns a meaningful error instead of false success
- [ ] Resources are rolled back on detected failure (hostapd, dnsmasq, iptables)
- [ ] Known-problematic drivers produce a startup warning in logs
- [ ] Network status API exposes radio health information
- [ ] Existing functionality for working adapters (MediaTek) is not affected
- [ ] Test coverage for carrier-check logic (mocked)

---

## Context & Evidence

**Hardware tested:**
- TP-Link 802.11ac NIC (USB ID `2357:0138`) × 2
- Chipset: Realtek RTL8822BU
- Driver: `rtw88_8822bu` (in-kernel, firmware v30.20.0)
- Kernel: 7.0.0-15-generic

**Symptoms observed:**
- `iw phy` reports AP mode as supported
- hostapd process starts successfully (exit code 0)
- Interface shows `carrier=1`, `operstate=up`, `type=AP` — all kernel-level checks PASS
- Despite passing checks, TX packet counter stays at 0 (no beacons transmitted)
- dmesg shows repeated `failed to get tx report from firmware` (~every 75s)
- No client ever sees the SSID or can associate
- Working comparison: MediaTek `mt7921u` on same system shows +61 TX packets in 5s

**Startup sequence tests (2026-05-07):**

Five different hostapd startup sequences were tested directly via shell script, bypassing Wi-Lab entirely. ALL failed identically:

| Test | Sequence | TX delta (5s) | Result |
|------|----------|---------------|--------|
| T1 | Wi-Lab default (down → managed → flush → hostapd) | +0 | FAIL |
| T2 | Skip managed reset (down → flush → hostapd) | +0 | FAIL |
| T3 | Manual AP mode first (down → iw set AP → hostapd) | +0 | FAIL |
| T4 | Longer delay 2s (same as T1 + 2s stabilization) | +0 | FAIL |
| T5 | Interface UP before hostapd (managed UP → hostapd) | +0 | FAIL |

**Conclusion:** The failure is at the firmware/driver level. No hostapd startup sequence variation produces beacon transmission. The Wi-Lab code is correct — the radio hardware simply does not transmit in AP mode with the `rtw88_8822bu` driver.

**Note on carrier/operstate:** Unlike initial observations where `NO-CARRIER` was seen, later tests (via Wi-Lab API) showed `carrier=1, operstate=up` — meaning the interface *appears* healthy at the kernel level but the firmware never actually transmits. This makes the failure harder to detect via simple carrier checks, and TX packet monitoring (Proposal 1) is the most reliable detection method.

**Known driver issues:**
- `rtw88_8822bu` is a relatively new in-kernel driver (replaced out-of-tree `rtl88x2bu`)
- AP mode support is listed in `iw phy` but functionally broken at firmware level
- `interface combinations are not supported` — limits concurrent mode operation
- The out-of-tree driver (`lwfinger/rtw88` or `morrownr/88x2bu`) may work better for AP mode

---

