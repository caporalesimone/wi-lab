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


IMPORTANT COMMENT:

Before starting this development, evaluate the cost of keeping an API waiting more than 5 seconds for a response.
The impact of switching to a request/job-id/polling pattern is high, as it requires clients to refactor their existing code.
A lighter alternative could be to check the beacon rate (beacons/sec) over a 5-second window at startup of Wi-Lab, and mark any underperforming networks as unavailable.

Checking all configured Wi-Fi networks at startup has the additional advantage of proactively marking unavailable any network whose driver is not functioning correctly, preventing it from ever being presented to the user as an option.However, it remains essential to provide a clear and easily accessible way for the user to understand why certain networks have been disabled — for example, through a dedicated status log or a visible warning indicating that the network was excluded due to a driver failure detected at startup.


---

## Success Criteria

- [ ] AP start on Realtek `rtw88_8822bu` is correctly detected as failed (carrier check)
- [ ] API returns a meaningful error instead of false success
- [ ] Existing functionality for working adapters (MediaTek) is not affected

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

