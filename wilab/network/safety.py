"""What Wi-Lab changes on the host: its firewall rules, and the startup notice."""

import logging

from .commands import execute_iptables

logger = logging.getLogger(__name__)


def list_wilab_rules() -> dict:
    """
    List all active Wi-Lab iptables rules.
    
    Returns:
        Dictionary with 'nat' and 'forward' lists of rules
    """
    rules: dict[str, list[str]] = {"nat": [], "forward": []}
    
    try:
        # Check NAT table
        nat_output = execute_iptables(["-t", "nat", "-L", "POSTROUTING", "-n", "-v"])
        for line in nat_output.split('\n'):
            if 'wilab-nat' in line:
                rules["nat"].append(line.strip())
        
        # Check FORWARD chain
        forward_output = execute_iptables(["-L", "FORWARD", "-n", "-v"])
        for line in forward_output.split('\n'):
            if 'wilab-' in line:
                rules["forward"].append(line.strip())
    
    except Exception as e:
        logger.warning(f"Could not list iptables rules: {e}")
    
    return rules


def log_host_impact_warning() -> None:
    """Say once at startup what Wi-Lab changes on the host (ARCH-9)."""
    logger.info(
        "Wi-Lab changes the host network: IP forwarding, iptables NAT, FORWARD and INPUT rules "
        "(all tagged 'wilab-'), and the Wi-Fi adapters it manages",
    )
