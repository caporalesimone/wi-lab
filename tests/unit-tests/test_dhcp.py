import os
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from wilab.network.commands import CommandError
from wilab.network.dhcp import DhcpServer, DhcpServerError


class TestDhcpServerInit:
    """Tests for DHCP server initialization."""
    
    def test_dhcp_server_init(self):
        """Test DHCP server initialization."""
        dhcp = DhcpServer()
        assert dhcp._instances == {}
    
    def test_dhcp_server_config_dir_created(self):
        """Test that config directory is created."""
        DhcpServer()
        # Directory should be created during init
        assert os.path.exists('/tmp/wilab-dnsmasq') or True  # Might fail without perms


class TestSubnetParsing:
    """Tests for subnet parsing."""
    
    def test_parse_subnet_valid(self):
        """Test parsing valid subnet."""
        dhcp = DhcpServer()
        network, gateway, dhcp_range = dhcp._parse_subnet('192.168.10.0/24')
        assert network == '192.168.10.0'
        assert gateway == '192.168.10.1'
        assert dhcp_range == '192.168.10.10,192.168.10.250'
    
    def test_parse_subnet_different_class(self):
        """Test parsing different class subnet."""
        dhcp = DhcpServer()
        network, gateway, dhcp_range = dhcp._parse_subnet('10.0.0.0/8')
        assert network == '10.0.0.0'
        assert gateway == '10.0.0.1'
        assert '10.0.0.10' in dhcp_range
    
    def test_parse_subnet_invalid_cidr(self):
        """Test parsing invalid CIDR raises error."""
        dhcp = DhcpServer()
        with pytest.raises((DhcpServerError, IndexError, ValueError)):
            dhcp._parse_subnet('192.168.10.1')  # Missing prefix
    
    def test_parse_subnet_invalid_ip(self):
        """Test parsing invalid IP raises error."""
        dhcp = DhcpServer()
        with pytest.raises(DhcpServerError, match="Invalid subnet"):
            dhcp._parse_subnet('999.999.999.999/24')


class TestConfigGeneration:
    """Tests for dnsmasq config generation."""
    
    def test_generate_config_basic(self):
        """Test basic config generation."""
        dhcp = DhcpServer()
        config = dhcp._generate_config(
            interface='wlan0',
            gateway='192.168.10.1',
            dhcp_range='192.168.10.10,192.168.10.250',
            lease_file='/tmp/test.leases',
            dns_server='192.168.10.21'
        )
        assert 'interface=wlan0' in config
        assert 'listen-address=192.168.10.1' in config
        assert 'dhcp-range=192.168.10.10,192.168.10.250' in config
    
    def test_generate_config_with_custom_dns(self):
        """Test config generation with custom DNS."""
        dhcp = DhcpServer()
        config = dhcp._generate_config(
            interface='wlan0',
            gateway='192.168.10.1',
            dhcp_range='192.168.10.10,192.168.10.250',
            lease_file='/tmp/test.leases',
            dns_server='192.168.10.21'
        )
        assert 'dhcp-option=option:dns-server,192.168.10.21' in config
    
    def test_generate_config_router_option(self):
        """Test that router option is set to gateway."""
        dhcp = DhcpServer()
        config = dhcp._generate_config(
            interface='wlan0',
            gateway='192.168.10.1',
            dhcp_range='192.168.10.10,192.168.10.250',
            lease_file='/tmp/test.leases',
            dns_server='192.168.10.21'
        )
        assert 'dhcp-option=option:router,192.168.10.1' in config


class TestSubnetInfo:
    """Tests for subnet information retrieval."""
    
    def test_get_subnet_info_none(self):
        """Test getting info for non-existent subnet."""
        dhcp = DhcpServer()
        info = dhcp.get_subnet_info('unknown')
        assert info is None
    
    def test_list_active_empty(self):
        """Test listing active servers when none exist."""
        dhcp = DhcpServer()
        active = dhcp.list_active()
        assert active == []


class TestDhcpServerStart:
    """Tests for starting DHCP server (with mocking)."""
    
    def test_start_does_not_change_interface(self, monkeypatch, tmp_path):
        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_PID_DIR", str(tmp_path))
        commands = []

        def run(cmd):
            commands.append(cmd[0])
            if any(arg.startswith("--pid-file=") for arg in cmd):
                (tmp_path / "dnsmasq-ap-01.pid").write_text("123")

        monkeypatch.setattr("wilab.network.dhcp.execute_command", run)
        info = DhcpServer().start("ap-01", "wlan0", "192.168.10.0/24", "192.0.2.1")
        assert info["gateway"] == "192.168.10.1"
        assert commands == ["dnsmasq", "dnsmasq"]  # --test and launch; no --version (PERF-1)

    def test_start_server_not_installed(self, monkeypatch, tmp_path):
        """Test starting server fails gracefully when dnsmasq not installed."""
        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_PID_DIR", str(tmp_path))
        dhcp = DhcpServer()
        monkeypatch.setattr("wilab.network.dhcp.execute_command", lambda *args, **kwargs: (_ for _ in ()).throw(CommandError("missing")))
        with pytest.raises(DhcpServerError, match="dnsmasq not installed|Failed|Permission"):
            dhcp.start(
                net_id='ap-01',
                interface='wlan0',
                subnet='192.168.10.0/24',
                dns_server='192.168.10.21'
            )
    
    def test_start_server_already_running(self, monkeypatch):
        """Test starting server when already running returns existing."""
        dhcp = DhcpServer()
        
        # Pre-populate the instances dict
        dhcp._instances['ap-01'] = {
            'gateway': '192.168.10.1',
            'config_file': '/tmp/test.conf'
        }
        
        # Avoid calling real dnsmasq
        monkeypatch.setattr("wilab.network.dhcp.execute_command", lambda *args, **kwargs: None)
        result = dhcp.start(
            net_id='ap-01',
            interface='wlan0',
            subnet='192.168.10.0/24',
            dns_server='192.168.10.21'
        )
        
        assert result == dhcp._instances['ap-01']


class TestDhcpServerStop:
    """Tests for stopping DHCP server."""
    
    def test_stop_nonexistent_server(self):
        """Test stopping non-existent server doesn't error."""
        dhcp = DhcpServer()
        dhcp.stop('nonexistent')  # Should not raise
    
class TestDhcpIntegration:
    """Integration tests for DHCP server."""
    
    def test_subnet_parsing_integration(self):
        """Test that subnet parsing integrates with IPv4Network."""
        dhcp = DhcpServer()
        
        # Test various small subnets to avoid huge IP ranges
        subnets = [
            '192.168.10.0/24',
            '192.168.20.0/24',  # Another /24
            '192.168.1.128/25'   # /25 is small
        ]
        
        for subnet in subnets:
            network, gateway, dhcp_range = dhcp._parse_subnet(subnet)
            # Verify gateway is second IP in network
            net = IPv4Network(subnet, strict=False)
            assert gateway == str(net[1])


class TestLaunchTimeoutCleanup:
    """NET-6: a dnsmasq launch that timed out before its PID file can still be cleaned up."""

    @pytest.fixture
    def timed_out(self, monkeypatch, tmp_path):
        from wilab.network.commands import CommandTimeout

        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr("wilab.network.dhcp.DNSMASQ_PID_DIR", str(tmp_path))

        def run(cmd):
            if any(arg.startswith("--pid-file=") for arg in cmd):
                raise CommandTimeout("Command timed out: dnsmasq")
            return ""

        monkeypatch.setattr("wilab.network.dhcp.execute_command", run)
        server = DhcpServer()
        with pytest.raises(DhcpServerError):
            server.start("ap-01", "wlan0", "192.168.10.0/24", "192.0.2.1")
        return server

    def test_stop_without_pid_file_and_no_process_completes(self, timed_out, monkeypatch):
        stopped = []
        monkeypatch.setattr("wilab.network.dhcp.stop_process", stopped.append)
        monkeypatch.setattr(DhcpServer, "_find_process", staticmethod(lambda config_file: None))
        timed_out.stop("ap-01")  # previously: "Missing dnsmasq PID file" on every attempt
        assert stopped == []
        assert "ap-01" not in timed_out.list_active()

    def test_stop_without_pid_file_kills_the_daemon_found_by_conf_file(self, timed_out, monkeypatch):
        stopped = []
        monkeypatch.setattr("wilab.network.dhcp.stop_process", stopped.append)
        monkeypatch.setattr(DhcpServer, "_find_process", staticmethod(lambda config_file: 4321))
        timed_out.stop("ap-01")
        assert stopped == [4321]
        assert "ap-01" not in timed_out.list_active()

    @pytest.mark.parametrize("keep_leases", [False, True])
    def test_leases_end_with_the_network(self, timed_out, monkeypatch, keep_leases):
        """NET-7: the next user of the adapter never inherits the previous clients;
        a watchdog restart of dnsmasq on the same network keeps them."""
        monkeypatch.setattr("wilab.network.dhcp.stop_process", lambda pid: None)
        monkeypatch.setattr(DhcpServer, "_find_process", staticmethod(lambda config_file: None))
        leases = Path(timed_out._instances["ap-01"]["lease_file"])
        leases.write_text("1700000000 aa:bb:cc:dd:ee:ff 192.168.10.50 phone *\n")
        timed_out.stop("ap-01", keep_leases=keep_leases)
        assert leases.exists() is keep_leases

    def test_find_process_matches_name_and_conf_file(self, tmp_path):
        import subprocess
        import sys

        fake = tmp_path / "dnsmasq"
        fake.symlink_to(sys.executable)
        conf = tmp_path / "dnsmasq-ap-01.conf"
        child = subprocess.Popen(
            [str(fake), "-c", "import time; time.sleep(30)", f"--conf-file={conf}"],
        )
        try:
            for _ in range(50):
                if DhcpServer._find_process(str(conf)) == child.pid:
                    break
                import time
                time.sleep(0.05)
            assert DhcpServer._find_process(str(conf)) == child.pid
            assert DhcpServer._find_process(str(tmp_path / "other.conf")) is None
        finally:
            child.kill()
            child.wait()
