# Feature: Patched hostapd for the Startup Segfault

**Priority:** 7  
**Status:** PROPOSED  
**Estimated Effort:** ~1 day  

## Description

Install a hostapd with the upstream fix for a NULL pointer crash at startup. The
crash happens in 2.4% of the starts on the MT7921U (51 of 2,112 in a stress run);
Wi-Lab already retries it, so no create fails, but each crash costs seconds.

## Context

All 51 crashes: `segfault at 0 ... error 4 in hostapd`, about 1.4 s after the start,
before the control socket opens. Package `hostapd 2:2.11-0ubuntu5`; with the debug
symbols the address resolves to `wpa_driver_nl80211_del_beacon()`
(`driver_nl80211.c:3086`, `link == NULL`), fixed upstream by
[`015f6a5a`](https://w1.fi/cgit/hostap/commit/?id=015f6a5a0cd1c8b0d40441b9fd9e4c8658bc9493)
(August 2024, after 2.11). It follows an early nl80211 initialization failure,
likely during the MT7921U firmware timeouts. Current mitigation: `HostapdSegfault`
is a radio failure, retried; `hostapd_debug_dir` saves a report of each failure
(enabled on the lab host); how to read a crash: troubleshooting, Issue 7.

## Part 1: Classify the Underlying Error

- [ ] From the reports in `hostapd_debug_dir` (`/var/log/wilab/hostapd/*-HostapdSegfault.log`), find the nl80211 command that fails before the crash
- [ ] Add that output line to `_classify_output` in `wilab/wifi/hostapd.py` as a radio failure, with a test
- [ ] Needed first: with the patch hostapd exits with an error instead of crashing, and an unclassified exit is not retried

## Part 2: Patched Package

- [ ] Rebuild Ubuntu's `wpa` source package with upstream commit `015f6a5a` (recipe below) and try it by hand on the lab host
- [ ] If it works: `scripts/patch-hostapd.sh`, called by `install.sh --patch-hostapd`; only when the installed 2.11 lacks the fix; never blocking
- [ ] `uninstall.sh` restores Ubuntu's version or says it is kept
- [ ] Optional: report the bug on Launchpad (`wpa` package) asking for an SRU

## Recipe

```bash
# enable source packages: add "deb-src" to Types: in /etc/apt/sources.list.d/ubuntu.sources
sudo apt update
sudo apt install devscripts build-essential quilt
sudo apt build-dep wpa
apt source wpa && cd wpa-2.11*/
curl -o debian/patches/nl80211-null-link.patch \
  "https://w1.fi/cgit/hostap/patch/?id=015f6a5a0cd1c8b0d40441b9fd9e4c8658bc9493"
echo nl80211-null-link.patch >> debian/patches/series
dch --local +wilab "Cherry-pick 015f6a5a: NULL check for link in del_beacon"
dpkg-buildpackage -us -uc -b
sudo apt install ../hostapd_2.11-0ubuntu5+wilab1_amd64.deb
readelf -n /usr/sbin/hostapd | grep "Build ID"   # must differ
```

No `apt-mark hold`: a future Ubuntu security update (`2.11-0ubuntu5.1`) sorts
higher and replaces it. Check from time to time whether Ubuntu ships the fix:
`apt-cache policy hostapd`, `/usr/share/doc/hostapd/changelog.Debian.gz`.

## Testing

- [ ] Unit test for the new classification
- [ ] Long stress run with the patched hostapd: no segfault, retries still work

## Benefits

- **Speed:** No lost seconds on crashed starts
- **Hygiene:** No core dumps of a known bug

## Breaking Changes

- None

## Success Criteria

- ✅ The nl80211 error is classified and retried
- ✅ A stress run with the patched hostapd has no segfault
