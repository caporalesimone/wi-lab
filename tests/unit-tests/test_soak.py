"""T-20: about 14 simulated hours of random faults on four antennas; the networks must survive.

The real NetworkManager, watchdog, reservations and firewall bookkeeping run;
hostapd and dnsmasq are simulated processes, every host command is a fake, and
the clock is a FakeClock. Each step is one watchdog tick (5 s) per antenna, with
no thread and no wait.

The injector only adds faults the service is designed to absorb: at most two
AP restores per antenna in any hour (the budget is three), one armed start
failure at a time, single iptables failures and slow probes. Inside that
envelope a quarantine, a lost reservation, an ERROR record or a firewall rule
without its network is a bug. After the faults, 30 fault-free minutes, then:

- every reservation still holds and has its network running;
- no antenna is quarantined, restoring or owed a restore;
- the firewall bookkeeping (NAT, Internet block, isolation, host guard)
  matches the running networks exactly.
"""

import logging
import os
import random
from collections import Counter, defaultdict
from ipaddress import IPv4Network
from unittest.mock import Mock

import pytest
from conftest import registry_of
from helpers import FakeClock

from wilab import heartbeat
from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.network import commands, host_guard
from wilab.network import dhcp as dhcp_module
from wilab.network.commands import CommandError
from wilab.network.dhcp import DhcpServerError
from wilab.reservation import ReservationManager
from wilab.wifi import manager as manager_module
from wilab.wifi import startup as startup_module
from wilab.wifi import watchdog as watchdog_module
from wilab.wifi.hostapd import (
    HostapdError,
    HostapdInitFailure,
    HostapdRadioFailure,
    HostapdSegfault,
)
from wilab.wifi.manager import NetworkManager
from wilab.wifi.watchdog import DeviceWatch

RESTORE_WINDOW = 3600.0   # the default budget window (config.yaml watchdog)

pytestmark = pytest.mark.slow

DEVICES = ("wlan0", "wlan1", "wlan2", "wlan3")
# WILAB_SOAK_STEPS and WILAB_SOAK_SEED run a longer or another simulation.
STEPS = int(os.environ.get("WILAB_SOAK_STEPS", "10000"))   # 5 s each: about 14 hours
QUIET_STEPS = 360         # 30 minutes without faults before the checks
SEED = int(os.environ.get("WILAB_SOAK_SEED", "20261127"))


class SimHostapd:
    """Plays HostapdManager: processes that die, probes that time out, starts that fail."""

    def __init__(self) -> None:
        self.alive: dict[str, bool] = {}
        self.armed: dict[str, Exception] = {}
        self.slow_probes: Counter[str] = Counter()
        self.disabled_answers: Counter[str] = Counter()
        self.starts: Counter[str] = Counter()
        self.on_change = None

    def start(self, *, net_id: str, **_kwargs) -> None:
        if net_id in self.alive:
            raise HostapdError(f"hostapd cleanup required for {net_id}")
        self.starts[net_id] += 1
        if net_id in self.armed:
            raise self.armed.pop(net_id)
        self.alive[net_id] = True

    def stop(self, net_id: str) -> None:
        self.alive.pop(net_id, None)

    def is_tracked(self, net_id: str) -> bool:
        return net_id in self.alive

    def is_running(self, net_id: str) -> bool:
        return self.alive.get(net_id, False)

    def is_enabled(self, net_id: str) -> bool | None:
        if not self.is_running(net_id):
            return False
        if self.slow_probes[net_id]:
            self.slow_probes[net_id] -= 1
            return None
        if self.disabled_answers[net_id]:
            self.disabled_answers[net_id] -= 1
            return False
        return True

    def report_exit(self, _net_id: str) -> None:
        pass

    def status(self) -> dict:
        return {"running": any(self.alive.values()), "instances": []}


class SimDhcp:
    """Plays DhcpServer: dnsmasq processes that die, starts that fail once."""

    def __init__(self) -> None:
        self.running: dict[str, bool] = {}
        self.armed: set[str] = set()

    def start(self, net_id: str, *_args, **_kwargs) -> dict:
        if net_id in self.running:
            raise DhcpServerError(f"DHCP server already running for {net_id}")
        if net_id in self.armed:
            self.armed.discard(net_id)
            raise DhcpServerError("dnsmasq exited at once: address in use")
        self.running[net_id] = True
        return {}

    def stop(self, net_id: str, keep_leases: bool = False) -> None:
        self.running.pop(net_id, None)

    def is_running(self, net_id: str) -> bool:
        return self.running.get(net_id, False)

    def list_active(self) -> list[str]:
        return list(self.running)

    def get_subnet_info(self, _net_id: str) -> dict:
        return {}

    def status(self) -> dict:
        return {"running": bool(self.running)}


class SimIptables:
    """A rule store that answers like iptables: -A -I -D -C -N -F -X -S, exit codes 1 and 2."""

    BUILTIN = ("INPUT", "FORWARD", "OUTPUT", "PREROUTING", "POSTROUTING")

    def __init__(self) -> None:
        self.chains: dict[tuple[str, str], list[tuple[str, ...]]] = {}

    def _chain(self, table: str, name: str) -> list[tuple[str, ...]]:
        key = (table, name)
        if key not in self.chains:
            if name not in self.BUILTIN:
                raise CommandError(f"iptables: No chain/target/match by that name ({name})", returncode=2)
            self.chains[key] = []
        return self.chains[key]

    def run(self, args: list[str]) -> str:
        args = list(args)
        while args and args[0] == "-w":
            args = args[2:] if len(args) > 1 and args[1].isdigit() else args[1:]
        table = "filter"
        if args[:1] == ["-t"]:
            table, args = args[1], args[2:]
        if not args:
            return ""
        option, rest = args[0], args[1:]
        if option == "-S":
            if rest:
                rules = self._chain(table, rest[0])
                return "\n".join([f"-N {rest[0]}" if rest[0] not in self.BUILTIN else f"-P {rest[0]} ACCEPT"]
                                 + [" ".join(("-A", rest[0], *rule)) for rule in rules])
            return "\n".join(f"-N {name}" for (tbl, name) in self.chains if tbl == table and name not in self.BUILTIN)
        if option == "-N":
            if (table, rest[0]) in self.chains:
                raise CommandError("iptables: Chain already exists.", returncode=1)
            self.chains[(table, rest[0])] = []
            return ""
        if option == "-F":
            if rest:
                self._chain(table, rest[0]).clear()
            return ""
        if option == "-X":
            self._chain(table, rest[0])
            del self.chains[(table, rest[0])]
            return ""
        chain, rule = rest[0], tuple(rest[1:])
        if option == "-I" and rule and rule[0].isdigit():
            position, rule = int(rule[0]) - 1, rule[1:]
        else:
            position = 0
        self._check_target(table, rule)
        rules = self._chain(table, chain)
        if option == "-A":
            rules.append(rule)
        elif option == "-I":
            rules.insert(position, rule)
        elif option in ("-C", "-D"):
            if rule not in rules:
                raise CommandError("iptables: Bad rule (does a matching rule exist in that chain?).", returncode=1)
            if option == "-D":
                rules.remove(rule)
        return ""

    def _check_target(self, table: str, rule: tuple[str, ...]) -> None:
        if "-j" in rule:
            target = rule[rule.index("-j") + 1]
            if target.startswith(("WILAB", "wilab")):
                self._chain(table, target)


class SimHost:
    """Addresses for `ip`, iptables and ip6tables rule stores, sysctl, and one-shot iptables failures."""

    def __init__(self, execute_command) -> None:
        self.addresses: dict[str, set[str]] = defaultdict(set)
        self.iptables_failures = 0
        self.iptables = SimIptables()
        self.ip6tables = SimIptables()
        self.sysctl: dict[str, str] = {}
        self._execute_command = execute_command

    def ip(self, args: list[str]) -> str:
        if args[:2] == ["addr", "add"]:
            self.addresses[args[-1]].add(args[2])
        elif args[:2] == ["addr", "flush"]:
            self.addresses[args[-1]].clear()
        elif "show" in args:
            interface = args[-1]
            return " ".join(f"inet {address}" for address in sorted(self.addresses[interface]))
        return ""

    def command(self, cmd: list[str], *args, **kwargs) -> str:
        if cmd[0] in ("iptables", "ip6tables"):
            if self.iptables_failures:
                self.iptables_failures -= 1
                raise CommandError("Another app is currently holding the xtables lock", returncode=4)
            return (self.iptables if cmd[0] == "iptables" else self.ip6tables).run(cmd[1:])
        if cmd[0] == "sysctl":
            if cmd[1] == "-w":
                key, value = cmd[2].split("=", 1)
                self.sysctl[key] = value
                return ""
            return self.sysctl.get(cmd[2], "0")
        if cmd[:2] == ["ip", "addr"] or cmd[:3] == ["ip", "-4", "-o"]:
            return self.ip(cmd[1:])
        return self._execute_command(cmd, *args, **kwargs)


def _request(rng: random.Random, device: str) -> NetworkCreateRequest:
    band = rng.choice(["2.4ghz", "5ghz"])
    encryption = rng.choice(["open", "wpa2", "wpa3", "wpa2-wpa3"])
    return NetworkCreateRequest(
        ssid=f"soak-{device}", band=band, channel=rng.choice([1, 6, 11] if band == "2.4ghz" else [36, 44, 149]),
        encryption=encryption, password=None if encryption == "open" else "soak-password",
        internet_enabled=rng.random() < 0.6, tx_power_level=4,
    )


@pytest.fixture
def lab(monkeypatch):
    clock = FakeClock().install(monkeypatch, watchdog_module, manager_module, startup_module)
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)
    host = SimHost(commands.execute_command)
    monkeypatch.setattr(commands, "execute_command", host.command)
    monkeypatch.setattr(host_guard, "execute_command", host.command)
    from wilab.network import nat
    monkeypatch.setattr(nat, "execute_command", host.command)
    for module in (manager_module, startup_module):
        monkeypatch.setattr(module, "execute_ip", host.ip)
    monkeypatch.setattr(dhcp_module, "execute_command", host.command)

    devices = registry_of(*DEVICES)
    manager = NetworkManager(load_config(), devices)
    hostapd, dhcp = SimHostapd(), SimDhcp()
    manager.hostapd_manager = hostapd   # type: ignore[assignment]
    manager.dhcp_server = dhcp          # type: ignore[assignment]
    manager.clients._dhcp_server = dhcp  # type: ignore[assignment]
    monkeypatch.setattr(manager._channel_manager, "validate_network", Mock(return_value=None))
    monkeypatch.setattr(manager.tx_power, "set_level", Mock())
    monkeypatch.setattr(manager.tx_power, "read_dbm", Mock(return_value=20.0))
    usb_resets = Mock()
    monkeypatch.setattr(manager.recovery, "schedule", usb_resets)
    reservations = ReservationManager(
        devices, cleanup=manager.release_device, cleanup_due=manager.cleanup_due,
        cleanup_wait=manager.cleanup_wait, before_release=manager.cancel_start,
        on_expiry=manager.forget_finished_start,
    )
    yield clock, host, manager, hostapd, dhcp, reservations, usb_resets
    manager.watchdog.stopping.set()


def _restores_in_window(watch: DeviceWatch, now: float) -> int:
    return sum(1 for t in watch.restores if now - t <= RESTORE_WINDOW)


def _dhcp_restarts_in_window(watch: DeviceWatch, now: float) -> int:
    return sum(1 for t in watch.dhcp_restores if now - t <= RESTORE_WINDOW)


def test_networks_survive_hours_of_random_faults(lab, caplog):
    clock, host, manager, hostapd, dhcp, reservations, usb_resets = lab
    rng = random.Random(SEED)
    owned = {}
    for device in DEVICES:
        reservation = reservations.create(0, device)
        manager.start_network(device, _request(rng, device), None)
        owned[device] = reservation
    watches = {device: DeviceWatch(device) for device in DEVICES}
    faults: Counter[str] = Counter()

    def inject(device: str) -> None:
        watch = watches[device]
        now = clock.monotonic()
        # Faults that end in a whole-network restore: at most 2 per hour per antenna. An
        # armed start failure is consumed by the next restore: retried inside the start
        # (radio) or owed and retried later (configuration), never a restore of its own.
        may_restore = (
            _restores_in_window(watch, now) <= 1 and device not in manager.watchdog._pending
            and watch.misses == 0
        )
        roll = rng.random()
        if roll < 0.0012 and may_restore and hostapd.is_running(device):
            hostapd.alive[device] = False                       # hostapd crashed (SIGSEGV)
            faults["hostapd_died"] += 1
        elif roll < 0.0024 and may_restore and dhcp.is_running(device) and _dhcp_restarts_in_window(watch, now) <= 1:
            dhcp.running[device] = False                        # dnsmasq died
            faults["dnsmasq_died"] += 1
        elif roll < 0.0040:
            hostapd.slow_probes[device] += 1                    # hostapd_cli timed out once
            faults["slow_probe"] += 1
        elif roll < 0.0048 and watch.misses == 0:
            hostapd.disabled_answers[device] += 1               # one "not ENABLED" answer
            faults["not_enabled_once"] += 1
        elif roll < 0.0060 and not host.iptables_failures:
            host.iptables_failures = 1                          # xtables lock held once
            faults["iptables_once"] += 1
        elif roll < 0.0075 and may_restore and device not in hostapd.armed:
            # The next start fails once, with one of the failure classes of a start.
            hostapd.armed[device] = rng.choice([
                HostapdSegfault(f"hostapd segfault on {device}"),
                HostapdInitFailure(f"hostapd exited with code 1 on {device}: beacon setup failed"),
                HostapdRadioFailure(f"AP not ready on {device} (hostapd state: HT_SCAN)"),
                HostapdError(f"hostapd exited with code 1 on {device}"),
            ])
            faults["start_armed"] += 1
        elif roll < 0.0082 and may_restore and device not in dhcp.armed:
            dhcp.armed.add(device)                              # the next dnsmasq start fails once
            faults["dhcp_start_armed"] += 1
        elif roll < 0.0090 and may_restore and hostapd.is_running(device) and not host.iptables_failures:
            # hostapd dies and the xtables lock is held when the restore cleans up (REV-10).
            hostapd.alive[device] = False
            host.iptables_failures = 1
            faults["hostapd_died_cleanup_fails"] += 1

    def step(with_faults: bool) -> None:
        if with_faults:
            for device in DEVICES:
                inject(device)
        clock.advance(watchdog_module.TICK)
        for device in DEVICES:
            manager.watchdog.tick(reservations, watches[device])

    with caplog.at_level(logging.WARNING):
        for _ in range(STEPS):
            step(with_faults=True)
        for _ in range(QUIET_STEPS):
            step(with_faults=False)

    restores = sum(r.ap_restarts for r in owned.values())
    dhcp_restarts = sum(r.dhcp_restarts for r in owned.values())

    # Every reservation holds and has its network.
    for device, reservation in owned.items():
        assert reservations.get(reservation.reservation_id) is reservation, (device, faults)
        assert device in manager.active, device
        assert hostapd.is_running(device) and dhcp.is_running(device), device
    usb_resets.assert_not_called()
    assert reservations.recovery_snapshot() == {}
    assert manager.watchdog.states == {} and manager.watchdog._pending == {}
    assert manager.cleanup_failures() == {} and not manager._stop_failed

    # The firewall bookkeeping matches the running networks exactly.
    active = manager.active
    nat = manager.nat_manager
    assert nat._nat_networks == {d for d, n in active.items() if n.internet_enabled}
    assert set(nat._blocked_rules) == {d for d, n in active.items() if not n.internet_enabled}
    assert manager.isolation_manager._active_subnets == {n.subnet for n in active.values()}
    assert set(manager.host_guard._guarded) == set(active)
    for device, network in active.items():
        assert network.subnet is not None
        net = IPv4Network(network.subnet)
        assert host.addresses[device] == {f"{net[1]}/{net.prefixlen}"}, device

    # The run exercised what it claims to.
    assert faults["hostapd_died"] >= 15 and faults["iptables_once"] >= 20 and faults["start_armed"] >= 10, faults
    assert restores >= 30 and dhcp_restarts >= 20, (restores, dhcp_restarts, faults)
    messages = [r.getMessage() for r in caplog.records]
    assert sum("AP watchdog cleanup on" in m for m in messages) >= 3   # REV-10: retried, not quarantined
    assert sum("AP restore failed on" in m for m in messages) >= 5    # owed restores (WD-2)

    # Rule 1 of ARCH-10: faults the service absorbs by design are never an ERROR.
    errors = [f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], errors[:5]
