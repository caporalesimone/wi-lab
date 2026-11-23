"""Firewall on the real service: lock handling (NET-1) and rules behind a 200 (NET-2, NET-4)."""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from wilab_e2e import Server, WiLab, detail_code

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
    network = wilab.http.get(f"/interface/{antenna.reservation_id}/network").json()
    assert network["internet_enabled"] is internet
    nat = server.iptables_rules("nat")
    forward = server.iptables_rules("filter")
    masquerade = [line for line in nat.splitlines() if f"wilab-nat-{antenna.interface}" in line]
    accept = [line for line in forward.splitlines() if f"wilab-forward-{antenna.interface}" in line]
    if internet:
        assert any(network["subnet"] in line and "MASQUERADE" in line for line in masquerade), nat
        assert len(accept) >= 2, forward
    else:
        assert not masquerade
    assert wilab.status()["checks"]["iptables_nat"]["configured"] is True
    journal = server.journal(start)
    assert "Isolation rules applied" in journal
    assert "Isolation disabled for testing" not in journal  # NET-4
    assert wilab.delete_network(antenna) == 200
    leftover = server.iptables_rules("nat")
    assert f"wilab-nat-{antenna.interface}" not in leftover
