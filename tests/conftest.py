# pytest configuration and shared fixtures
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from wilab.config import load_config


@pytest.fixture(scope="session")
def config():
    """Load config once per test session."""
    return load_config()


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
    
    # Realistic iw phy output with 2.4 GHz, 5 GHz, and disabled channels
    _MOCK_PHY_INFO = """\
Band 1:
\t\tFrequencies:
\t\t\t* 2412.0 MHz [1] (20.0 dBm)
\t\t\t* 2417.0 MHz [2] (20.0 dBm)
\t\t\t* 2422.0 MHz [3] (20.0 dBm)
\t\t\t* 2427.0 MHz [4] (20.0 dBm)
\t\t\t* 2432.0 MHz [5] (20.0 dBm)
\t\t\t* 2437.0 MHz [6] (20.0 dBm)
\t\t\t* 2442.0 MHz [7] (20.0 dBm)
\t\t\t* 2447.0 MHz [8] (20.0 dBm)
\t\t\t* 2452.0 MHz [9] (20.0 dBm)
\t\t\t* 2457.0 MHz [10] (20.0 dBm)
\t\t\t* 2462.0 MHz [11] (20.0 dBm)
\t\t\t* 2467.0 MHz [12] (20.0 dBm)
\t\t\t* 2472.0 MHz [13] (20.0 dBm)
\t\t\t* 2484.0 MHz [14] (disabled)
Band 2:
\t\tFrequencies:
\t\t\t* 5180.0 MHz [36] (23.0 dBm)
\t\t\t* 5200.0 MHz [40] (23.0 dBm)
\t\t\t* 5220.0 MHz [44] (23.0 dBm)
\t\t\t* 5240.0 MHz [48] (23.0 dBm)
\t\t\t* 5260.0 MHz [52] (20.0 dBm) (radar detection)
\t\t\t* 5280.0 MHz [56] (20.0 dBm) (radar detection)
\t\t\t* 5300.0 MHz [60] (20.0 dBm) (radar detection)
\t\t\t* 5320.0 MHz [64] (20.0 dBm) (radar detection)
\t\t\t* 5500.0 MHz [100] (26.0 dBm) (radar detection)
\t\t\t* 5745.0 MHz [149] (13.0 dBm)
\t\t\t* 5765.0 MHz [153] (13.0 dBm)
\t\t\t* 5785.0 MHz [157] (13.0 dBm)
\t\t\t* 5805.0 MHz [161] (13.0 dBm)
\t\t\t* 5825.0 MHz [165] (13.0 dBm)
\t\t\t* 5845.0 MHz [169] (disabled)
"""

    # Mock execute_iw to avoid needing real WiFi hardware
    def mock_execute_iw(args):
        # Return mock wiphy info
        if not args:
            return ""
        
        # Handle: execute_iw([interface, "info"])
        if len(args) >= 2 and args[1] == "info" and not args[0].startswith("phy"):
            # Return wiphy info for interface
            return f"Interface {args[0]}\nwiphy 0\ntxpower 20.00 dBm"
        
        # Handle: execute_iw(["phy0", "info"])
        elif args[0].startswith("phy"):
            return _MOCK_PHY_INFO
        
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
    monkeypatch.setattr(manager, "validate_interface_ap_mode", mock_validate_interface_ap_mode)
    monkeypatch.setattr(manager, "execute_iw", mock_execute_iw)
    
    # Patch commands
    monkeypatch.setattr(commands, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(commands, "execute_iw", mock_execute_iw)
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
