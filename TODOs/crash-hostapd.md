# Issue: hostapd 2.11 segfault at startup

**Priority:** 3 (LOW, mitigated)
**Status:** ANALYZED, fix postponed

---

## Summary

During the stress run of 2026-11-25 (15:30–16:55 UTC, two MediaTek MT7921U
antennas), hostapd crashed at startup **51 times out of 2,112 starts (2.4%)**.
Wi-Lab classifies the crash as a radio failure and starts the AP again, so no
create failed and no antenna was quarantined. The cost for clients is a few
extra seconds on those starts.

The crash is a **bug in hostapd 2.11**, already fixed upstream. It is a
symptom: the real event is an early failure of the nl80211 driver
initialization, most likely during the MT7921U firmware timeouts seen in the
same period (44 `Message ... timeout` and 48 firmware reloads in 85 minutes).

## Evidence

- All 51 crashes are identical in the kernel log:
  `hostapd[...]: segfault at 0 ip ... error 4 in hostapd[aaf3a,...]`, about
  1.4 s after start, before hostapd opens its control socket.
- Installed package: `hostapd 2:2.11-0ubuntu5` (Ubuntu 26.04 "resolute"),
  Build ID `36b6e3aa198aea6a597af14c502591c56b32ee80`.
- `aaf3a` is a file offset; in this binary it equals the address. With the
  debug symbols of the same build (`hostapd-dbgsym_2.11-0ubuntu5_amd64.ddeb`
  from Launchpad; not available on debuginfod.ubuntu.com nor ddebs) it resolves
  to `wpa_driver_nl80211_del_beacon()`, `src/drivers/driver_nl80211.c:3086`:
  `if (!link->beacon_set)` with `link == NULL`.
- Upstream fix: hostap commit
  [`015f6a5a`](https://w1.fi/cgit/hostap/commit/?id=015f6a5a0cd1c8b0d40441b9fd9e4c8658bc9493)
  "nl80211: NULL pointer check for link before use" (August 2024, after 2.11):
  *bss->flink could be NULL when wpa_driver_nl80211_del_beacon() is called if
  wpa_driver_nl80211_drv_init() fails early through the 'failed' label.*

## Current mitigation (in Wi-Lab, nothing to do)

- A segfault is a classified radio failure (`HostapdSegfault`): up to 3 starts
  during the asynchronous create (1 s apart), then one start after 5 s and
  one after 10 s; only if all fail the reservation is invalidated (polling:
  `404`, `reservation_invalidated`).
- Diagnostics added: optional `hostapd_debug_dir` in `config.yaml` writes, for
  every failed hostapd start, the configuration (no passwords) and the last
  400 lines of `hostapd -d`. Enabled on the lab host
  (`/var/log/wilab/hostapd`).
- Host tools installed on the lab host: `systemd-coredump` (cores of every
  crash, `coredumpctl list hostapd`), `gdb`, `debuginfod`. The service already
  allows core dumps (`LimitCORE=infinity`).
- How to read a crash: [troubleshooting, Issue 7](../docs/troubleshooting.md).

## Why `apt update` does not fix it

The Ubuntu candidate is the installed version, and the fix is not in any
hostapd release known so far (2.11 is the latest). Check again from time to
time: `sudo apt update && apt-cache policy hostapd`, and whether the Ubuntu
changelog (`/usr/share/doc/hostapd/changelog.Debian.gz`) mentions the patch.

## Important: the patch changes Wi-Lab's behaviour

With the patch hostapd no longer crashes: it exits with an error code. Today
an unclassified exit code is not retried: the create ends as `runtime_state:
start_failed` (`error.code` 1013, `stage: hostapd`), so creates would
fail more often than now. **Before installing a patched hostapd**, Wi-Lab must
recognize the nl80211 initialization error in the `hostapd -d` output and
classify it as a radio failure (like `HostapdInitFailure`), so it is retried.

## Plan (in this order)

1. Restart Wi-Lab with `hostapd_debug_dir` enabled and run a long stress test.
2. From the reports, find the nl80211 command that fails before the crash.
3. Add its output line to hostapd's output classification in Wi-Lab
   (`_classify_output` in `wilab/wifi/hostapd.py`) as a radio failure, with a
   test.
4. Try the patched package by hand on the lab host (recipe below).
5. Only if it works: make it an optional install step (design below).
6. In parallel (optional): report the bug on Launchpad (`wpa` source package)
   asking for an SRU with `015f6a5a`.

## Recipe: rebuild the Ubuntu package with the one-line patch

```bash
# enable source packages: add "deb-src" to Types: in /etc/apt/sources.list.d/ubuntu.sources
sudo apt update
sudo apt install devscripts build-essential quilt
sudo apt build-dep wpa            # the source package is "wpa"
apt source wpa && cd wpa-2.11*/
curl -o debian/patches/nl80211-null-link.patch \
  "https://w1.fi/cgit/hostap/patch/?id=015f6a5a0cd1c8b0d40441b9fd9e4c8658bc9493"
echo nl80211-null-link.patch >> debian/patches/series
dch --local +wilab "Cherry-pick 015f6a5a: NULL check for link in del_beacon"
dpkg-buildpackage -us -uc -b
sudo apt install ../hostapd_2.11-0ubuntu5+wilab1_amd64.deb   # hostapd only
readelf -n /usr/sbin/hostapd | grep "Build ID"                # must differ
```

- No `apt-mark hold`: with Debian version ordering a future Ubuntu security
  update (`2.11-0ubuntu5.1`) is higher than `2.11-0ubuntu5+wilab1` and replaces
  it. If it lacks the patch, the crash returns and the check below detects it.
- Building upstream git instead is not recommended: it brings every change
  after 2.11, needs the build options aligned with Ubuntu's, and bypasses apt.

## Design: optional install step (if step 5 is reached)

- A separate `scripts/patch-hostapd.sh`, also usable alone (e.g. after an
  Ubuntu update). `install.sh` calls it only with `--patch-hostapd`, or asks
  for confirmation in interactive mode when the problem is detected.
- **Only if needed:** apply when the upstream version is 2.11 and the installed
  package changelog contains neither the patch nor the `+wilab` suffix. Do
  nothing once Ubuntu ships the fix.
- **Never blocking:** if the build or the patch fails, continue with Ubuntu's
  hostapd and print a clear warning (Wi-Lab copes with the crash).
- Build in a temporary directory and remove the build dependencies afterwards
  (`mk-build-deps --remove`, or `apt-mark auto` + `autoremove`).
- `uninstall.sh`: reinstall Ubuntu's version
  (`apt install --reinstall hostapd=<ubuntu version>`) or leave it and say so.

Reasons it is not automatic: it enables `deb-src`, installs a toolchain and
hundreds of MB of `-dev` packages, compiles on the production host, and
depends on the Ubuntu release and package layout.
