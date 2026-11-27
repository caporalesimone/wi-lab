"""Firewall on the real service: lock handling (NET-1), rules behind a 200 (NET-2, NET-4)
and the host guard (SEC-3), also when it is lost (e2e-test-11)."""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from wilab_e2e import Antenna, Server, WiLab, detail_code, reserve_with_budget, wait_for

RADIOS = [("2.4ghz", 6), ("5ghz", 36)]


def test_concurrent_cycles_with_status_polling(wilab: WiLab, server: Server) -> None:
    """NET-1: parallel create/delete on every antenna while /status reads the firewall."""
    start = time.time()
    antennas = [wilab.reserve(interface) for interface in wilab.interfaces()]
    stop = threading.Event()
    status_codes: Counter = Counter()

    def poll_status() -> None:
        while not stop.is_set():
            status_codes[wilab.http.get("/status").status_code] += 1
            time.sleep(0.2)

    def cycles(index: int) -> Counter:
        antenna = antennas[index]
        band, channel = RADIOS[index % len(RADIOS)]
        results: Counter = Counter()
        for _ in range(10):
            response = wilab.create(antenna, ssid=f"wilab-fw-{index}", band=band, channel=channel)
            results[(response.status_code, detail_code(response))] += 1
            results[("delete", wilab.delete_network(antenna))] += 1
        return results

    poller = threading.Thread(target=poll_status, daemon=True)
    poller.start()
    try:
        with ThreadPoolExecutor(len(antennas)) as pool:
            per_antenna = list(pool.map(cycles, range(len(antennas))))
    finally:
        stop.set()
        poller.join(timeout=5)

    for antenna, results in zip(antennas, per_antenna, strict=True):
        assert results == Counter({(200, None): 10, ("delete", 200): 10}), antenna.display_name
        assert not wilab.device(antenna.interface).get("recovery_state")
    assert set(status_codes) == {200}, status_codes
    journal = server.journal(start)
    assert "xtables lock" not in journal
    assert "quarantin" not in journal.lower()


def test_create_waits_for_a_held_xtables_lock(wilab: WiLab, server: Server) -> None:
    """NET-1: another program holding the legacy xtables lock delays a create, never fails it."""
    if server.iptables_backend() != "legacy":
        pytest.skip("nf_tables backend has no xtables lock")
    antenna = wilab.reserve()
    start = time.time()
    with server.hold_xtables_lock(2):
        response = wilab.create(antenna)
    assert response.status_code == 200, response.text
    assert "xtables lock" not in server.journal(start)


@pytest.mark.parametrize("internet", [True, False])
def test_success_means_the_firewall_is_in_place(wilab: WiLab, server: Server, internet: bool) -> None:
    """NET-2: a 200 create has the NAT rules it reports, and none when Internet is off.

    The failure path (NAT or isolation cannot be applied -> 500 and rollback)
    has no safe live trigger on a shared host; it is covered by
    tests/unit-tests/test_startup_firewall.py.
    """
    antenna = wilab.reserve()
    start = time.time()
    response = wilab.create(antenna, internet_enabled=internet)
    assert response.status_code == 200, response.text
    network = wilab.http.get(f"/reservations/{antenna.reservation_id}/network").json()
    assert network["internet"]["enabled"] is internet
    nat = server.iptables_rules("nat")
    forward = server.iptables_rules("filter")
    masquerade = [line for line in nat.splitlines() if f"wilab-nat-{antenna.interface}" in line]
    accept = [line for line in forward.splitlines() if f"wilab-forward-{antenna.interface}" in line]
    if internet:
        assert any(network["ip"]["subnet"] in line and "MASQUERADE" in line for line in masquerade), nat
        assert len(accept) >= 2, forward
    else:
        assert not masquerade
    assert wilab.http.get("/status").json()["checks"]["iptables_nat"]["configured"] is True
    journal = server.journal(start)
    assert "Isolation rules applied" in journal
    assert "Isolation disabled for testing" not in journal  # NET-4
    assert wilab.delete_network(antenna) == 200
    leftover = server.iptables_rules("nat")
    assert f"wilab-nat-{antenna.interface}" not in leftover


# --------------------------------------------------------------------------- SEC-3

def _input_rules(rules: str) -> list[str]:
    return [line for line in rules.splitlines() if line.startswith("-A INPUT ")]


@pytest.mark.parametrize("captive_portal", [False, True])
def test_host_is_guarded_from_ap_clients(wilab: WiLab, server: Server, captive_portal: bool) -> None:
    """SEC-3: AP clients reach only DHCP, ICMP and, with a portal, DNS and the portal page."""
    antenna = wilab.reserve()
    assert wilab.create(antenna, captive_portal=captive_portal).status_code == 200
    chain = f"wilab-in-{antenna.interface}"
    for rules in (server.iptables_rules(), server.ip6tables_rules()):
        first = _input_rules(rules)[0]
        assert f"-i {antenna.interface}" in first and first.endswith(f"-j {chain}"), first
    v4 = [line for line in server.iptables_rules().splitlines() if line.startswith(f"-A {chain} ")]
    accepted = " ".join(line for line in v4 if line.endswith("-j ACCEPT"))
    assert "--dport 67" in accepted and "-p icmp" in accepted
    assert ("--dport 53" in accepted) is captive_portal
    if captive_portal:
        # The portal page, on captive_portal_port (8081 by default, no longer 80).
        network = wilab.http.get(f"/reservations/{antenna.reservation_id}/network").json()
        assert f"--dport {urlsplit(network['captive_portal']['url']).port or 80}" in accepted
    assert "8080" not in accepted and "--dport 22" not in accepted
    assert v4[-1] == f"-A {chain} -j REJECT --reject-with icmp-port-unreachable"

    assert wilab.delete_network(antenna) == 200
    assert chain not in server.iptables_rules() and chain not in server.ip6tables_rules()


def _network_up(wilab: WiLab, antenna: Antenna) -> bool:
    response = wilab.network(antenna)
    body = response.json()
    return response.status_code == 200 and body.get("active") is True and not body.get("runtime_state")


def _ap_restarts(wilab: WiLab, antenna: Antenna) -> int:
    response = wilab.network(antenna)
    return response.json()["restarts"]["ap"] if response.status_code == 200 else 0


def test_lost_host_guard_restores_the_network(wilab: WiLab, server: Server) -> None:
    """e2e-test-11: the guard jump and chain removed by hand, IPv4 and IPv6.

    The watchdog's network check (every 30 s) finds the guard missing and
    restores the whole network (`restarts.ap` grows, `last_reason:
    network_check_failed`), with no quarantine; the guard is back and the stop
    answers `200`. Uses one AP restore of the antenna's hourly budget.
    """
    antenna = reserve_with_budget(wilab, server, ap=1)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    chain = f"wilab-in-{antenna.interface}"
    server.remove_host_guard(antenna.interface)
    assert chain not in server.iptables_rules() and chain not in server.ip6tables_rules()

    assert wait_for(lambda: _ap_restarts(wilab, antenna) >= 1, timeout=50, interval=2)
    assert wait_for(lambda: _network_up(wilab, antenna), timeout=30, interval=2)
    network = wilab.network(antenna).json()
    assert network["restarts"]["ap"] == 1, network["restarts"]
    assert network["restarts"]["last_reason"] == "network_check_failed", network["restarts"]
    for rules in (server.iptables_rules(), server.ip6tables_rules()):
        first = _input_rules(rules)[0]
        assert f"-i {antenna.interface}" in first and first.endswith(f"-j {chain}"), first
    assert server.chain_rules(chain) and server.chain_rules(chain, ipv6=True)
    assert not wilab.device(antenna.interface).get("recovery_state")
    journal = server.journal(start)
    assert "host guard" in journal
    assert "quarantin" not in journal.lower()

    assert wilab.delete_network(antenna) == 200
    assert server.wilab_rules(antenna.interface) == []
