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

For example, `API failure operation=start_network http_status=500 detail_code=1003`
identifies a terminal creation failure with an invalidated reservation. The
new diagnostic line is emitted only for API `5xx` responses. It omits request
paths, reservation IDs, tokens, and response bodies. Existing access and
application logs are unchanged.

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
- `GET /api/v1/status` returns `status: degraded` and an entry with
  `recovery_state: unavailable` (or `recovering` for a long time)
- a create returned `500 / 1003`; fewer antennas can be reserved

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
