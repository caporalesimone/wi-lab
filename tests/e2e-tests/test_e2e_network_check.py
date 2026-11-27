"""WD-7: the watchdog repairs what a running network lost beyond its processes,
and leaves alone what the client turned off (e2e-test-12).

Only Wi-Lab's own state is touched: the gateway address on the AP interface and
the network's own MASQUERADE rule. The host interface and other rules are never
changed.
"""

import ipaddress
import shlex
import subprocess
import time

from wilab_e2e import Server, WiLab, wait_for


def _gateway(wilab: WiLab, reservation_id: str) -> str:
    subnet = ipaddress.ip_network(wilab.http.get(f"/access-point/{reservation_id}").json()["ip"]["subnet"])
    return f"{subnet[1]}/{subnet.prefixlen}"


def _has_address(interface: str, address: str) -> bool:
    out = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", interface], capture_output=True, text=True, check=True,
    ).stdout
    return address in out.split()


def _masquerade_rule(server: Server, interface: str) -> list[str] | None:
    for line in server.iptables_rules("nat").splitlines():
        if f"wilab-nat-{interface}" in line and "MASQUERADE" in line:
            return shlex.split(line)
    return None


def test_lost_gateway_and_nat_rule_are_repaired_in_place(wilab: WiLab, server: Server) -> None:
    antenna = wilab.reserve()
    start = time.time()
    assert wilab.create(antenna, internet_enabled=True).status_code == 200
    gateway = _gateway(wilab, antenna.reservation_id)
    rule = _masquerade_rule(server, antenna.interface)
    assert rule is not None and _has_address(antenna.interface, gateway)

    server.sudo(["ip", "addr", "del", gateway, "dev", antenna.interface])
    server.sudo(["iptables", "-w", "5", "-t", "nat", "-D", *rule[1:]])
    assert not _has_address(antenna.interface, gateway)

    # The check runs every 30 s on a healthy network.
    assert wait_for(lambda: _has_address(antenna.interface, gateway), timeout=45, interval=2)
    assert _masquerade_rule(server, antenna.interface) is not None
    body = wilab.http.get(f"/access-point/{antenna.reservation_id}").json()
    assert body["active"] is True and not body.get("runtime_state")
    journal = server.journal(start)
    assert "repaired in place" in journal
    assert "gateway address" in journal and "NAT POSTROUTING rule" in journal
    assert "quarantin" not in journal.lower()


def test_disabled_internet_stays_disabled(wilab: WiLab, server: Server) -> None:
    """e2e-test-12: the network check never gives back the Internet a client disabled.

    After `internet/disable` the MASQUERADE rule is gone and the
    `wilab-block-<if>` rules are in place; 40 s later (a check runs every
    30 s) nothing has changed and nothing was "repaired in place".
    """
    antenna = wilab.reserve()
    rid = antenna.reservation_id
    assert wilab.create(antenna, internet_enabled=True).status_code == 200
    subnet = wilab.http.get(f"/access-point/{rid}").json()["ip"]["subnet"]
    assert _masquerade_rule(server, antenna.interface) is not None
    start = time.time()
    assert wilab.http.post(f"/access-point/{rid}/internet/disable").status_code == 200

    def disabled() -> None:
        nat = server.iptables_rules("nat")
        assert not [line for line in nat.splitlines() if subnet in line and "MASQUERADE" in line], nat
        block = [line for line in server.iptables_rules().splitlines() if f"wilab-block-{antenna.interface}" in line]
        assert block, "no wilab-block rule"
        network = wilab.http.get(f"/access-point/{rid}").json()
        assert network["internet"]["enabled"] is False, network
        assert network["active"] is True and network["runtime_state"] is None, network

    disabled()
    time.sleep(40)
    disabled()
    assert wilab.http.get(f"/access-point/{rid}").json()["restarts"]["ap"] == 0
    assert "repaired in place" not in server.journal(start)
