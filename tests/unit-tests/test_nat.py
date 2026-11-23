"""Tests for NAT and Internet forwarding management."""

import pytest

from wilab.network.commands import CommandError
from wilab.network.nat import NatManager


def _recording_iptables(calls, listing=lambda args: ""):
    """Fake execute_iptables: lists with `listing`, reports every rule as missing, records changes."""

    def iptables(args):
        if "-S" in args:
            return listing(args)
        if "-C" in args:
            raise CommandError("iptables: Bad rule (does a matching rule exist in that chain?)")
        calls.append(args)
        return ""

    return iptables


def test_stale_cleanup_removes_only_owned_rules_and_duplicates(monkeypatch):
    rules = {
        "FORWARD": [
            '-A FORWARD -m comment --comment "wilab-isolation" -j DROP',
            '-A FORWARD -m comment --comment "wilab-forward-wlan0" -j ACCEPT',
            '-A FORWARD -m comment --comment "wilab-forward-wlan0" -j ACCEPT',
            '-A FORWARD -m comment --comment "other-wilab-nat-wlan0" -j ACCEPT',
        ],
        "POSTROUTING": [
            '-A POSTROUTING -m comment --comment "wilab-nat-wlan0" -j MASQUERADE',
            '-A POSTROUTING -m comment --comment "unrelated" -j MASQUERADE',
        ],
    }
    import shlex

    def iptables(args):
        if "-S" in args:
            return "\n".join(rules[args[-1]])
        chain = args[3] if args[:2] == ["-t", "nat"] else args[1]
        rule = args[3:] if args[:2] == ["-t", "nat"] else args[1:]
        index = next(i for i, line in enumerate(rules[chain]) if shlex.split(line)[1:] == rule)
        rules[chain].pop(index)
        return ""

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    manager = NatManager()
    manager.remove_stale_rules()
    manager.remove_stale_rules()
    assert len(rules["FORWARD"]) == 1 and "other-wilab" in rules["FORWARD"][0]
    assert len(rules["POSTROUTING"]) == 1 and "unrelated" in rules["POSTROUTING"][0]


def test_stale_cleanup_logs_failures_and_continues(monkeypatch, caplog):
    def iptables(args):
        if "-S" not in args:
            raise CommandError("deletion failed")
        if args[-1] == "FORWARD":
            raise CommandError("listing failed")
        return '-A POSTROUTING -m comment --comment wilab-nat-wlan0 -j MASQUERADE'

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    NatManager().remove_stale_rules()
    assert "Cannot list stale" in caplog.text
    assert "Cannot remove stale" in caplog.text


def test_nat_rules_use_only_the_selected_network_subnet(monkeypatch):
    import shlex

    calls = []
    monkeypatch.setattr("wilab.network.nat.execute_sysctl", lambda *args: None)

    def iptables(args):
        if "-C" in args:
            raise CommandError("missing")
        if "-S" in args:
            chain = args[-1]
            return "\n".join(
                shlex.join(call[2:] if call[:2] == ["-t", "nat"] else call)
                for call in calls
                if (call[:2] == ["-A", chain] or call[:4] == ["-t", "nat", "-A", chain])
            )
        calls.append(args)
        return ""

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    nat = NatManager("eth0")
    nat.enable_nat("wlan0", "a", "192.168.120.0/24")
    nat.enable_nat("wlan1", "b", "192.168.121.0/24")
    nat.disable_nat("wlan0", "a", "192.168.120.0/24")
    added = [c for c in calls if c[:4] == ["-t", "nat", "-A", "POSTROUTING"]]
    removed = [c for c in calls if c[:4] == ["-t", "nat", "-D", "POSTROUTING"]]
    assert len(added) == 2
    assert "192.168.120.0/24" in added[0] and "192.168.121.0/24" in added[1]
    assert removed and all("192.168.120.0/24" in c and "wilab-nat-a" in c for c in removed)


def test_internet_block_precedes_protection_and_is_removed_on_reenable(monkeypatch):
    calls = []
    monkeypatch.setattr("wilab.network.nat.execute_sysctl", lambda *args: None)

    def iptables(args):
        if "-S" in args:
            return "-P FORWARD DROP"
        if "-C" in args:
            raise CommandError("missing")
        calls.append(args)
        return ""

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    nat = NatManager("eth0")
    nat.disable_nat("wlan0", "a", "192.168.120.0/24")
    assert calls[0][:3] == ["-I", "FORWARD", "1"]
    assert calls[1][:3] == ["-I", "FORWARD", "1"]
    assert calls[2][:3] == ["-I", "FORWARD", "1"]
    assert ["-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset"] == calls[2][5:11]
    calls.clear()
    nat.enable_nat("wlan1", "b", "192.168.121.0/24")
    protect = next(c for c in calls if "wilab-protect-existing" in c)
    assert protect[:3] == ["-I", "FORWARD", "4"]
    calls.clear()
    nat.enable_nat("wlan0", "a", "192.168.120.0/24")
    assert calls[-1][:2] == ["-D", "FORWARD"]
    assert not nat._blocked_rules


def test_partial_internet_block_never_reports_success_and_can_be_cleaned(monkeypatch):
    calls = []

    def iptables(args):
        calls.append(args)
        if len(calls) == 2:
            raise CommandError("failed")

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    nat = NatManager("eth0")
    with pytest.raises(RuntimeError, match="Cannot block"):
        nat.block_internet("wlan0", "a")
    with pytest.raises(RuntimeError, match="Incomplete"):
        nat.block_internet("wlan0", "a")
    nat.unblock_internet("a")
    assert calls[-1][:2] == ["-D", "FORWARD"]
    assert not nat._blocked_rules


def test_unblock_failure_restores_previously_removed_rule(monkeypatch):
    calls = []

    def iptables(args):
        calls.append(args)
        if len(calls) == 5:
            raise CommandError("delete failed")

    monkeypatch.setattr("wilab.network.nat.execute_iptables", iptables)
    nat = NatManager("eth0")
    nat.block_internet("wlan0", "a")
    with pytest.raises(RuntimeError, match="Cannot remove Internet block"):
        nat.unblock_internet("a")
    assert len(nat._blocked_rules["a"]) == 3
    assert calls[-1][:3] == ["-I", "FORWARD", "1"]


class TestNatManagerInit:
    """Tests for NAT manager initialization."""

    def test_nat_manager_init_auto(self):
        """Test NAT manager initialization with auto upstream."""
        nat = NatManager(upstream_interface="auto")
        assert nat.upstream_interface == "auto"
        assert nat._upstream_by_network == {}

    def test_nat_manager_init_specific(self):
        """Test NAT manager initialization with specific interface."""
        nat = NatManager(upstream_interface="eth0")
        assert nat.upstream_interface == "eth0"


class TestUpstreamDiscovery:
    """Tests for upstream interface discovery."""

    def test_discover_upstream_interface(self, monkeypatch):
        """Test discovering upstream interface from default route."""
        nat = NatManager(upstream_interface="auto")

        # Mock ip route output
        mock_output = "default via 192.168.1.1 dev eth0 proto dhcp metric 100"
        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            lambda cmd: mock_output
        )

        interface = nat._discover_upstream_interface()
        assert interface == "eth0"

    def test_discover_upstream_follows_the_default_route(self, monkeypatch):
        """STAB-6: the upstream is resolved on every use, not cached for the process life."""
        nat = NatManager(upstream_interface="auto")
        route = {"dev": "eth0"}
        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            lambda cmd: f"default via 192.0.2.1 dev {route['dev']} proto dhcp metric 100",
        )
        assert nat.get_upstream_interface() == "eth0"
        route["dev"] = "eth1"  # cable moved, VPN, failover
        assert nat.get_upstream_interface() == "eth1"

    def test_discover_upstream_no_default_route(self, monkeypatch):
        """Test error when no default route exists."""
        nat = NatManager(upstream_interface="auto")

        # Mock ip route with no default
        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            lambda cmd: "192.168.1.0/24 dev eth0 proto kernel scope link src 192.168.1.100"
        )

        with pytest.raises(RuntimeError, match="No default route"):
            nat._discover_upstream_interface()

    def test_discover_upstream_command_failure(self, monkeypatch):
        """Test error when ip route command fails."""
        nat = NatManager(upstream_interface="auto")

        def mock_fail(cmd):
            raise CommandError("ip route failed")

        monkeypatch.setattr("wilab.network.nat.execute_command", mock_fail)

        with pytest.raises(RuntimeError, match="Cannot determine upstream"):
            nat._discover_upstream_interface()


class TestGetUpstreamInterface:
    """Tests for getting upstream interface."""

    def test_get_upstream_auto(self, monkeypatch):
        """Test getting upstream with auto discovery."""
        nat = NatManager(upstream_interface="auto")

        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            lambda cmd: "default via 192.168.1.1 dev eth0"
        )

        interface = nat.get_upstream_interface()
        assert interface == "eth0"

    def test_get_upstream_specific(self):
        """Test getting upstream with specific interface."""
        nat = NatManager(upstream_interface="eth1")
        interface = nat.get_upstream_interface()
        assert interface == "eth1"


class TestIpForwarding:
    """Tests for IP forwarding control."""

    def test_enable_ip_forwarding(self, monkeypatch):
        """Test enabling IP forwarding."""
        nat = NatManager()

        called_with = []
        def mock_sysctl(key, value=None):
            called_with.append((key, value))
            return ""

        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)

        nat.enable_ip_forwarding()
        assert called_with == [("net.ipv4.ip_forward", "1")]

    def test_enable_ip_forwarding_failure(self, monkeypatch):
        """Test error when enabling IP forwarding fails."""
        nat = NatManager()

        def mock_fail(key, value=None):
            raise CommandError("sysctl failed")

        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_fail)

        with pytest.raises(RuntimeError, match="Cannot enable IP forwarding"):
            nat.enable_ip_forwarding()

    def test_disable_ip_forwarding(self, monkeypatch):
        """Test disabling IP forwarding."""
        nat = NatManager()

        called_with = []
        def mock_sysctl(key, value=None):
            called_with.append((key, value))
            return ""

        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)

        nat.disable_ip_forwarding()
        assert called_with == [("net.ipv4.ip_forward", "0")]


class TestEnableNat:
    """Tests for enabling NAT."""

    def test_enable_nat_success(self, monkeypatch):
        """Test enabling NAT with all rules."""
        nat = NatManager(upstream_interface="eth0")

        iptables_calls = []
        sysctl_calls = []

        monkeypatch.setattr("wilab.network.nat.execute_iptables", _recording_iptables(iptables_calls))
        def mock_sysctl(key, value=None):
            sysctl_calls.append((key, value))
            return ""
        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)

        nat.enable_nat("wlan0", "test-net", "192.168.120.0/24")

        # Check IP forwarding was enabled
        assert sysctl_calls == [("net.ipv4.ip_forward", "1")]

        # Check iptables rules (accept 3 or 4 if protection rule added)
        assert len(iptables_calls) >= 3

        # Verify MASQUERADE rule exists (may not be first if protection rule added)
        masquerade_rule = [
            "-t", "nat", "-A", "POSTROUTING",
            "-s", "192.168.120.0/24", "-o", "eth0", "-j", "MASQUERADE",
            "-m", "comment", "--comment", "wilab-nat-test-net"
        ]
        assert masquerade_rule in iptables_calls

        # Verify forward rules exist
        forward_in = [
            "-A", "FORWARD", "-i", "wlan0", "-o", "eth0", "-j", "ACCEPT",
            "-m", "comment", "--comment", "wilab-forward-test-net"
        ]
        forward_out = [
            "-A", "FORWARD", "-i", "eth0", "-o", "wlan0",
            "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT",
            "-m", "comment", "--comment", "wilab-forward-test-net"
        ]
        assert forward_in in iptables_calls
        assert forward_out in iptables_calls

    def test_enable_nat_auto_upstream(self, monkeypatch):
        """Test enabling NAT with auto upstream discovery."""
        nat = NatManager(upstream_interface="auto")

        iptables_calls = []

        # Mock upstream discovery - distinguish between ip route and iptables -C commands
        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            lambda cmd: "default via 10.0.0.1 dev eth1",
        )
        monkeypatch.setattr("wilab.network.nat.execute_iptables", _recording_iptables(iptables_calls))
        def mock_sysctl(key, value=None):
            return ""
        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)

        nat.enable_nat("wlan0", "test-net", "192.168.120.0/24")

        # Check that eth1 was used
        assert any("eth1" in str(call) for call in iptables_calls)

    def test_enable_nat_iptables_failure(self, monkeypatch):
        """Test error when iptables command fails."""
        nat = NatManager(upstream_interface="eth0")

        call_count = 0
        def mock_iptables(args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise CommandError("iptables failed")

        monkeypatch.setattr("wilab.network.nat.execute_iptables", mock_iptables)
        monkeypatch.setattr("wilab.network.nat.execute_sysctl", lambda args: None)

        with pytest.raises(RuntimeError, match="Cannot enable NAT"):
            nat.enable_nat("wlan0", "test-net", "192.168.120.0/24")


class TestDisableNat:
    """Tests for disabling NAT."""

    def test_disable_nat_success(self, monkeypatch):
        """Test disabling NAT removes all rules."""
        nat = NatManager(upstream_interface="eth0")

        iptables_calls = []

        def listing(args):
            if args[-1] == "POSTROUTING":
                return "-A POSTROUTING -s 192.168.120.0/24 -o eth0 -j MASQUERADE -m comment --comment wilab-nat-test-net"
            return "\n".join([
                "-A FORWARD -i wlan0 -o eth0 -j ACCEPT -m comment --comment wilab-forward-test-net",
                "-A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT -m comment --comment wilab-forward-test-net",
            ])
        monkeypatch.setattr("wilab.network.nat.execute_iptables", _recording_iptables(iptables_calls, listing))

        nat.disable_nat("wlan0", "test-net", "192.168.120.0/24")

        # The implementation may issue multiple deletes to remove duplicates;
        # assert that required rule deletions were attempted at least once.
        def contains(items, call):
            return all(item in call for item in items)

        # MASQUERADE delete on POSTROUTING for upstream eth0 with net_id comment
        assert any(
            call[:4] == ["-t", "nat", "-D", "POSTROUTING"]
            and contains(["-s", "192.168.120.0/24", "-o", "eth0", "MASQUERADE", "wilab-nat-test-net"], call)
            for call in iptables_calls
        )

        # FORWARD delete: wlan0 -> eth0 ACCEPT with net_id comment
        assert any(
            call[:2] == ["-D", "FORWARD"]
            and contains(["-i", "wlan0", "-o", "eth0", "ACCEPT", "wilab-forward-test-net"], call)
            for call in iptables_calls
        )

        # FORWARD delete: eth0 -> wlan0 RELATED,ESTABLISHED ACCEPT with net_id comment
        assert any(
            call[:2] == ["-D", "FORWARD"]
            and contains(["-i", "eth0", "-o", "wlan0", "--state", "RELATED,ESTABLISHED", "ACCEPT", "wilab-forward-test-net"], call)
            for call in iptables_calls
        )

    def test_disable_nat_nonexistent_rules(self, monkeypatch):
        """Test that disabling NAT doesn't fail if rules don't exist."""
        nat = NatManager(upstream_interface="eth0")

        def mock_iptables(args):
            if "-D" in args:
                raise CommandError("iptables: Bad rule (does a matching rule exist in that chain?)")
            return ""

        monkeypatch.setattr("wilab.network.nat.execute_iptables", mock_iptables)

        # Should not raise
        nat.disable_nat("wlan0", "test-net", "192.168.120.0/24")

    def test_cleanup_failure_retains_block_and_pending_state(self, monkeypatch):
        nat = NatManager("eth0")
        nat._nat_networks.add("test-net")
        monkeypatch.setattr("wilab.network.nat.execute_iptables", lambda args: None)
        nat.block_internet("wlan0", "test-net")

        def fail(args):
            if "-S" in args:
                raise CommandError("cannot list rules")
            return ""

        monkeypatch.setattr("wilab.network.nat.execute_iptables", fail)
        with pytest.raises(RuntimeError, match="Cannot remove NAT rules"):
            nat.release_network("wlan0", "test-net")
        assert nat.has_pending_network("test-net")
        assert len(nat._blocked_rules["test-net"]) == 3


class TestFlushRules:
    """Tests for flushing all rules."""

    def test_flush_all_rules(self, monkeypatch):
        """Test flushing all NAT and FORWARD rules."""
        nat = NatManager()

        iptables_calls = []
        monkeypatch.setattr(
            "wilab.network.nat.execute_iptables",
            lambda args: iptables_calls.append(args)
        )

        nat.flush_all_rules()

        assert len(iptables_calls) == 2
        assert iptables_calls[0] == ["-t", "nat", "-F"]
        assert iptables_calls[1] == ["-F", "FORWARD"]


# --------------------------------------------------------------------------- STAB-6


class _Firewall:
    """In-memory iptables for NatManager: -A/-I add, -D removes, -C checks, -S lists."""

    def __init__(self):
        self.rules: list[tuple[str, list[str]]] = []

    def __call__(self, args):
        table = "filter"
        if args[:1] == ["-t"]:
            table, args = args[1], args[2:]
        op = args[0]
        if op == "-S":
            chain = args[1] if len(args) > 1 else None
            return "\n".join(
                "-A " + " ".join(r) for t, r in self.rules if t == table and (chain is None or r[0] == chain)
            )
        rule = args[1:] if op != "-I" else [args[1], *args[3:]]
        if op == "-C":
            if (table, rule) not in self.rules:
                raise CommandError("Bad rule")
        elif op in ("-A", "-I"):
            self.rules.append((table, rule))
        elif op == "-D":
            self.rules.remove((table, rule))
        return ""


@pytest.fixture
def moving_route(monkeypatch):
    route = {"dev": "eth0"}
    fw = _Firewall()
    monkeypatch.setattr("wilab.network.nat.execute_iptables", fw)
    monkeypatch.setattr("wilab.network.nat.execute_sysctl", lambda key, value=None: "1")
    monkeypatch.setattr(
        "wilab.network.nat.execute_command", lambda cmd: f"default via 192.0.2.1 dev {route['dev']}",
    )
    return route, fw


def _masquerade_upstreams(fw):
    return [r[r.index("-o") + 1] for t, r in fw.rules if t == "nat"]


def test_new_network_after_a_route_change_uses_the_new_upstream(moving_route):
    route, fw = moving_route
    nat = NatManager("auto")
    nat.enable_nat("wlan0", "wlan0", "192.168.120.0/24")
    route["dev"] = "eth1"
    nat.enable_nat("wlan1", "wlan1", "192.168.121.0/24")
    assert _masquerade_upstreams(fw) == ["eth0", "eth1"]


def test_verify_moves_the_rules_of_a_running_network(moving_route):
    route, fw = moving_route
    nat = NatManager("auto")
    nat.enable_nat("wlan0", "wlan0", "192.168.120.0/24")
    route["dev"] = "eth1"
    repaired = nat.verify("wlan0", "wlan0", "192.168.120.0/24")
    assert repaired[0] == "NAT upstream eth0 -> eth1"
    assert _masquerade_upstreams(fw) == ["eth1"]  # the eth0 rules are gone
    forward = [r for t, r in fw.rules if t == "filter" and r[0] == "FORWARD"]
    assert all("eth0" not in r for r in forward) and len(forward) == 2
    assert nat.verify("wlan0", "wlan0", "192.168.120.0/24") == []


def test_release_forgets_the_upstream(moving_route):
    _route, fw = moving_route
    nat = NatManager("auto")
    nat.enable_nat("wlan0", "wlan0", "192.168.120.0/24")
    nat.release_network("wlan0", "wlan0")
    assert nat._upstream_by_network == {} and fw.rules == []
