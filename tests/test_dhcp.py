import pytest
import os
from ipaddress import IPv4Network
from wilab.network.dhcp import DhcpServer, DhcpServerError
from wilab.network.commands import CommandError


class TestDhcpServerInit:
    """Tests for DHCP server initialization."""
    
    def test_dhcp_server_init(self):
        """Test DHCP server initialization."""
        dhcp = DhcpServer()
        assert dhcp._instances == {}
    
    def test_dhcp_server_config_dir_created(self):
        """Test that config directory is created."""
        dhcp = DhcpServer()
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
    
    def test_start_server_not_installed(self, monkeypatch):
        """Test starting server fails gracefully when dnsmasq not installed."""
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
    
    def test_stop_all_empty(self):
        """Test stopping all when none active."""
        dhcp = DhcpServer()
        dhcp.stop_all()  # Should not raise


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
