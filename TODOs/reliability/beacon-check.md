# Feature: Beacon Check After AP Start

**Priority:** 3 (HIGH)  
**Status:** PROPOSED  
**Estimated Effort:** ~4 hours  

## Description

Verify after a start that the radio really transmits beacons. A clean hostapd
start does not prove it: on Realtek RTL8822BU (`rtw88_8822bu`) the AP starts,
carrier and operstate are up, and no beacon is ever sent.

## Context

Realtek RTL8822BU, driver `rtw88_8822bu` (kernel 7.0.0-15, firmware 30.20.0), tested
2026-05-07: `iw phy` lists AP mode, hostapd starts, carrier and operstate are up,
TX packets stay at 0, `dmesg` shows `failed to get tx report from firmware`, no
client sees the SSID. Five startup sequences, all bypassing Wi-Lab, failed the
same way: the firmware does not transmit in AP mode. The MT7921U on the same host
sent +61 TX packets in 5 s then; on 2026-11-27 (kernel 7.0.0-44) it showed +3 in
10 s, because MediaTek beacons are sent by the firmware and not counted.

## Implementation Tasks

- [ ] After the start, read the interface TX packet counter twice, 5 s apart; a healthy AP sends about 10 beacons per second
- [ ] Only for drivers that count beacons in TX packets (`rtw88_8822bu` does; the MT7921U does not: +3 packets in 10 s with the AP up)
- [ ] Per-driver option next to the watchdog budgets: `watchdog.drivers.<driver>.beacon_check: true`
- [ ] A failed check is a radio failure: retried, then `start_failed` with a clear message
- [ ] Optional: check every antenna at Wi-Lab startup and mark failing drivers unavailable, with the reason visible in `/antennas`

## Testing

- [ ] Unit tests with fake counters: passing, failing, driver without the option
- [ ] Real radio: Realtek fails the check, MediaTek is not checked

## Benefits

- **Reliability:** No more "started" networks that do not exist on the air

## Breaking Changes

- None (per-driver option, off by default)

## Success Criteria

- ✅ A Realtek start without beacons is reported as failed
- ✅ MediaTek starts are not affected
