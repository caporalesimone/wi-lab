# pytest configuration and shared fixtures
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from wilab.config import load_config, AppConfig


@pytest.fixture(scope="session")
def config():
    """Load config once per test session."""
    return load_config()


@pytest.fixture
def clean_manager(config, monkeypatch):
    """Create a fresh NetworkManager with no active networks."""
    from wilab.wifi.manager import NetworkManager
    mgr = NetworkManager(config)
    
    # Mock DHCP to avoid system calls
    def mock_dhcp_start(*args, **kwargs):
        return {
            'gateway': '192.168.10.1',
            'dhcp_range': '192.168.10.10,192.168.10.250',
            'config_file': '/tmp/mock-dnsmasq.conf'
        }
    
    def mock_dhcp_stop(*args, **kwargs):
        pass
    
    monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
    monkeypatch.setattr(mgr.dhcp_server, 'stop', mock_dhcp_stop)
    
    return mgr
