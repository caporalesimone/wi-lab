# Test bench features: what would make Wi-Lab a better Wi-Fi test bench

**Priority:** 3 (HIGH for items 1-3)
**Status:** PROPOSED (2026-11-28)

Features around the access points: seeing what clients do, injecting faults,
measuring, automating and reporting. The settings of the access point itself
(IPv6, 802.1X, PMF, DHCP options, roaming...) are in
[ap-improvements.md](ap-improvements.md).

Why items 1-3 come first: on 2026-11-27 finding out why a phone connected as
Wi-Fi 5 instead of Wi-Fi 6 took `hostapd_cli`, the journal at debug level and a
manual beacon scan with the spare antenna. With client details, client events
and a capture of the association requests, the answer would have been on the
screen in a minute.

## Proposals

| # | Feature | What it is for | Notes |
|---|---|---|---|
| 1 | **Client details in the API**: negotiated generation (HT/VHT/HE), PHY rate in both directions, RSSI, retries, bytes, connected time | Answer "is the phone on Wi-Fi 6?" or "why is it slow?" without root on the host | From `hostapd_cli all_sta` and `iw station dump`; extends `clients` of `GET /access-point/{reservation_id}`. Continues [clients-info-and-statistics.md](clients-info-and-statistics.md) |
| 2 | **Client event log**: associations, refusals with their reason code, failed authentications (wrong password, PMF, generation required), DHCP leases | Why a client cannot connect | hostapd events (control socket) and dnsmasq; served by the event stream of [realtime-events.md](realtime-events.md) |
| 3 | **Packet capture download** (pcap) of a network, and **management frame capture** with the spare antenna in monitor mode | Analysis in Wireshark; see the association requests of a client | `tcpdump` on the AP interface; monitor mode on the other antenna, on the AP's channel |
| 4 | **Throughput server on the gateway** (iperf3, or a LibreSpeed page) reachable from the clients | Measure the Wi-Fi link without the Internet line in between | Opens one port in the host guard, only for that service, only on that network |
| 5 | **Fault injection** through the API: disconnect a client, change the password of a running network, DHCP that does not answer or gives a wrong gateway, DNS failures, AP restart | How a client recovers | Internet on/off and QoS already exist. Runtime hostapd commands must be checked on this VM first (see the hardware notes in [ap-improvements.md](ap-improvements.md)) |
| 6 | **"No Internet" distinct from "captive portal"**: controlled answers to the connectivity checks of Android, iOS and Windows | The "connected, no Internet" notifications and the operating system's captive portal handling | Local DNS and HTTP for `connectivitycheck.gstatic.com`, `captive.apple.com`, `www.msftconnecttest.com`... |
| 7 | **DNS manipulation** per network: overridden names, NXDOMAIN, delayed answers | Application tests (another server, resolution errors) | dnsmasq `address=` and options per network |
| 8 | **Timed scenarios**: a list of steps (at 30 s Internet off, at 60 s QoS "3G", at 90 s a client kicked...) | Repeatable, automated tests | A server-side runner fed by a JSON list of steps, bound to a reservation |
| 9 | **Environment scan**: nearby networks and channel use, with the spare antenna | Pick a clean channel; explain interference and low throughput | A manual scan like this was done on 2026-11-27 |
| 10 | **Controlled attenuation** | Simulated distance and roaming thresholds | TX power does not work on the MT7921U: needs programmable RF attenuators or a shielded box (hardware). Software side: [link-quality-simulation.md](link-quality-simulation.md) covers loss and latency only |
| 11 | **Roaming tests** with both antennas (same SSID, 802.11r/k/v), driven by the attenuator | Client handover times | Depends on items 13 and 14 of [ap-improvements.md](ap-improvements.md) |
| 12 | **Report per reservation**: clients, events, throughput, watchdog restarts, settings used | Attach the results to a test ticket | JSON or HTML, downloadable when the reservation ends |
| 13 | **Prometheus metrics** (`/metrics`) | Continuous monitoring of the bench and of long tests in Grafana | Reservations, networks, clients, restarts, quarantines, command durations |
| 14 | **Scheduled reservations and a queue** | Several testers on one bench without conflicts | A calendar or a queue in front of `POST /reservations` |
| 15 | **Webhooks / notifications** (reservation ended, client connected, fault) | Integration with CI and external test systems | On top of the event log (item 2); see [realtime-events.md](realtime-events.md) |

<a id="infrastructure"></a>
## Infrastructure (outside Wi-Lab)

Measured on 2026-11-27: one network carries 70-90 Mbit/s with a 400 Mbit/s PHY
link and no retries, while the VM's two virtual CPUs are 70-88% busy. The
adapters run at USB 2.0 (480 Mbit/s) through QEMU's emulated USB, with a generic
CPU model. In order of expected gain:

1. Pass a whole USB 3 controller to the VM (PCI passthrough) instead of single
   devices: no USB emulation.
2. CPU model `host` and at least 4 virtual CPUs.
3. Adapters on USB 3 ports (the MT7921U supports USB 3).
4. Wi-Lab on a physical machine, for performance measurements.

Until then, document the limit for testers: "about 80 Mbit/s per network on this
installation, limited by CPU and USB, not by the radio".

## Steps

1. Items 1 and 2: extend the client list and add the event log (the base of 12
   and 15).
2. Item 3: pcap download, then monitor-mode capture with the spare antenna.
3. Items 4 and 6: measuring and "no Internet" without external services.
4. Items 5, 7 and 8: faults and scenarios.
5. The rest when needed; item 10 needs hardware.
