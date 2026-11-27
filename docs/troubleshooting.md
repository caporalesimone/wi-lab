# Wi-Lab Troubleshooting Guide

> Disclaimer: before running any troubleshooting script, align interface names (for example `wlx...`) to the real interface names on your host.

This document is script-first: operational commands are stored under [diagnostics/troubleshooting](../diagnostics/troubleshooting).

Run scripts from the repository root with `bash <script>`.

---

## Quick Diagnostics

- Service status and Swagger reachability:
	- [diagnostics/troubleshooting/check_service_status.sh](../diagnostics/troubleshooting/check_service_status.sh)
- Service logs (modes: `tail`, `follow`, `boot`, `hour`, `errors`):
	- [diagnostics/troubleshooting/view_service_logs.sh](../diagnostics/troubleshooting/view_service_logs.sh)
- Post-installation sanity checks:
	- [diagnostics/troubleshooting/post_installation_sanity.sh](../diagnostics/troubleshooting/post_installation_sanity.sh)

### Filter API server errors

```bash
journalctl -u wi-lab.service --no-pager -g 'API failure operation='
```

For example, `API failure operation=stop_network http_status=503 detail_code=1012`
identifies a `DELETE .../network` that did not complete (hostapd stuck in the
kernel). The diagnostic line is emitted only for API `5xx` responses. It omits
request paths, reservation IDs, tokens, and response bodies. A failed
asynchronous create is not an API `5xx`: its outcome is logged by the create
job as `AP start on <interface> failed: ...` or `AP start on <interface> ended
its reservation (...)`.

---

## Service Management

- Start/stop/restart/reload/status:
	- [diagnostics/troubleshooting/service_management.sh](../diagnostics/troubleshooting/service_management.sh)
- Enable/disable/check autostart:
	- [diagnostics/troubleshooting/autostart_management.sh](../diagnostics/troubleshooting/autostart_management.sh)

---

## Common Issues

### Issue 1: Service Fails to Start

Symptoms:
- `wi-lab.service` is failed/inactive
- Swagger UI is not reachable

Script:
- [diagnostics/troubleshooting/issue_service_fails_start.sh](../diagnostics/troubleshooting/issue_service_fails_start.sh)

Startup prechecks: `journalctl -u wi-lab | grep "Startup precheck"`.
- `CRITICAL ... Startup precheck root` or `... commands`: the service exits with code
  `78` and systemd does not restart it. Run the installer again (it installs missing
  commands), then `sudo systemctl restart wi-lab`.

### Issue 1b: `WARNING ... Startup precheck network_manager` or `... wpa_supplicant`

NetworkManager or `wpa_supplicant` can take a Wi-Fi adapter back and bring APs down.
Wi-Lab requires NetworkManager disabled; `wpa_supplicant` is warned about only when
it manages a Wi-Lab radio.

```bash
systemctl is-active NetworkManager wpa_supplicant
nmcli device status          # NetworkManager must manage no interface of the host
networkctl list              # the host interface must be "configured" by systemd-networkd
ls /run/wpa_supplicant/      # a socket named like a Wi-Lab radio: wpa_supplicant holds it
```

If NetworkManager manages no interface (or rerun the installer, which checks it):

```bash
sudo systemctl disable --now NetworkManager && sudo systemctl mask NetworkManager
sudo systemctl disable --now wpa_supplicant && sudo systemctl mask wpa_supplicant
sudo systemctl restart wi-lab
```

### Issue 2: Cannot Create WiFi Network

Symptoms:
- Swagger UI reachable
- Create network operation fails

Script:
- [diagnostics/troubleshooting/issue_network_creation_fails.sh](../diagnostics/troubleshooting/issue_network_creation_fails.sh)
- [USB adapter recovery procedure](architecture.md#82-manual-recovery) for a blocked interface

### Issue 3: Clients Cannot Connect

Symptoms:
- SSID visible
- clients fail to get IP or Internet

Scripts:
- [diagnostics/troubleshooting/issue_clients_cannot_connect.sh](../diagnostics/troubleshooting/issue_clients_cannot_connect.sh)
- [diagnostics/troubleshooting/view_service_logs.sh](../diagnostics/troubleshooting/view_service_logs.sh)

### Issue 4: SSH Lost After Network Changes

Scripts:
- Console recovery and subnet conflict checks:
	- [diagnostics/troubleshooting/issue_ssh_lost_recovery.sh](../diagnostics/troubleshooting/issue_ssh_lost_recovery.sh)
- iptables diagnosis:
	- [diagnostics/troubleshooting/issue_iptables_ssh_interference.sh](../diagnostics/troubleshooting/issue_iptables_ssh_interference.sh)
- manual destructive recovery (`--force` required):
	- [diagnostics/troubleshooting/issue_manual_network_recovery.sh](../diagnostics/troubleshooting/issue_manual_network_recovery.sh)

### Issue 5: TX Power Not Applied

Script:
- [diagnostics/troubleshooting/issue_txpower_diagnosis.sh](../diagnostics/troubleshooting/issue_txpower_diagnosis.sh)

### Issue 6: Antenna Stays `unavailable` (status `degraded`)

Symptoms:
- `GET /api/v2/status` returns `status: degraded` and an entry with
  `recovery_state: unavailable` (or `recovering` for a long time)
- a create ended with `404` and `reason: reservation_invalidated`; fewer antennas can be reserved

Check, in this order:
1. Kernel log around the failure: `journalctl -k --since "<time>"`. Look for
   `USB disconnect`, `mt7921u ... Message ... timeout`, `USB transport access
   failed, queueing device reset`, and whether the adapter came back
   (`renamed from wlan0`).
2. Is the adapter still there? `ip -br link`, `lsusb`. If `lsusb` no longer
   lists it, no software recovery can work: replug it, or re-attach the USB
   passthrough to the VM.
3. Wi-Lab log: `journalctl -u wi-lab | grep -E "re-probe|allocatable again|USB recovery|disappeared"`.
   An `unavailable` antenna is re-probed after 30 s, then with backoff up to
   every 15 min; `passed the probe and is allocatable again` means it is back.
4. If it is present but keeps failing the probe, follow the
   [manual recovery procedure](architecture.md#82-manual-recovery).

Observed on 2026-11-23: the USB adapter dropped during a create (firmware
timeout, driver-initiated USB reset) and came back 6 s later, but before the
WD-4/WD-5 fixes it stayed `unavailable` until a service restart. A later VM
stall (`rcu_preempt ... starved`) detached it from the guest entirely; that
case needs the adapter to be re-attached.

---

### Issue 7: hostapd Crashes at Startup (`hostapd segfault`)

The journal shows `Failed to start AP for <interface>: hostapd segfault` and
the kernel log `hostapd[...]: segfault at 0 ... in hostapd[aaf3a,...]`. Wi-Lab
classifies it as a radio failure and retries, so a create usually still
succeeds.

Cause found in November 2026 with hostapd `2:2.11-0ubuntu5`: when the nl80211
driver initialization fails early, hostapd 2.11 cleans up through
`wpa_driver_nl80211_del_beacon()` with a NULL link and crashes instead of
exiting with an error. Upstream fixed it after 2.11 (hostap commit `015f6a5a`,
"nl80211: NULL pointer check for link before use"). The crash is therefore a
symptom: the driver initialization failed first, often while the mt7921u
firmware was timing out (`mt7921u ...: Message ... timeout` in `journalctl -k`).

To see why the initialization fails:

1. Set `hostapd_debug_dir: "/var/log/wilab/hostapd"` in `config.yaml` and
   restart Wi-Lab. Every failed hostapd start writes a report there: the
   hostapd configuration (no passwords) and the last 400 lines of
   `hostapd -d`, whose last lines before the crash show the failing nl80211
   command.
2. With `systemd-coredump` installed, each crash is saved: `coredumpctl list
   hostapd`. For a backtrace, extract the debug symbols of the installed
   version (`hostapd-dbgsym_<version>_amd64.ddeb` from Launchpad,
   `dpkg-deb -x` into a directory) and run
   `coredumpctl gdb hostapd` with `set debug-file-directory <dir>/usr/lib/debug`.
3. Without a core: the kernel line gives the file offset (`hostapd[aaf3a,...]`);
   `gdb -batch -ex "info symbol 0xaaf3a" /usr/sbin/hostapd` with the same
   debug directory names the function.

If one adapter fails at every start and its firmware keeps timing out (the
kernel log repeats `Message ... timeout` for it), reload its driver with the
service stopped:

```bash
make stop
make reload-drivers      # sudo bash scripts/reload-drivers.sh
make start
```

It unloads and loads the kernel module of every adapter Wi-Lab manages, once
per module, and waits for the interfaces to come back. It refuses to run while
the service runs (exit code 3), and never reloads a module that also drives the
host's own network (the default-route interface or `upstream_interface`).
Reloading resets every adapter of that module, including any not managed by
Wi-Lab.

### Issue 8: Red Bar "Security updates installed" (`service.restart_required` in `/status`)

Unattended upgrades installed security updates, and the running service still uses the
old code: a library it had loaded was replaced (`service`), or an update asks for a reboot
(`system`: `/run/reboot-required`, or a kernel newer than the running one is installed). Wi-Lab never restarts by itself:
the installer excludes it from needrestart (`/etc/needrestart/conf.d/wilab.conf`), since a
restart stops every active network.

When no network is in use:

```bash
sudo systemctl restart wi-lab     # service.restart_required.service
sudo reboot                       # service.restart_required.system
```

`GET /api/v2/monitoring` lists the replaced libraries and the packages (`checks.updates`).
Before 4.1.0 needrestart restarted Wi-Lab after such an upgrade, dropping every network.

## Performance Issues

### WiFi Slow or Unstable

Script:
- [diagnostics/troubleshooting/performance_diagnosis.sh](../diagnostics/troubleshooting/performance_diagnosis.sh)

---

## Testing and Validation

- Complete health check report:
	- [diagnostics/troubleshooting/complete_health_check.sh](../diagnostics/troubleshooting/complete_health_check.sh)
- API interactive testing:
	- `http://localhost:8080/docs`

---

## Debug Mode

- Verbose Python startup:
	- [diagnostics/troubleshooting/debug_verbose.sh](../diagnostics/troubleshooting/debug_verbose.sh)
- Manual foreground service run:
	- [diagnostics/troubleshooting/debug_manual_foreground.sh](../diagnostics/troubleshooting/debug_manual_foreground.sh)

---

## Networking Reference

For networking model and safeguards (no operational scripts), see [networking.md](networking.md):
- [System Modifications](networking.md#system-modifications)
- [CRITICAL: Subnet Conflicts](networking.md#-critical-subnet-conflicts)
- [Diagnostics and Monitoring](networking.md#diagnostics-and-monitoring)

---

## Getting Help

1. Run [diagnostics/troubleshooting/check_service_status.sh](../diagnostics/troubleshooting/check_service_status.sh)
2. Run [diagnostics/troubleshooting/view_service_logs.sh](../diagnostics/troubleshooting/view_service_logs.sh) with `errors`
3. Run the issue-specific script from this document
4. Check [swagger.md](swagger.md)
5. If unresolved, open a GitHub issue with script outputs
