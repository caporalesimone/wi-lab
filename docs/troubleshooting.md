# Wi-Lab Troubleshooting Guide

> Disclaimer: before running any troubleshooting script, align interface names (for example `wlx...`) to the real interface names on your host.

This document is script-first: operational commands are stored under [diagnostics/troubleshooting](../diagnostics/troubleshooting).

Run scripts from the repository root with `bash <script>`.

---

## Quick Diagnostics

- **Configuration check — start here whenever the service will not start:**
	- `python3 main.py --validate-config` (see [Issue 0](#issue-0-service-does-not-start--configuration-validation-failed))
- Service status and Swagger reachability:
	- [diagnostics/troubleshooting/check_service_status.sh](../diagnostics/troubleshooting/check_service_status.sh)
- Service logs (modes: `tail`, `follow`, `boot`, `hour`, `errors`):
	- [diagnostics/troubleshooting/view_service_logs.sh](../diagnostics/troubleshooting/view_service_logs.sh)
- Post-installation sanity checks:
	- [diagnostics/troubleshooting/post_installation_sanity.sh](../diagnostics/troubleshooting/post_installation_sanity.sh)

---

## Service Management

- Start/stop/restart/reload/status:
	- [diagnostics/troubleshooting/service_management.sh](../diagnostics/troubleshooting/service_management.sh)
- Enable/disable/check autostart:
	- [diagnostics/troubleshooting/autostart_management.sh](../diagnostics/troubleshooting/autostart_management.sh)

---

## Common Issues

### Issue 0: Service Does Not Start — Configuration Validation Failed

**Always check this first.** Wi-Lab validates `config.yaml` before doing anything else and
refuses to start if it is incomplete or wrong. This is by far the most common cause of a
service that will not come up, especially right after an upgrade.

Symptoms:
- `wi-lab.service` is `failed`
- `systemctl status wi-lab` shows a `Wi-Lab configuration validation FAILED` report
- Nothing was started, no interface was touched, no rule was installed

Run the validator yourself — it is safe on a production host, starts no server and changes
nothing:

```bash
cd /opt/wilab
python3 main.py --validate-config                   # structure, types, values
python3 main.py --validate-config --check-hardware   # also adapters and host routes
```

**How to read the report.** Every problem is listed in one pass, so the file can be fixed
in a single editing session — there is no restart-fix-restart loop:

```
Wi-Lab configuration validation FAILED
File: /opt/wilab/config.yaml
1 error(s), 1 warning(s)

WARNING api_port
        api_port (80) is a privileged port.
        -> Binding below 1024 requires root or CAP_NET_BIND_SERVICE.

ERROR   networks[0].capabilities
        Missing required key.
        -> Add a capabilities block declaring: 2.4ghz, 5ghz
```

| Column | Meaning |
|--------|---------|
| `ERROR` / `WARNING` | Errors stop the service; warnings do not |
| The path | Exactly where in the file, `networks[0]` being the first device |
| The message | What is wrong |
| The `->` line | What to do about it |

Exit codes, for scripting and CI:

| Code | Meaning |
|------|---------|
| `0` | Valid — warnings may still have been printed |
| `1` | Invalid — see the report |
| `2` | The file could not be read or parsed at all (missing, unreadable, broken YAML) |

**Unit state: `failed`, not a restart loop.** The unit is configured with
`StartLimitIntervalSec=300` / `StartLimitBurst=3`, so after three failed starts in five
minutes systemd gives up and leaves it in `failed`. A configuration error cannot fix
itself by being retried, and a unit stuck in `activating (auto-restart)` would hide the
report under a wall of repeated journal entries. If you see `failed`, read the report; if
you see `activating (auto-restart)`, the failure is something transient, not the config.

```bash
systemctl status wi-lab                    # the validation report is in the status output
journalctl -u wi-lab -n 60 --no-pager      # or here, if the status output is truncated
```

After fixing the file, re-run `--validate-config` until it prints OK, then
`sudo systemctl restart wi-lab`.

> **Upgrading from 3.x?** `capabilities`, `cors_origins` and
> `allow_unlimited_reservation` are now required and this is exactly what the report will
> tell you. Capability values must be typed by hand — Wi-Lab never guesses them and never
> edits your file. See [Configuration](../README.md#configuration).

### Issue 1: Service Fails to Start

First rule out Issue 0 above — if the journal shows a validation report, that is the
problem and no script will tell you more than the report already does.

Symptoms:
- `wi-lab.service` is failed/inactive
- Swagger UI is not reachable
- `systemctl status wi-lab` shows **no** validation report

Script:
- [diagnostics/troubleshooting/issue_service_fails_start.sh](../diagnostics/troubleshooting/issue_service_fails_start.sh)

### Issue 2: Cannot Create WiFi Network

Symptoms:
- Swagger UI reachable
- Create network operation fails

Script:
- [diagnostics/troubleshooting/issue_network_creation_fails.sh](../diagnostics/troubleshooting/issue_network_creation_fails.sh)

**"hostapd crashed (SIGSEGV) while starting"** means hostapd itself died, which is almost always the
adapter's driver or firmware and not the configuration. Confirm it:

```bash
sudo dmesg | tail -30      # look for "failed to download firmware" or "segfault ... in hostapd"
```

Reload the driver of the adapter (the module name is in the `dmesg` lines, e.g. `rtw88_8822bu`).
This resets **every** adapter that uses that module, so do it while no network is in use:

```bash
sudo modprobe -r rtw88_8822bu    # unload the driver: this releases the adapters
sudo modprobe rtw88_8822bu       # load it again: the adapters are detected and initialised anew
```

If it does not help, unplug and replug the adapter, or restart the host.

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

> ⚠️ **Known limitation:** TX power control could not be made to work with the USB dongles
> tested so far, so correct operation is not guaranteed for now.

Script:
- [diagnostics/troubleshooting/issue_txpower_diagnosis.sh](../diagnostics/troubleshooting/issue_txpower_diagnosis.sh)

---

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

1. Run `python3 main.py --validate-config` from the install directory
2. Run [diagnostics/troubleshooting/check_service_status.sh](../diagnostics/troubleshooting/check_service_status.sh)
3. Run [diagnostics/troubleshooting/view_service_logs.sh](../diagnostics/troubleshooting/view_service_logs.sh) with `errors`
4. Run the issue-specific script from this document
5. Check [swagger.md](swagger.md)
6. If unresolved, open a GitHub issue with script outputs
