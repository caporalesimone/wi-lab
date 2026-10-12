# Feature: Future Capabilities and the Role of `kind`

**Priority:** 4 (LOW)  
**Status:** PROPOSED (nothing here is implemented; read it before adding a capability)  

## Description

Reference for whoever adds the **first capability beyond `2.4ghz` and `5ghz`**. It records what
the capability model already provides, what is deliberately unused today, and what must be done
properly when a new capability is introduced. The model itself is in
[completed/device-capabilities.md](completed/device-capabilities.md); the code is in
[wilab/config.py](../wilab/config.py) (`Capability`, `CAPABILITY_REGISTRY`, `CapabilityDef`).

## Today: two capabilities, one kind

| Capability | `kind` | `group` | Meaning |
|------------|--------|---------|---------|
| `2.4ghz` | `radio` | `band` | The device may transmit on 2.4 GHz |
| `5ghz` | `radio` | `band` | The device may transmit on 5 GHz |

The three registry attributes that classify a capability are easy to confuse:

| Attribute | Question it answers | Used by the backend? |
|-----------|---------------------|----------------------|
| `kind` | What *sort of statement* is this (`radio` or `policy`)? | **No.** Published in `/status`; the reservation dialog groups the options by it |
| `group` | Which capabilities are alternatives of each other? | **Yes.** `GROUPS_REQUIRING_ONE` demands at least one enabled member per device (`band`) |
| `type` / `matchable` | How is the value stored and can a reservation ask for it? | **Yes.** An import-time guard accepts only boolean, matchable capabilities |

`kind` is **metadata for presentation**. With a single kind it has no visible effect today (the UI
shows group headings only when there are at least two kinds). It exists so that adding the first
`policy` capability needs no change of the catalogue, the API or the UI structure.

The `config.yaml` capability map is deliberately **flat** (`"2.4ghz": true`, `"5ghz": true`), with
the same identifiers as the API and the `band` field of a network. A `radio:` sub-section was
considered and rejected for now: the backend does not treat kinds differently, the key names would
stop matching the API vocabulary, and the file format of 4.0.0 would change for no behavioural gain.

## The two kinds

| Kind | Statement | Examples | Source of truth |
|------|-----------|----------|-----------------|
| `radio` | What the **hardware may transmit** | `wifi6`, `wifi6e`, `6ghz`, `dfs`, `160mhz`, `mesh`, `monitor-mode` | The administrator's declaration, informed by the adapter |
| `policy` | What the **administrator allows a user to change** | `change-ssid`, `change-password`, `change-channel` | A purely administrative choice: nothing in `iw` can tell it |

Both are declared in `config.yaml`, which stays authoritative: Wi-Lab never probes the hardware to
infer them and never edits the file (see `CLAUDE.md`).

## When a capability is added: do `kind` properly

Introducing a capability is one `Capability` member plus one registry entry. As soon as the new
capability has a `kind` different from the existing ones, `kind` stops being decoration and must be
**managed correctly**, not left as a label. The points to decide and implement in the same change:

1. **Pick the kind on purpose.** A capability is `radio` if it describes what the device can do on
   air, `policy` if it describes what a user may be allowed to do. If it fits neither, add a new
   `CapabilityKind` and document it here instead of stretching an existing one.
2. **Decide whether the configuration should show it.** If a second kind exists, grouping the
   capability map by kind in `config.yaml` and `config.example.yaml` starts to make sense (a
   `radio:` and a `policy:` section), because the two groups then differ in meaning and not only in
   label. This is a breaking change of the file format: it needs a migration note, a validator
   update (`wilab/config_validation.py`: unknown/duplicate/missing keys per section, one report) and
   a clear error for the old flat layout. Do not add a compatibility layer.
3. **Make the backend aware of the kind where it matters.** Examples: a `policy` capability needs an
   *enforcement point* (the endpoint that refuses the change); a `radio` capability may need a
   hardware cross-check in `--check-hardware`. Declaring `change-ssid: false` is meaningless until
   some endpoint refuses the change, so declaration and enforcement must be planned together.
4. **Rules by kind and group.** `GROUPS_REQUIRING_ONE` today only protects the `band` group. A
   policy capability set to `false` must **not** make a device invalid: the "at least one enabled"
   rule is scoped to the group on purpose (design decision D9 of the capabilities document).
5. **Reservation matching.** Decide whether a reservation can *ask for* the capability. A `policy`
   capability that is only declared and enforced is normally not matchable; the registry attribute
   `matchable` is where that is expressed. v1 requires every capability to be matchable (import-time
   guard); relaxing it means implementing the filtering in `ReservationManager`, not removing the guard.
6. **Presentation.** Keep the catalogue (`/status`), the Swagger texts and the reservation dialog
   consistent: group headings, labels and the "not guaranteed" style warnings where a capability
   depends on the driver (as for TX power control).
7. **Tests and documentation.** Registry and validator tests per kind, API tests for the catalogue,
   and an update of README, `docs/`, `config.example.yaml`, Swagger and the design document in the
   same change.

## Candidate capabilities (not planned)

| Capability | Kind | What it would need |
|------------|------|--------------------|
| `6ghz`, `wifi6`, `wifi6e` | radio | New band: channels, `hw_mode`, hostapd settings and a new `band` value; a Wi-Fi 6 flag alone changes no allocation rule beyond matching |
| `dfs`, `160mhz` | radio | Channel validation against the regulatory domain |
| `mesh`, `monitor-mode` | radio | A new network mode in the API, not only a flag |
| `change-ssid`, `change-password`, `change-channel` | policy | The enforcement point in the network endpoints, `matchable: false` |
| `max-clients: 50` | (quantitative) | `CapabilityType.INTEGER`, a matching rule (at least N) and runtime enforcement, see §3.1 of the capabilities document |

## Open questions

- Is a `radio:` / `policy:` split in `config.yaml` worth a file-format change, or should the flat map
  stay and `kind` remain catalogue metadata? Decide when the first non-radio capability is real.
- If no policy capability ever arrives, `kind` should be removed (enum, registry field, `/status`
  field, UI grouping): metadata nobody uses is a maintenance cost.
