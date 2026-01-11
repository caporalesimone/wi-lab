import logging
from typing import Optional
from ..network.commands import execute_command, execute_iw, CommandError

logger = logging.getLogger(__name__)


class InterfaceError(Exception):
    """Exception raised for interface validation failures."""
    pass


def validate_interface_exists(interface: str) -> bool:
    """
    Check if network interface exists.
    
    Args:
        interface: Interface name (e.g., "wlan0")
        
    Returns:
        True if interface exists
        
    Raises:
        InterfaceError: If interface does not exist
    """
    try:
        output = execute_command(["ip", "link", "show", interface])
        return interface in output
    except CommandError:
        raise InterfaceError(f"Interface {interface} does not exist")


def validate_interface_wireless(interface: str) -> bool:
    """
    Check if interface is wireless-capable.
    
    Args:
        interface: Interface name
        
    Returns:
        True if interface is wireless
        
    Raises:
        InterfaceError: If interface is not wireless
    """
    try:
        output = execute_iw([interface, "info"])
        return "wiphy" in output.lower() or "type" in output.lower()
    except CommandError:
        raise InterfaceError(f"Interface {interface} is not wireless-capable")


def validate_interface_ap_mode(interface: str) -> bool:
    """
    Check if interface supports AP mode.
    
    Args:
        interface: Interface name
        
    Returns:
        True if AP mode is supported
        
    Raises:
        InterfaceError: If AP mode not supported
    """
    try:
        # Get physical device (phy) for the interface
        info_output = execute_iw([interface, "info"])
        
        # Extract wiphy number
        wiphy = None
        for line in info_output.split('\n'):
            if 'wiphy' in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    wiphy = parts[1]
                    break
        
        if not wiphy:
            raise InterfaceError(f"Cannot determine wiphy for {interface}")
        
        # Check supported interface modes
        phy_output = execute_iw(["phy" + wiphy, "info"])
        
        if "AP" not in phy_output:
            raise InterfaceError(f"Interface {interface} does not support AP mode")
        
        return True
        
    except CommandError as e:
        raise InterfaceError(f"Cannot validate AP mode for {interface}: {e}")


def validate_interface(interface: str) -> None:
    """
    Comprehensive validation of WiFi interface for AP mode.
    
    Args:
        interface: Interface name
        
    Raises:
        InterfaceError: If any validation check fails
    """
    logger.info(f"Validating interface {interface}")
    
    validate_interface_exists(interface)
    logger.debug(f"Interface {interface} exists")
    
    validate_interface_wireless(interface)
    logger.debug(f"Interface {interface} is wireless-capable")
    
    validate_interface_ap_mode(interface)
    logger.info(f"Interface {interface} validated for AP mode")

