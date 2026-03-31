import os
import pytest
from wilab.config import load_config, AppConfig, NetworkEntry


class TestConfigLoading:
    """Tests for configuration file loading and validation."""
    
    def test_load_config_example(self):
        """Test loading the config.example.yaml file."""
        path = os.path.join(os.getcwd(), 'config.example.yaml')
        cfg = load_config(path)
        assert isinstance(cfg, AppConfig)
        assert cfg.api_port == 8080
        assert cfg.networks[0].device_id == 'wlxbc071dc527d6'
        assert cfg.networks[0].interface == 'wlxbc071dc527d6'
    
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
            interface='wlan0',
            display_name='test-device'
        )
        assert entry.interface == 'wlan0'
        assert entry.device_id == 'wlan0'
        assert entry.display_name == 'test-device'
    
    def test_network_entry_with_display_name(self):
        """Test creating a NetworkEntry with display_name."""
        entry = NetworkEntry(
            interface='wlan0',
            display_name='bench-antenna-1'
        )
        assert entry.device_id == 'wlan0'
        assert entry.display_name == 'bench-antenna-1'
    
    def test_network_entry_missing_display_name(self):
        """Test that missing display_name raises validation error."""
        with pytest.raises(ValueError):
            NetworkEntry(interface='wlan0')
    
    def test_device_id_equals_interface(self):
        """Test that device_id is always equal to interface name."""
        entry = NetworkEntry(interface='wlx782051245264', display_name='antenna')
        assert entry.device_id == 'wlx782051245264'
    
    def test_config_without_net_id_is_valid(self):
        """Test that configuration without net_id is valid (new format)."""
        entry = NetworkEntry(interface='wlan0', display_name='test')
        assert entry.interface == 'wlan0'
    
    def test_each_interface_has_unique_device_id(self):
        """Test that each configured interface has unique device_id."""
        cfg = load_config()
        device_ids = [n.device_id for n in cfg.networks]
        assert len(device_ids) == len(set(device_ids))


class TestConfigIntegration:
    """Integration tests for config with NetworkManager."""
    
    def test_dhcp_base_network_valid_cidr(self):
        """Test that dhcp_base_network is valid CIDR."""
        cfg = load_config()
        assert '/' in cfg.dhcp_base_network
        from ipaddress import IPv4Network
        IPv4Network(cfg.dhcp_base_network, strict=False)  # Should not raise

