"""WD-7: the watchdog checks what a running network needs beyond its processes."""

import threading
from unittest.mock import Mock

import pytest

from wilab import heartbeat
from wilab.api import dependencies
from wilab.models import NetworkStatus
from wilab.network import captive, isolation, nat
from wilab.network.commands import CommandError
from wilab.network.isolation import IsolationManager
from wilab.network.nat import NatManager
from wilab.wifi import manager as manager_module
from wilab.wifi import watchdog as watchdog_module


class FakeFirewall:
    """In-memory iptables: -A/-I add, -D removes, -C checks, -S lists nothing."""

    def __init__(self) -> None:
        self.rules: list[tuple[str, tuple[str, ...]]] = []
        self.changes: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs) -> str:
        table = "filter"
        if args[:1] == ["-t"]:
            table, args = args[1], args[2:]
        op, rest = args[0], args[1:]
        if op == "-S":
            return ""
        if op == "-I":  # -I CHAIN POS rule...
            rest = [rest[0], *rest[2:]]
        key = (table, tuple(rest))
        if op == "-C":
            if key not in self.rules:
                raise CommandError("Bad rule", returncode=1)
            return ""
        self.changes.append(args)
        if op == "-A":
            self.rules.append(key)
        elif op == "-I":
            self.rules.insert(0, key)
        elif op == "-D":
            self.rules.remove(key)
        return ""


@pytest.fixture
def firewall(monkeypatch) -> FakeFirewall:
    fw = FakeFirewall()
    for module in (nat, isolation, captive):
        monkeypatch.setattr(module, "execute_iptables", fw)
    return fw


@pytest.fixture
def nat_manager(monkeypatch, firewall) -> NatManager:
    forward = {"value": "1"}

    def sysctl(key, value=None):
        if value is not None:
            forward["value"] = value
        return forward["value"] + "\n"

    monkeypatch.setattr(nat, "execute_sysctl", sysctl)
    mgr = NatManager("eth0")
    mgr.forward = forward  # type: ignore[attr-defined]
    return mgr


# --------------------------------------------------------------------------- NAT


def test_intact_nat_needs_no_repair(nat_manager, firewall):
    nat_manager.enable_nat("wlan0", "wlan0", "192.168.10.0/24")
    firewall.changes.clear()
    assert nat_manager.verify("wlan0", "wlan0", "192.168.10.0/24") == []
    assert firewall.changes == []


def test_flushed_nat_rules_are_restored(nat_manager, firewall):
    nat_manager.enable_nat("wlan0", "wlan0", "192.168.10.0/24")
    before = list(firewall.rules)
    firewall.rules = [r for r in firewall.rules if r[0] != "nat"]  # iptables -t nat -F POSTROUTING
    assert nat_manager.verify("wlan0", "wlan0", "192.168.10.0/24") == ["NAT POSTROUTING rule"]
    assert sorted(firewall.rules) == sorted(before)


def test_ip_forward_reset_is_restored(nat_manager, firewall):
    nat_manager.enable_nat("wlan0", "wlan0", "192.168.10.0/24")
    nat_manager.forward["value"] = "0"
    assert nat_manager.verify("wlan0", "wlan0", "192.168.10.0/24") == ["ip_forward"]
    assert nat_manager.forward["value"] == "1"


def test_lost_internet_block_is_reinstalled_in_order(nat_manager, firewall):
    nat_manager.block_internet("wlan0", "wlan0")
    order = list(firewall.rules)
    firewall.rules.pop(1)  # a host firewall reload dropped one rule
    assert nat_manager.verify("wlan0", "wlan0", "192.168.10.0/24") == ["Internet block rules"]
    assert firewall.rules == order  # TCP reset stays before the generic reject


# --------------------------------------------------------------------------- isolation


def test_lost_isolation_rules_are_restored(firewall):
    mgr = IsolationManager()
    mgr.add_network("192.168.10.0/24")
    mgr.add_network("192.168.11.0/24")
    assert len(firewall.rules) == 2
    firewall.rules.clear()
    repaired = mgr.verify()
    assert sorted(repaired) == [
        "isolation 192.168.10.0/24 -> 192.168.11.0/24", "isolation 192.168.11.0/24 -> 192.168.10.0/24",
    ]
    assert len(firewall.rules) == 2
    assert mgr.verify() == []


# --------------------------------------------------------------------------- manager


@pytest.fixture
def running(monkeypatch):
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    device = config.antennas[0].device_id
    status = NetworkStatus(interface=device, active=True, subnet="192.168.10.0/24")
    monkeypatch.setitem(mgr.active, device, status)
    monkeypatch.setattr(mgr.nat_manager, "verify", Mock(return_value=[]))
    monkeypatch.setattr(mgr.isolation_manager, "verify", Mock(return_value=[]))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock())
    return mgr, device


def test_missing_gateway_is_restored_and_dhcp_restarted(monkeypatch, running):
    mgr, device = running
    calls: list[list[str]] = []

    def ip(args):
        calls.append(args)
        return "3: wlan0    inet6 fe80::1/64 scope link\n"  # the IPv4 gateway is gone

    monkeypatch.setattr(manager_module, "execute_ip", ip)
    assert mgr.verify_network(device) == (["gateway address"], False)
    assert ["addr", "add", "192.168.10.1/24", "dev", device] in calls
    mgr.dhcp_server.stop.assert_called_once_with(device)
    mgr.dhcp_server.start.assert_called_once()


def test_present_gateway_is_left_alone(monkeypatch, running):
    mgr, device = running
    monkeypatch.setattr(
        manager_module, "execute_ip",
        lambda args: f"3: {device}    inet 192.168.10.1/24 brd 192.168.10.255 scope global {device}\n",
    )
    assert mgr.verify_network(device) == ([], False)
    mgr.dhcp_server.start.assert_not_called()


def test_broken_captive_portal_asks_for_a_network_restore(monkeypatch, running):
    mgr, device = running
    monkeypatch.setattr(
        manager_module, "execute_ip", lambda args: f"inet 192.168.10.1/24 scope global {device}",
    )
    portal = Mock()
    portal.problems.return_value = ["captive portal server"]
    monkeypatch.setitem(mgr.captive_portals, device, portal)
    assert mgr.verify_network(device) == (["captive portal server"], True)


def test_captive_portal_problems_detects_a_dead_server_and_missing_rules(firewall):
    portal = captive.CaptivePortal(
        interface="wlan0", net_id="wlan0", gateway="192.168.10.1",
        context=dict, lookup_mac=lambda ip: None, firewall_lock=threading.Lock(),
    )
    assert portal.problems() == [
        "captive portal server", "captive portal PREROUTING rule", "captive portal FORWARD rule",
    ]


# --------------------------------------------------------------------------- watchdog


def test_watchdog_checks_every_sixth_healthy_tick_and_restores_on_request(monkeypatch):
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(mgr.active, device, NetworkStatus(interface=device, active=True))
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)
    monkeypatch.setattr(mgr.hostapd_manager, "is_running", Mock(return_value=True))
    monkeypatch.setattr(mgr.hostapd_manager, "is_enabled", Mock(return_value=True))
    monkeypatch.setattr(mgr.dhcp_server, "is_running", Mock(return_value=True))
    verify = Mock(side_effect=[(["NAT POSTROUTING rule"], False), (["captive portal server"], True)])
    monkeypatch.setattr(mgr, "verify_network", verify)
    restore = Mock()
    monkeypatch.setattr(mgr.watchdog, "_restore_ap", restore)
    ticks = 13
    monkeypatch.setattr(
        mgr.watchdog.stopping, "wait", Mock(side_effect=[False] * ticks + [True]),
    )
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: 0.0)
    mgr.watchdog._watch(reservations, device)
    assert verify.call_count == 2  # ticks 6 and 12
    restore.assert_called_once()  # tick 13, after the captive portal check failed


def test_failed_rule_checks_raise_instead_of_repairing(monkeypatch, firewall):
    """REV-3 (unit-test-3): `-C` that fails for another reason (xtables lock) is not "missing"."""
    iso = IsolationManager()
    iso.add_network("192.168.10.0/24")
    iso.add_network("192.168.11.0/24")
    portal = captive.CaptivePortal(
        interface="wlan0", net_id="wlan0", gateway="192.168.10.1",
        context=dict, lookup_mac=lambda ip: None, firewall_lock=threading.Lock(),
    )
    before = list(firewall.rules)

    def locked(args, **kwargs):
        if "-C" in args:
            raise CommandError("Another app is currently holding the xtables lock", returncode=4)
        return firewall(args, **kwargs)

    for module in (isolation, captive):
        monkeypatch.setattr(module, "execute_iptables", locked)
    with pytest.raises(CommandError):
        iso.verify()
    with pytest.raises(CommandError):
        portal.problems()
    assert firewall.rules == before


def test_failed_check_skips_the_watchdog_round(monkeypatch):
    """The watchdog reads a failed check as "cannot verify now", never as a broken network."""
    config = dependencies.get_config()
    mgr = dependencies.get_manager(config)
    watchdog = watchdog_module.NetworkWatchdog(mgr)
    monkeypatch.setattr(mgr, "verify_network", Mock(side_effect=CommandError("lock", returncode=4)))
    assert watchdog._verify("wls16") == ""
