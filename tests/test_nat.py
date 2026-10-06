"""Tests for NAT and Internet forwarding management."""

import pytest
from wilab.network.nat import NatManager
from wilab.network.commands import CommandError


class TestNatManagerInit:
    """Tests for NAT manager initialization."""
    
    def test_nat_manager_init_auto(self):
        """Test NAT manager initialization with auto upstream."""
        nat = NatManager(upstream_interface="auto")
        assert nat.upstream_interface == "auto"
        assert nat._resolved_upstream is None
    
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
        assert nat._resolved_upstream == "eth0"
    
    def test_discover_upstream_cached(self, monkeypatch):
        """Test that discovered upstream is cached."""
        nat = NatManager(upstream_interface="auto")
        nat._resolved_upstream = "eth0"
        
        # Should not call execute_command
        call_count = 0
        def mock_command(cmd):
            nonlocal call_count
            call_count += 1
            return "should not be called"
        
        monkeypatch.setattr("wilab.network.nat.execute_command", mock_command)
        
        interface = nat._discover_upstream_interface()
        assert interface == "eth0"
        assert call_count == 0
    
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
        
        monkeypatch.setattr(
            "wilab.network.nat.execute_iptables",
            lambda args: iptables_calls.append(args)
        )
        def mock_sysctl(key, value=None):
            sysctl_calls.append((key, value))
            return ""
        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)
        
        nat.enable_nat("wlan0", "test-net")
        
        # Check IP forwarding was enabled
        assert sysctl_calls == [("net.ipv4.ip_forward", "1")]
        
        # Check iptables rules (accept 3 or 4 if protection rule added)
        assert len(iptables_calls) >= 3
        
        # Verify MASQUERADE rule exists (may not be first if protection rule added)
        masquerade_rule = [
            "-t", "nat", "-A", "POSTROUTING",
            "-o", "eth0", "-j", "MASQUERADE",
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
        def mock_execute_command(cmd):
            if isinstance(cmd, list) and len(cmd) > 1:
                if cmd[1] == "route" or "route" in cmd:
                    return "default via 10.0.0.1 dev eth1"
                elif "-C" in cmd:
                    # Rule check always returns "not found" (exception)
                    raise Exception("Rule not found")
            return "default via 10.0.0.1 dev eth1"
        
        monkeypatch.setattr(
            "wilab.network.nat.execute_command",
            mock_execute_command
        )
        monkeypatch.setattr(
            "wilab.network.nat.execute_iptables",
            lambda args: iptables_calls.append(args)
        )
        def mock_sysctl(key, value=None):
            return ""
        monkeypatch.setattr("wilab.network.nat.execute_sysctl", mock_sysctl)
        
        nat.enable_nat("wlan0", "test-net")
        
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
            nat.enable_nat("wlan0", "test-net")


class TestDisableNat:
    """Tests for disabling NAT."""
    
    def test_disable_nat_success(self, monkeypatch):
        """Test disabling NAT removes all rules."""
        nat = NatManager(upstream_interface="eth0")
        
        iptables_calls = []
        monkeypatch.setattr(
            "wilab.network.nat.execute_iptables",
            lambda args: iptables_calls.append(args)
        )
        
        nat.disable_nat("wlan0", "test-net")
        
        # The implementation may issue multiple deletes to remove duplicates;
        # assert that required rule deletions were attempted at least once.
        def contains(items, call):
            return all(item in call for item in items)

        # MASQUERADE delete on POSTROUTING for upstream eth0 with net_id comment
        assert any(
            call[:4] == ["-t", "nat", "-D", "POSTROUTING"]
            and contains(["-o", "eth0", "MASQUERADE", "wilab-nat-test-net"], call)
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
    
    def test_release_network_nonexistent_rules(self, monkeypatch):
        """Test that removing a network's rules doesn't fail if they don't exist."""
        nat = NatManager(upstream_interface="eth0")

        def mock_iptables(args):
            raise CommandError("iptables: Bad rule (does a matching rule exist in that chain?)")

        monkeypatch.setattr("wilab.network.nat.execute_iptables", mock_iptables)

        # Should not raise
        nat.release_network("wlan0", "test-net")

    def test_disable_nat_fails_if_the_block_cannot_be_applied(self, monkeypatch):
        """Internet must not be reported as disabled when the block rules are missing."""
        nat = NatManager(upstream_interface="eth0")

        def mock_iptables(args):
            raise CommandError("iptables failed")

        monkeypatch.setattr("wilab.network.nat.execute_iptables", mock_iptables)

        with pytest.raises(RuntimeError, match="Cannot block Internet"):
            nat.disable_nat("wlan0", "test-net")


class FakeIptables:
    """In-memory iptables: enough of -A/-I/-D/-C/-S to check rule order and ownership."""

    def __init__(self, forward_policy: str = "DROP"):
        self.forward_policy = forward_policy
        self.chains: dict = {}

    def iptables(self, args):
        args = list(args)
        table = "filter"
        if args[0] == "-t":
            table, args = args[1], args[2:]
        op, chain, rest = args[0], args[1], args[2:]
        rules = self.chains.setdefault((table, chain), [])
        if op == "-A":
            rules.append(tuple(rest))
        elif op == "-I":
            rules.insert(int(rest[0]) - 1, tuple(rest[1:]))
        elif op in ("-D", "-C"):
            if tuple(rest) not in rules:
                raise CommandError("Bad rule (does a matching rule exist in that chain?)")
            if op == "-D":
                rules.remove(tuple(rest))
        return ""

    def command(self, cmd, **kwargs):
        if cmd[:2] == ["ip", "route"]:
            return ""  # no default route
        if cmd[1:] == ["-S", "FORWARD"]:
            return f"-P FORWARD {self.forward_policy}\n"
        return self.iptables(cmd[1:])

    def rules(self, table: str = "filter", chain: str = "FORWARD") -> list:
        return self.chains.get((table, chain), [])

    def comments(self, table: str = "filter", chain: str = "FORWARD") -> list:
        return [rule[rule.index("--comment") + 1] for rule in self.rules(table, chain)]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeIptables()
    monkeypatch.setattr("wilab.network.nat.execute_iptables", fake.iptables)
    monkeypatch.setattr("wilab.network.nat.execute_command", fake.command)
    monkeypatch.setattr("wilab.network.nat.execute_sysctl", lambda key, value=None: "")
    return fake


BLOCK_A = ["wilab-block-net-a"] * 3


class TestDisableInternetCutsOpenConnections:
    """Disabling Internet must stop established connections, on that network only."""

    def test_block_rules_come_before_every_accept_for_established_traffic(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")
        nat.enable_nat("wlan1", "net-b")

        nat.disable_nat("wlan0", "net-a")

        forward = fake.rules()
        assert fake.comments()[:4] == [*BLOCK_A, "wilab-protect-existing"]
        assert forward[0][:7] == ("-i", "wlan0", "-p", "tcp", "-j", "REJECT", "--reject-with")
        assert "tcp-reset" in forward[0]
        assert forward[1][:4] == ("-i", "wlan0", "-j", "REJECT")
        assert forward[2][:4] == ("-o", "wlan0", "-j", "DROP")

    def test_other_networks_keep_their_access(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")
        nat.enable_nat("wlan1", "net-b")

        nat.disable_nat("wlan0", "net-a")

        assert fake.comments() == [
            *BLOCK_A, "wilab-protect-existing", "wilab-forward-net-b", "wilab-forward-net-b"
        ]
        assert fake.comments("nat", "POSTROUTING") == ["wilab-nat-net-b"]
        assert not any("wlan1" in rule for rule in fake.rules()[:3])

    def test_the_shared_protect_rule_goes_with_the_last_network(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")
        nat.enable_nat("wlan1", "net-b")

        nat.disable_nat("wlan0", "net-a")
        nat.disable_nat("wlan1", "net-b")

        assert "wilab-protect-existing" not in fake.comments()
        assert fake.comments() == ["wilab-block-net-b"] * 3 + BLOCK_A
        assert fake.comments("nat", "POSTROUTING") == []

    def test_enabling_again_lifts_the_block(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")
        nat.disable_nat("wlan0", "net-a")

        nat.enable_nat("wlan0", "net-a")

        assert fake.comments() == ["wilab-protect-existing", "wilab-forward-net-a", "wilab-forward-net-a"]
        assert fake.comments("nat", "POSTROUTING") == ["wilab-nat-net-a"]

    def test_disabling_twice_does_not_duplicate_the_block(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")

        nat.disable_nat("wlan0", "net-a")
        nat.disable_nat("wlan0", "net-a")

        assert fake.comments() == BLOCK_A

    def test_the_block_does_not_need_an_upstream_interface(self, fake):
        """A network created without Internet is blocked even when there is no default route."""
        nat = NatManager(upstream_interface="auto")

        nat.disable_nat("wlan0", "net-a")

        assert fake.comments() == BLOCK_A

    def test_with_an_accept_policy_the_block_is_applied_too(self, fake):
        fake.forward_policy = "ACCEPT"
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")

        nat.disable_nat("wlan0", "net-a")

        assert fake.comments() == BLOCK_A

    def test_stopping_a_network_removes_its_block_and_nothing_else(self, fake):
        nat = NatManager(upstream_interface="eth0")
        nat.enable_nat("wlan0", "net-a")
        nat.enable_nat("wlan1", "net-b")
        nat.disable_nat("wlan0", "net-a")

        nat.release_network("wlan0", "net-a")

        assert fake.comments() == ["wilab-protect-existing", "wilab-forward-net-b", "wilab-forward-net-b"]
        assert fake.comments("nat", "POSTROUTING") == ["wilab-nat-net-b"]


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
