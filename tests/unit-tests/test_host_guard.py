"""SEC-3: clients of a Wi-Lab AP cannot reach the Wi-Lab host itself."""

from unittest.mock import Mock

import pytest

from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.network import host_guard
from wilab.network.commands import CommandError
from wilab.network.host_guard import HostGuard
from wilab.wifi.manager import NetworkManager, StartupFailure


class FakeTable:
    """One iptables family: chains with ordered rules."""

    def __init__(self) -> None:
        self.chains: dict[str, list[list[str]]] = {"INPUT": []}

    def __call__(self, args: list[str], **kwargs) -> str:
        args = [a for a in args if a not in ("-w", "5")]
        op = args[0]
        if op == "-N":
            if args[1] in self.chains:
                raise CommandError("Chain already exists.")
            self.chains[args[1]] = []
        elif op == "-A":
            self.chains[args[1]].append(args[2:])
        elif op == "-I":
            self.chains[args[1]].insert(int(args[2]) - 1, args[3:])
        elif op in ("-D", "-C"):
            if args[2:] not in self.chains.get(args[1], []):
                raise CommandError("Bad rule (does a matching rule exist in that chain?)")
            if op == "-D":
                self.chains[args[1]].remove(args[2:])
        elif op == "-F":
            if args[1] not in self.chains:
                raise CommandError("No chain/target/match by that name.")
            self.chains[args[1]] = []
        elif op == "-X":
            if args[1] not in self.chains:
                raise CommandError("No chain/target/match by that name.")
            del self.chains[args[1]]
        elif op == "-S":
            chains = [args[1]] if len(args) > 1 else list(self.chains)
            lines = [] if len(args) > 1 else [f"-N {c}" for c in self.chains if c != "INPUT"]
            for c in chains:
                lines += ["-A " + c + " " + " ".join(r) for r in self.chains.get(c, [])]
            return "\n".join(lines)
        return ""


@pytest.fixture
def tables(monkeypatch):
    v4, v6 = FakeTable(), FakeTable()
    monkeypatch.setattr(host_guard, "execute_iptables", v4)
    monkeypatch.setattr(host_guard, "_ip6tables", v6)
    return v4, v6


def test_guard_allows_only_dhcp_and_icmp_and_is_first_in_input(tables):
    v4, v6 = tables
    v4.chains["INPUT"].append(["-j", "ACCEPT"])  # a permissive host rule
    HostGuard().add("wlan0", "wlan0")
    assert v4.chains["INPUT"][0][:2] == ["-i", "wlan0"]
    assert v4.chains["INPUT"][0][-2:] == ["-j", "wilab-in-wlan0"]
    assert v4.chains["wilab-in-wlan0"] == [
        ["-p", "udp", "--dport", "67", "-j", "ACCEPT"],
        ["-p", "icmp", "-j", "ACCEPT"],
        ["-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"],
        ["-j", "REJECT"],
    ]
    # IPv6: SSH listens on [::]:22 and is reachable over link-local addresses.
    assert v6.chains["wilab-in-wlan0"][-1] == ["-j", "REJECT"]
    assert v6.chains["INPUT"][0][-1] == "wilab-in-wlan0"


def test_captive_portal_keeps_dns_and_the_portal_page(tables):
    v4, _ = tables
    HostGuard().add("wlan0", "wlan0", captive_port=80)
    accepted = [r for r in v4.chains["wilab-in-wlan0"] if r[-1] == "ACCEPT"]
    assert ["-p", "udp", "--dport", "53", "-j", "ACCEPT"] in accepted
    assert ["-p", "tcp", "--dport", "53", "-j", "ACCEPT"] in accepted
    assert ["-p", "tcp", "--dport", "80", "-j", "ACCEPT"] in accepted
    assert not any("8080" in r for r in accepted)


def test_remove_deletes_everything_and_tolerates_missing_rules(tables):
    v4, v6 = tables
    guard = HostGuard()
    guard.add("wlan0", "wlan0")
    v6.chains["INPUT"].clear()  # someone flushed INPUT already
    guard.remove("wlan0")
    assert v4.chains == {"INPUT": []} and v6.chains == {"INPUT": []}
    assert not guard.has("wlan0")
    guard.remove("wlan0")  # nothing to do


def test_problems_reports_a_missing_jump(tables):
    v4, _ = tables
    guard = HostGuard()
    guard.add("wlan0", "wlan0")
    assert guard.problems("wlan0") == []
    v4.chains["INPUT"].clear()
    assert guard.problems("wlan0") == ["IPv4 host guard"]


def test_remove_stale_deletes_only_wilab_guards(tables):
    v4, v6 = tables
    HostGuard().add("wlan0", "wlan0")
    v4.chains["INPUT"].append(["-p", "tcp", "--dport", "22", "-j", "ACCEPT"])
    v4.chains["f2b-sshd"] = []
    HostGuard.remove_stale()
    assert v4.chains == {"INPUT": [["-p", "tcp", "--dport", "22", "-j", "ACCEPT"]], "f2b-sshd": []}
    assert v6.chains == {"INPUT": []}


def _request(**kwargs) -> NetworkCreateRequest:
    return NetworkCreateRequest(ssid="g", channel=6, encryption="open", band="2.4ghz", tx_power_level=4, **kwargs)


@pytest.fixture
def manager(monkeypatch, tables) -> NetworkManager:
    mgr = NetworkManager(load_config())
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "start", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    return mgr


def test_network_start_installs_the_guard_and_stop_removes_it(manager, tables):
    v4, _ = tables
    device = manager.config.antennas[0].device_id
    manager.start_network(device, _request(internet_enabled=False))
    assert f"wilab-in-{device}" in v4.chains
    manager.stop_network(device)
    assert f"wilab-in-{device}" not in v4.chains


def test_guard_failure_fails_the_startup_and_rolls_back(manager, tables, monkeypatch):
    v4, _ = tables
    device = manager.config.antennas[0].device_id

    def broken(args):
        if args[:1] == ["-N"]:
            raise CommandError("iptables: Permission denied")
        return v4(args)

    monkeypatch.setattr(host_guard, "execute_iptables", broken)
    with pytest.raises(StartupFailure, match="protect host") as failure:
        manager.start_network(device, _request(internet_enabled=False))
    assert not failure.value.radio
    assert device not in manager.active
    assert not manager.host_guard.has(device)
