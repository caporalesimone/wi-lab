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


@pytest.fixture(autouse=True)
def mock_network_operations(monkeypatch):
    """Auto-mock network operations that require root privileges."""
    from wilab.network import commands
    from wilab.wifi import interface
    from wilab.wifi import manager
    
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
            return f"inet 192.168.120.1/24\nstate UP"
        return ""
    
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
            # Return phy capabilities with proper channel info
            return """Band 2.4 GHz
* 2412 MHz [1] (20.0 dBm)
* 2437 MHz [6] (20.0 dBm)  
* 2462 MHz [11] (20.0 dBm)"""
        
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
