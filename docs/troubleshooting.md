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
