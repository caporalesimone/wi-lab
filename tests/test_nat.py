"""Tests for NAT and Internet forwarding management."""

import pytest
from unittest.mock import Mock, patch
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
    
    def test_disable_nat_nonexistent_rules(self, monkeypatch):
        """Test that disabling NAT doesn't fail if rules don't exist."""
        nat = NatManager(upstream_interface="eth0")
        
        def mock_iptables(args):
            raise CommandError("iptables: Bad rule (does a matching rule exist in that chain?)")
        
        monkeypatch.setattr("wilab.network.nat.execute_iptables", mock_iptables)
        
        # Should not raise
        nat.disable_nat("wlan0", "test-net")


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
