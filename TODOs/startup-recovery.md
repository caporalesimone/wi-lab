# Startup recovery: show what was cleaned up

**Priority:** 4
**Status:** PROPOSED (reduced on 2026-11-28)

The cleanup itself is done (`wilab/runtime_cleanup.py`, Fable STAB-4): at
startup Wi-Lab stops the hostapd and dnsmasq processes a previous run left,
removes its stale firewall rules and captive portal chains, runtime files and
`wilab-ifbN` QoS devices, and resets every radio when discovery adds it. Each
action is written to the journal (`Stopped orphan ...`, `Removed stale ...`).
Wi-Lab uses no network namespaces.

## What is left

- Report the last startup cleanup in the API, for an operator who cannot read
  the journal: for example `checks.startup_cleanup` in `GET /status` with the
  time, the counts per kind (processes, rules, files, QoS devices) and the steps
  that failed.
- A failed step is already logged as `ERROR`; decide whether it should also make
  `service.health` `degraded` until the next successful cleanup.

## Success criteria

- `GET /status` shows what the last startup cleaned and what it could not.
- Tests: a startup with leftovers of each kind, and one with a failing step.
