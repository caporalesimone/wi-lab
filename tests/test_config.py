import os
import tempfile
import pytest
from wilab.config import load_config, AppConfig, NetworkEntry, NET_ID_REGEX


class TestConfigLoading:
    """Tests for configuration file loading and validation."""
    
    def test_load_config_example(self):
        """Test loading the default config.yaml file."""
        path = os.path.join(os.getcwd(), 'config.yaml')
        cfg = load_config(path)
        assert isinstance(cfg, AppConfig)
        assert cfg.api_port == 8080
        assert cfg.networks[0].net_id == 'ap-01'
        assert cfg.networks[0].interface == 'wlx782051245264'
    
    def test_load_config_default_path(self):
        """Test loading config from default location."""
        cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.auth_token == "secret-token-12345"
    
    def test_config_has_required_fields(self):
        """Test that loaded config has all required fields."""
        cfg = load_config()
        assert hasattr(cfg, 'auth_token')
        assert hasattr(cfg, 'api_port')
        assert hasattr(cfg, 'default_timeout')
        assert hasattr(cfg, 'dhcp_base_network')
        assert hasattr(cfg, 'upstream_interface')
        assert hasattr(cfg, 'dns_server')
        assert hasattr(cfg, 'networks')
    
    def test_config_defaults(self):
        """Test that config has correct default values."""
        cfg = load_config()
        assert cfg.api_port == 8080
        assert cfg.default_timeout == 3600
        assert cfg.internet_enabled_by_default is True
        assert cfg.min_timeout == 60
        assert cfg.max_timeout == 86400  # 24 hours
    
    def test_config_file_not_found(self):
        """Test that SystemExit is raised for missing config file."""
        with pytest.raises(SystemExit) as exc_info:
            load_config('/nonexistent/path/config.yaml')
        assert "Configuration file not found" in str(exc_info.value)


class TestNetworkEntryValidation:
    """Tests for NetworkEntry validation."""
    
    def test_valid_network_entry(self):
        """Test creating a valid NetworkEntry."""
        entry = NetworkEntry(
            net_id='ap-01',
            interface='wlan0'
        )
        assert entry.net_id == 'ap-01'
        assert entry.interface == 'wlan0'
    
    def test_invalid_net_id_uppercase(self):
        """Test that uppercase net_id is rejected."""
        with pytest.raises(ValueError, match="must match"):
            NetworkEntry(
                net_id='AP-01',
                interface='wlan0'
            )
    
    def test_invalid_net_id_special_chars(self):
        """Test that special characters in net_id are rejected."""
        with pytest.raises(ValueError, match="must match"):
            NetworkEntry(
                net_id='ap_01',
                interface='wlan0'
            )
    
    def test_invalid_net_id_too_long(self):
        """Test that net_id longer than 16 chars is rejected."""
        with pytest.raises(ValueError, match="must match"):
            NetworkEntry(
                net_id='a' * 17,
                interface='wlan0'
            )
    
    def test_valid_net_id_regex(self):
        """Test valid net_id patterns."""
        valid_ids = ['ap-01', 'ap-1', 'a', '1', 'test-network-123']
        for net_id in valid_ids:
            assert NET_ID_REGEX.match(net_id)


class TestConfigIntegration:
    """Integration tests for config with NetworkManager."""
    
    def test_dhcp_base_network_valid_cidr(self):
        """Test that dhcp_base_network is valid CIDR."""
        cfg = load_config()
        assert '/' in cfg.dhcp_base_network
        from ipaddress import IPv4Network
        IPv4Network(cfg.dhcp_base_network, strict=False)  # Should not raise

