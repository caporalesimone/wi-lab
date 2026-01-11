"""Network isolation using iptables to prevent inter-subnet traffic."""

import logging
from typing import List, Set
from .commands import execute_iptables, CommandError

logger = logging.getLogger(__name__)


class IsolationManager:
    """Manages iptables rules to isolate WiFi AP networks from each other."""
    
    def __init__(self):
        """Initialize isolation manager."""
        self._active_subnets: Set[str] = set()
        logger.info("IsolationManager initialized")
    
    def add_network(self, subnet: str) -> None:
        """
        Add isolation rules for a new network subnet.
        Blocks traffic between this subnet and all existing subnets.
        
        Args:
            subnet: CIDR subnet (e.g., "192.168.10.0/24")
        """
        if subnet in self._active_subnets:
            logger.warning(f"Subnet {subnet} already has isolation rules")
            return
        
        logger.info(f"Adding isolation rules for subnet {subnet}")
        
        # Add rules to block traffic between this subnet and all existing subnets
        for existing_subnet in self._active_subnets:
            self._block_traffic(subnet, existing_subnet)
            self._block_traffic(existing_subnet, subnet)
        
        self._active_subnets.add(subnet)
        logger.info(f"Isolation rules added for {subnet}")
    
    def remove_network(self, subnet: str) -> None:
        """
        Remove isolation rules for a network subnet.
        
        Args:
            subnet: CIDR subnet (e.g., "192.168.10.0/24")
        """
        if subnet not in self._active_subnets:
            logger.warning(f"Subnet {subnet} has no isolation rules to remove")
            return
        
        logger.info(f"Removing isolation rules for subnet {subnet}")
        
        # Remove rules blocking traffic between this subnet and others
        for other_subnet in self._active_subnets:
            if other_subnet != subnet:
                self._unblock_traffic(subnet, other_subnet)
                self._unblock_traffic(other_subnet, subnet)
        
        self._active_subnets.discard(subnet)
        logger.info(f"Isolation rules removed for {subnet}")
    
    def _block_traffic(self, source: str, destination: str) -> None:
        """
        Block traffic from source subnet to destination subnet.
        
        Args:
            source: Source CIDR subnet
            destination: Destination CIDR subnet
        """
        try:
            # SAFETY: Only block traffic BETWEEN WiFi subnets (192.168.x.0/24)
            # Do NOT block traffic to/from host's main network
            # Skip if either subnet is not a WiFi subnet (not 192.168.x.0/24)
            if not (source.startswith("192.168.") and destination.startswith("192.168.")):
                logger.warning(f"Skipping isolation rule for non-WiFi subnets: {source} -> {destination}")
                return
            
            # Append rule to FORWARD chain to block inter-subnet traffic
            # Use -A (append) instead of -I (insert) to avoid interfering with existing rules
            # iptables -A FORWARD -s <source> -d <destination> -j DROP -m comment --comment "wilab-isolation"
            execute_iptables([
                "-A", "FORWARD",
                "-s", source,
                "-d", destination,
                "-j", "DROP",
                "-m", "comment",
                "--comment", "wilab-isolation"
            ])
            logger.debug(f"Blocked traffic: {source} -> {destination}")
        except CommandError as e:
            logger.error(f"Failed to block traffic {source} -> {destination}: {e}")
    
    def _unblock_traffic(self, source: str, destination: str) -> None:
        """
        Remove block rule for traffic from source to destination.
        
        Args:
            source: Source CIDR subnet
            destination: Destination CIDR subnet
        """
        try:
            # Delete rule from FORWARD chain (must match comment from insert)
            # iptables -D FORWARD -s <source> -d <destination> -j DROP -m comment --comment "wilab-isolation"
            execute_iptables([
                "-D", "FORWARD",
                "-s", source,
                "-d", destination,
                "-j", "DROP",
                "-m", "comment",
                "--comment", "wilab-isolation"
            ])
            logger.debug(f"Unblocked traffic: {source} -> {destination}")
        except CommandError as e:
            # Don't fail if rule doesn't exist (might have been cleaned up already)
            logger.warning(f"Could not remove block rule {source} -> {destination}: {e}")
    
    def get_active_subnets(self) -> List[str]:
        """Get list of subnets with active isolation rules."""
        return sorted(list(self._active_subnets))
    
    def flush_all(self) -> None:
        """
        Remove all isolation rules (emergency cleanup).
        WARNING: This removes ALL DROP rules in FORWARD chain.
        """
        logger.warning("Flushing all isolation rules")
        
        for subnet in list(self._active_subnets):
            self.remove_network(subnet)
        
        self._active_subnets.clear()
        logger.info("All isolation rules flushed")
