"""Safety utilities for checking host network impact."""

import logging
from .commands import execute_command, execute_iptables

logger = logging.getLogger(__name__)


def check_ip_forwarding() -> bool:
    """
    Check if IP forwarding is currently enabled.
    
    Returns:
        True if enabled, False otherwise
    """
    try:
        output = execute_command(["sysctl", "-n", "net.ipv4.ip_forward"])
        return output.strip() == "1"
    except Exception as e:
        logger.warning(f"Could not check IP forwarding status: {e}")
        return False


def list_wilab_rules() -> dict:
    """
    List all active Wi-Lab iptables rules.
    
    Returns:
        Dictionary with 'nat' and 'forward' lists of rules
    """
    rules = {"nat": [], "forward": []}
    
    try:
        # Check NAT table
        nat_output = execute_command(["iptables", "-t", "nat", "-L", "POSTROUTING", "-n", "-v"])
        for line in nat_output.split('\n'):
            if 'wilab-nat' in line:
                rules["nat"].append(line.strip())
        
        # Check FORWARD chain
        forward_output = execute_command(["iptables", "-L", "FORWARD", "-n", "-v"])
        for line in forward_output.split('\n'):
            if 'wilab-' in line:
                rules["forward"].append(line.strip())
    
    except Exception as e:
        logger.warning(f"Could not list iptables rules: {e}")
    
    return rules


def log_host_impact_warning():
    """Log warning about host network impact."""
    logger.warning("=" * 80)
    logger.warning("⚠️  NETWORK_MODE=HOST: All networking changes affect the HOST system!")
    logger.warning("=" * 80)
    logger.warning("Wi-Lab will modify:")
    logger.warning("  - IP forwarding (sysctl net.ipv4.ip_forward)")
    logger.warning("  - iptables NAT rules (POSTROUTING)")
    logger.warning("  - iptables FORWARD rules")
    logger.warning("  - WiFi interface state (AP mode)")
    logger.warning("")
    logger.warning("All rules include '-m comment --comment wilab-*' for tracking.")
    logger.warning("To clean up manually: bash scripts/cleanup-wilab-rules.sh")
    logger.warning("=" * 80)


def check_existing_wilab_rules():
    """Check and warn about existing Wi-Lab rules (from previous runs)."""
    rules = list_wilab_rules()
    
    if rules["nat"] or rules["forward"]:
        logger.warning("⚠️  Found existing Wi-Lab iptables rules (from previous run?):")
        
        if rules["nat"]:
            logger.warning(f"  NAT rules: {len(rules['nat'])} found")
            for rule in rules["nat"][:3]:  # Show first 3
                logger.warning(f"    {rule}")
        
        if rules["forward"]:
            logger.warning(f"  FORWARD rules: {len(rules['forward'])} found")
            for rule in rules["forward"][:3]:  # Show first 3
                logger.warning(f"    {rule}")
        
        logger.warning("  Consider running cleanup script before starting new networks.")
    else:
        logger.info("✅ No existing Wi-Lab iptables rules found")
