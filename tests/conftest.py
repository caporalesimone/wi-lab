# pytest configuration and shared fixtures
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from wilab.config import load_config

TEST_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'test.config.yaml')


@pytest.fixture(scope="session")
def config():
    """Load test config once per test session."""
    return load_config(TEST_CONFIG_PATH)


@pytest.fixture(autouse=True)
def _test_config_env(monkeypatch):
    """Point load_config() to the test config and reset cached dependency singletons."""
    from wilab.api import dependencies
    monkeypatch.setenv('CONFIG_PATH', TEST_CONFIG_PATH)
    monkeypatch.setattr(dependencies, '_config', None)
    monkeypatch.setattr(dependencies, '_manager', None)
    monkeypatch.setattr(dependencies, '_reservation_manager', None)
    monkeypatch.setattr(dependencies, '_channel_manager', None)
    monkeypatch.setattr(dependencies, '_qos_manager', None)


@pytest.fixture(autouse=True)
def mock_network_operations(monkeypatch):
    """Auto-mock network operations that require root privileges."""
    from wilab.network import commands
    from wilab.wifi import interface
    from wilab.wifi import manager
    from wilab.wifi import channels
    
    # Mock WiFi interface validation (requires real hardware)
    def mock_validate_interface(iface):
        # Just return without validation
        return
    
    def mock_validate_interface_ap_mode(iface):
        # Just return without validation
        return
    
    # Mock execute_ip to avoid RTNETLINK errors (requires root)
    def mock_execute_ip(args):
        # Return empty string for most commands, simulate success
        cmd = args[0] if args else ""
        if cmd == "addr" and "show" in args:
            # Simulate interface exists
            return "inet 192.168.120.1/24\nstate UP"
        return ""
    
    # Realistic iw phy channels output with 2.4 GHz, 5 GHz, No IR, and disabled channels
    _MOCK_PHY_CHANNELS = """\
Band 1:
        * 2412 MHz [1] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2417 MHz [2] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2422 MHz [3] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2427 MHz [4] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2432 MHz [5] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2437 MHz [6] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2442 MHz [7] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2447 MHz [8] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2452 MHz [9] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2457 MHz [10] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2462 MHz [11] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2467 MHz [12] 
          Maximum TX power: 20.0 dBm
          No IR
          Channel widths: 20MHz HT40-
        * 2472 MHz [13] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2484 MHz [14] (disabled)
Band 2:
        * 5180 MHz [36] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5200 MHz [40] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5220 MHz [44] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5240 MHz [48] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5260 MHz [52] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5280 MHz [56] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5300 MHz [60] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5320 MHz [64] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5500 MHz [100] 
          Maximum TX power: 26.0 dBm
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5745 MHz [149] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5765 MHz [153] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5785 MHz [157] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5805 MHz [161] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5825 MHz [165] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5845 MHz [169] (disabled)
"""

    # Mock execute_iw to avoid needing real WiFi hardware
    def mock_execute_iw(args):
        # Return mock wiphy info
        if not args:
            return ""
        
        # Handle: execute_iw(["reg", "set", ...])
        if args[0] == "reg":
            return ""

        # Handle: execute_iw([interface, "info"])
        if len(args) >= 2 and args[1] == "info" and not args[0].startswith("phy"):
            # Return wiphy info for interface
            return f"Interface {args[0]}\nwiphy 0\ntxpower 20.00 dBm"
        
        # Handle: execute_iw(["phy0", "channels"])
        elif args[0].startswith("phy"):
            return _MOCK_PHY_CHANNELS
        
        # Handle: execute_iw(["dev", interface, "station", "dump"])
        elif "station" in args:
            return ""
        
        return ""
    
    # Mock execute_command for network operations
    def mock_execute_command(cmd, **kwargs):
        if cmd[0] == "ip":
            return mock_execute_ip(cmd[1:])
        # For other commands, return empty string
        return ""
    
    # Patch in interface module
    monkeypatch.setattr(interface, "validate_interface", mock_validate_interface)
    monkeypatch.setattr(interface, "validate_interface_ap_mode", mock_validate_interface_ap_mode)
    
    # Patch in manager module (where they're imported)
    monkeypatch.setattr(manager, "validate_interface_exists", lambda iface: None)
    monkeypatch.setattr(manager, "validate_interface_wireless", lambda iface: None)
    monkeypatch.setattr(manager, "validate_interface_ap_mode", mock_validate_interface_ap_mode)
    monkeypatch.setattr(manager, "execute_iw", mock_execute_iw)
    
    # Patch commands
    monkeypatch.setattr(commands, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(commands, "execute_iw", mock_execute_iw)
    monkeypatch.setattr(commands, "execute_tc", lambda args: "")
    monkeypatch.setattr(commands, "execute_command", mock_execute_command)

    # Patch in channels module
    monkeypatch.setattr(channels, "execute_iw", mock_execute_iw)


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
