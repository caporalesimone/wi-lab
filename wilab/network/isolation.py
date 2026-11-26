"""Network isolation using iptables to prevent inter-subnet traffic."""

import logging

from .commands import CommandError, execute_iptables, rule_exists

logger = logging.getLogger(__name__)


class IsolationManager:
    """Manages iptables rules to isolate WiFi AP networks from each other."""
    
    def __init__(self):
        """Initialize isolation manager."""
        self._active_subnets: set[str] = set()
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
        
        # Add rules to block traffic between this subnet and all existing subnets.
        # All or nothing (NET-2): on failure the rules already added are removed
        # and CommandError is raised, so the network startup fails and rolls back.
        added: list[tuple[str, str]] = []
        try:
            for existing_subnet in self._active_subnets:
                for pair in ((subnet, existing_subnet), (existing_subnet, subnet)):
                    self._block_traffic(*pair)
                    added.append(pair)
        except CommandError:
            for pair in reversed(added):
                self._unblock_traffic(*pair)
            raise
        
        self._active_subnets.add(subnet)
        logger.info(f"Isolation rules added for {subnet}")
    
    def remove_network(self, subnet: str) -> None:
        """
        Remove isolation rules for a network subnet.
        
        Args:
            subnet: CIDR subnet (e.g., "192.168.10.0/24")
        """
        if subnet not in self._active_subnets:
            # Normal after a startup that failed before isolation was applied.
            logger.debug(f"Subnet {subnet} has no isolation rules to remove")
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

        Both subnets come from the AP subnet allocator, so they are Wi-Lab's own
        whatever `dhcp_base_network` is (NET-3: 10.x and 172.16-31.x included).

        Args:
            source: Source CIDR subnet
            destination: Destination CIDR subnet

        Raises:
            CommandError: If iptables fails.
        """
        try:
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
            raise
    
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
    
    def verify(self) -> list[str]:
        """Re-add isolation rules that disappeared from FORWARD (WD-7); returns the repairs."""
        repaired: list[str] = []
        for source in sorted(self._active_subnets):
            for destination in sorted(self._active_subnets):
                if source == destination:
                    continue
                rule = [
                    "FORWARD", "-s", source, "-d", destination, "-j", "DROP",
                    "-m", "comment", "--comment", "wilab-isolation",
                ]
                # Raises when iptables cannot tell: never add a rule that may exist (REV-3).
                if not rule_exists(execute_iptables, rule):
                    execute_iptables(["-A", *rule])
                    repaired.append(f"isolation {source} -> {destination}")
        return repaired

    def get_active_subnets(self) -> list[str]:
        """Get list of subnets with active isolation rules."""
        return sorted(list(self._active_subnets))
    