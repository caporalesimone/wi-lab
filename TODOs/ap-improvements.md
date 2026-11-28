# Access point improvements: Wi-Fi network settings Wi-Lab does not cover yet

**Priority:** 3 (HIGH for the items marked *high*)
**Status:** PROPOSED (2026-11-28)

What a create can set today: band, channel, channel width (20/40/80 MHz), Wi-Fi
generation (4/5/6) with or without fallback (`enable_generation_fallback`),
encryption (open, WPA1, WPA2, WPA3, WPA2/WPA3), hidden SSID, Internet, captive
portal, QoS profile, the antenna's optional 802.11n/ac features
(`enable_ht_vht_capab`) and a TX power level.

This file lists the settings of the access point and of its network that are
missing. The test bench features around it (client details, events, captures,
fault injection...) are in [testbench-features.md](testbench-features.md).

## What the lab hardware allows (measured 2026-11-27/28)

Every item below is judged against the MT7921U, the adapter in use, on a QEMU VM
with USB passthrough. What was measured:

- **TX power has no effect in AP mode.** The level is accepted, but the driver
  keeps the regulatory maximum as its limit and the radio always transmits at its
  calibration (about 18 dBm). `iw dev <if> info` always reports 3 dBm; the real
  values are in `/sys/kernel/debug/ieee80211/<phy>/mt76/txpower_sku`. Changing the
  power of a running AP detached the adapter and hung the VM, so the runtime
  endpoints were removed in 4.1.0.
- **Wi-Fi 6 in AP mode is limited.** The driver does not support BSS color (the
  beacon says `BSS Color Disabled`) and its HE capabilities in AP mode are smaller
  than in station mode (no beamforming). A Redmi Note 14 Pro 5G saw the network as
  Wi-Fi 6 but connected only as Wi-Fi 5, and did not try a Wi-Fi 6-only network.
  Not yet checked with another Wi-Fi 6 client.
- **Throughput is limited by the VM, not the radio.** 70-90 Mbit/s per network
  with a 400 Mbit/s PHY link and no retries; the VM's two virtual CPUs are 70-88%
  busy (emulated USB 2.0 path, generic CPU model). See the infrastructure notes in
  [testbench-features.md](testbench-features.md#infrastructure).
- **No 6 GHz, 160 MHz or Wi-Fi 7.** The MT7921U is a 2.4/5 GHz Wi-Fi 6 adapter.

Every runtime command on a running AP (channel switch, power, reload) is a risk
on this setup: check it first on a test network, with the user's consent.

## Proposals

| # | Missing setting | What it lets a tester check | hostapd / dnsmasq | MT7921U | Priority |
|---|---|---|---|---|---|
| 1 | **IPv6** on the test networks (RA, SLAAC, DHCPv6) | Clients on IPv6-only and dual-stack networks; today every test network is IPv4 only | dnsmasq `enable-ra`, `dhcp-range` for IPv6; a routed prefix or NAT66 on the uplink | yes | high |
| 2 | **WPA2/WPA3-Enterprise (802.1X)** with hostapd's internal RADIUS | Company devices: PEAP, EAP-TLS with certificates, wrong credentials, expired certificate | `ieee8021x=1`, `eap_server=1`, `eap_user_file`, CA and server certificates | yes | high |
| 3 | **PMF (802.11w) choice** for WPA2: off, optional, required | Clients without PMF support, or that refuse it; today WPA2 has none and WPA3 requires it | `ieee80211w=0/1/2` | yes | medium |
| 4 | **OWE (Enhanced Open)**, and the open/OWE transition | "Open but encrypted" networks | `wpa_key_mgmt=OWE`, `owe_transition_ifname` | probably | medium |
| 5 | **WPA3 variants**: H2E only, hunting-and-pecking only, SAE groups | WPA3 compatibility of clients (Wi-Fi 6E requires H2E) | `sae_pwe=0/1/2`, `sae_groups` | yes | medium |
| 6 | **Mixed WPA/WPA2 (TKIP+CCMP)**, GCMP-256 | Old clients on mixed networks; modern ciphers | `wpa=3`, `wpa_pairwise=TKIP CCMP`, `rsn_pairwise=GCMP-256` | yes (GCMP to check) | low |
| 7 | **Beacon interval and DTIM period** | Power save, IoT and battery devices, delivery delays | `beacon_int`, `dtim_period` | yes | medium |
| 8 | **Pure legacy: 802.11b/g without HT, basic rates** | Old or embedded devices; a network without 802.11b rates | `ieee80211n=0`, `supported_rates`, `basic_rates` | yes | medium |
| 9 | **Client isolation inside one network**, and a client limit | Devices that must see each other (casting, printers) or must not; a full network | `ap_isolate=1`, `max_num_sta` | yes | medium |
| 10 | **MAC filters** (allow / deny list) | A refused client, controlled onboarding | `macaddr_acl`, `accept_mac_file`, `deny_mac_file`. Overlaps [client-controls.md](client-controls.md) part 1 | yes | low |
| 11 | **DHCP options**: lease time, range, fixed addresses, DNS server per network | Fast lease renewals, predictable addresses, another DNS for one test (today `dns_server` is global) | dnsmasq `dhcp-range` with lease time, `dhcp-host`, `dhcp-option=6` | yes | medium |
| 12 | **WMM and U-APSD** on or off | VoIP and power save; clients without WMM | `wmm_enabled=0`, `uapsd_advertisement_enabled` | yes | low |
| 13 | **802.11r/k/v** (fast roaming, neighbor reports, BSS transition) | Roaming between two APs with the same SSID (the lab has two antennas) | `ieee80211r`, `mobility_domain`, `rrm_neighbor_report`, `bss_transition` | yes, with both antennas | medium |
| 14 | **One SSID on 2.4 and 5 GHz** (a dual-band AP, one antenna per band) | Band choice and band steering of clients | Two coordinated networks on the two antennas, one reservation | yes | medium |
| 15 | **Channel switch announcement** on a running AP | Clients that follow a channel change (as after a radar event) | `hostapd_cli chan_switch` | to check: runtime command, risk of a hang | low |
| 16 | **Simulated DFS radar** | Client behaviour when the AP leaves a DFS channel | mt76 debugfs radar trigger | to check | low |
| 17 | **Advanced Wi-Fi 6**: BSS color, TWT, OFDMA / MU-MIMO settings | Wi-Fi 6 specific features | `he_bss_color`, `he_twt_*`, `he_mu_*` | mostly no: not supported by the driver in AP mode | low |
| 18 | **Wi-Fi 6E (6 GHz), 160 MHz, Wi-Fi 7** | Recent clients | — | no: needs other adapters (e.g. MT7922, MT7925) | depends on hardware |
| 19 | **Several SSIDs on one antenna** (multi-BSS) | A guest and a main network together | extra `bss=` sections | to check on the MT7921U | low |
| 20 | **WPS, Hotspot 2.0 / Passpoint** | IoT onboarding; operator networks | `wps_state`, `hs20=1` | yes | low |

## Notes per item

- **1 IPv6.** The host guard, isolation and NAT rules are IPv4 (`iptables`); the
  same rules are needed in `ip6tables`, or the test networks become reachable from
  each other over IPv6. Decide between a routed prefix (the lab network must
  delegate one) and NAT66.
- **2 Enterprise.** Users and certificates must come from the create body or from
  files on the host; never log the passwords. A wrong password must be visible in
  the client events ([testbench-features.md](testbench-features.md) item 2).
- **3 PMF, 5 WPA3 variants, 6 ciphers.** Small: new optional fields in
  `wifi.security`, validated against the encryption, like
  `enable_generation_fallback`.
- **13 and 14.** Need a reservation that holds both antennas, or two
  reservations linked by one request. The API has neither today.
- **15 and 16.** Try them on a test network first: runtime commands on a running
  AP have hung this VM twice (23/11 and 28/11).

## Steps

1. Items 3, 5, 7, 9, 11: optional fields, defaults equal to today's behaviour,
   one test per hostapd/dnsmasq line, and a check on the real radio.
2. Item 1 (IPv6) and item 2 (802.1X): each one a design note first.
3. Items 13 and 14: decide how one reservation holds two antennas.
4. The rest when a tester asks for it.
