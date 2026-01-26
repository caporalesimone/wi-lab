"""NAT and Internet forwarding management using iptables."""

import logging
from typing import Optional
from .commands import execute_command, execute_iptables, execute_sysctl

logger = logging.getLogger(__name__)


class NatManager:
    """Manages NAT rules and IP forwarding for Internet access."""
    
    def __init__(self, upstream_interface: str = "auto"):
        """
        Initialize NAT manager.
        
        Args:
            upstream_interface: Interface to use for Internet (e.g., "eth0") or "auto" for autodiscovery
        """
        self.upstream_interface = upstream_interface
        self._resolved_upstream: Optional[str] = None
        logger.info(f"NatManager initialized with upstream={upstream_interface}")
    
    def _discover_upstream_interface(self) -> str:
        """
        Discover upstream interface from default route.
        
        Returns:
            Interface name (e.g., "eth0")
            
        Raises:
            RuntimeError: If no default route found
        """
        if self._resolved_upstream:
            return self._resolved_upstream
        
        try:
            # Get default route: ip route show default
            output = execute_command(["ip", "route", "show", "default"])
            
            # Parse output: "default via 192.168.1.1 dev eth0 ..."
            for line in output.strip().split('\n'):
                if 'default' in line and 'dev' in line:
                    parts = line.split()
                    dev_idx = parts.index('dev')
                    if dev_idx + 1 < len(parts):
                        interface = parts[dev_idx + 1]
                        self._resolved_upstream = interface
                        logger.info(f"Discovered upstream interface: {interface}")
                        return interface
            
            raise RuntimeError("No default route found")
        
        except Exception as e:
            logger.error(f"Failed to discover upstream interface: {e}")
            raise RuntimeError(f"Cannot determine upstream interface: {e}") from e
    
    def get_upstream_interface(self) -> str:
        """
        Get the upstream interface to use for NAT.
        
        Returns:
            Interface name
        """
        if self.upstream_interface == "auto":
            return self._discover_upstream_interface()
        return self.upstream_interface
    
    def enable_ip_forwarding(self) -> None:
        """
        Enable IPv4 forwarding at kernel level.
        
        Raises:
            RuntimeError: If sysctl command fails
        """
        try:
            execute_sysctl("net.ipv4.ip_forward", "1")
            logger.info("IP forwarding enabled")
        except Exception as e:
            logger.error(f"Failed to enable IP forwarding: {e}")
            raise RuntimeError(f"Cannot enable IP forwarding: {e}") from e
    
    def disable_ip_forwarding(self) -> None:
        """Disable IPv4 forwarding (only if no other networks need it)."""
        try:
            execute_sysctl("net.ipv4.ip_forward", "0")
            logger.info("IP forwarding disabled")
        except Exception as e:
            logger.warning(f"Failed to disable IP forwarding: {e}")
    
    def _rule_exists(self, table: Optional[str], args: list) -> bool:
        """
        Check if an iptables rule exists.
        
        Args:
            table: Table name (e.g., "nat") or None for filter
            args: Rule arguments to check
            
        Returns:
            True if rule exists, False otherwise
        """
        try:
            cmd = ["iptables"]
            if table:
                cmd.extend(["-t", table])
            cmd.extend(["-C"] + args)
            execute_command(cmd)
            return True
        except Exception:
            return False
    
    def enable_nat(self, wifi_interface: str, net_id: str) -> None:
        """
        Enable NAT for a WiFi interface to allow Internet access.
        
        Args:
            wifi_interface: WiFi interface to enable NAT for (e.g., "wlan0")
            net_id: Network identifier for tracking rules (e.g., "ap-01")
            
        Raises:
            RuntimeError: If iptables commands fail
        """
        upstream = self.get_upstream_interface()
        
        logger.info(f"Enabling NAT for {net_id}: {wifi_interface} -> {upstream}")
        
        try:
            # SAFETY: Check default FORWARD policy first
            # If policy is DROP, we need to be extremely careful with rule order
            try:
                forward_policy = execute_command(["iptables", "-S", "FORWARD"])
                if "-P FORWARD DROP" in forward_policy:
                    # Add rule to accept ESTABLISHED connections FIRST to protect existing SSH
                    # Only add if not already present
                    protect_rule = [
                        "FORWARD",
                        "-m", "conntrack",
                        "--ctstate", "ESTABLISHED,RELATED",
                        "-j", "ACCEPT",
                        "-m", "comment",
                        "--comment", "wilab-protect-existing"
                    ]
                    if not self._rule_exists(None, protect_rule):
                        logger.warning("FORWARD policy is DROP - adding accept rule for existing connections first")
                        execute_iptables([
                            "-I", "FORWARD", "1",
                            "-m", "conntrack",
                            "--ctstate", "ESTABLISHED,RELATED",
                            "-j", "ACCEPT",
                            "-m", "comment",
                            "--comment", "wilab-protect-existing"
                        ])
                    else:
                        logger.debug("FORWARD protection rule already exists")
            except Exception as e:
                logger.warning(f"Could not check FORWARD policy: {e}")
            
            # Enable IP forwarding first
            self.enable_ip_forwarding()
            
            # Add MASQUERADE rule (check if exists first to avoid duplicates)
            masquerade_rule = [
                "POSTROUTING",
                "-o", upstream,
                "-j", "MASQUERADE",
                "-m", "comment",
                "--comment", f"wilab-nat-{net_id}"
            ]
            if not self._rule_exists("nat", masquerade_rule):
                execute_iptables([
                    "-t", "nat",
                    "-A", "POSTROUTING",
                    "-o", upstream,
                    "-j", "MASQUERADE",
                    "-m", "comment",
                    "--comment", f"wilab-nat-{net_id}"
                ])
                logger.debug(f"Added MASQUERADE rule for {net_id}")
            else:
                logger.debug(f"MASQUERADE rule already exists for {net_id}")
            
            # Allow forwarding from WiFi to upstream (check if exists first)
            forward_in_rule = [
                "FORWARD",
                "-i", wifi_interface,
                "-o", upstream,
                "-j", "ACCEPT",
                "-m", "comment",
                "--comment", f"wilab-forward-{net_id}"
            ]
            if not self._rule_exists(None, forward_in_rule):
                execute_iptables([
                    "-A", "FORWARD",
                    "-i", wifi_interface,
                    "-o", upstream,
                    "-j", "ACCEPT",
                    "-m", "comment",
                    "--comment", f"wilab-forward-{net_id}"
                ])
                logger.debug(f"Added FORWARD ingress rule for {net_id}")
            else:
                logger.debug(f"FORWARD ingress rule already exists for {net_id}")
            
            # Allow established/related connections back (check if exists first)
            forward_out_rule = [
                "FORWARD",
                "-i", upstream,
                "-o", wifi_interface,
                "-m", "state",
                "--state", "RELATED,ESTABLISHED",
                "-j", "ACCEPT",
                "-m", "comment",
                "--comment", f"wilab-forward-{net_id}"
            ]
            if not self._rule_exists(None, forward_out_rule):
                execute_iptables([
                    "-A", "FORWARD",
                    "-i", upstream,
                    "-o", wifi_interface,
                    "-m", "state",
                    "--state", "RELATED,ESTABLISHED",
                    "-j", "ACCEPT",
                    "-m", "comment",
                    "--comment", f"wilab-forward-{net_id}"
                ])
                logger.debug(f"Added FORWARD egress rule for {net_id}")
            else:
                logger.debug(f"FORWARD egress rule already exists for {net_id}")
            
            logger.info(f"NAT enabled for {net_id} ({wifi_interface})")
        
        except Exception as e:
            logger.error(f"Failed to enable NAT for {net_id} ({wifi_interface}): {e}")
            raise RuntimeError(f"Cannot enable NAT: {e}") from e
    
    def disable_nat(self, wifi_interface: str, net_id: str) -> None:
        """
        Disable NAT for a WiFi interface.
        
        Args:
            wifi_interface: WiFi interface to disable NAT for
            net_id: Network identifier to match rules (e.g., "ap-01")
        """
        upstream = self.get_upstream_interface()
        
        logger.info(f"Disabling NAT for {net_id}: {wifi_interface} -> {upstream}")
        
        try:
            # Remove MASQUERADE rule (with net_id-specific comment filter)
            # Use -D (delete) instead of -A (append)
            # Loop to remove all instances (in case of duplicates from previous runs)
            for _ in range(10):  # Max 10 attempts to avoid infinite loop
                try:
                    execute_iptables([
                        "-t", "nat",
                        "-D", "POSTROUTING",
                        "-o", upstream,
                        "-j", "MASQUERADE",
                        "-m", "comment",
                        "--comment", f"wilab-nat-{net_id}"
                    ])
                except Exception:
                    break  # No more rules to delete
            
            # Remove FORWARD rules (with net_id-specific comment filter)
            for _ in range(10):
                try:
                    execute_iptables([
                        "-D", "FORWARD",
                        "-i", wifi_interface,
                        "-o", upstream,
                        "-j", "ACCEPT",
                        "-m", "comment",
                        "--comment", f"wilab-forward-{net_id}"
                    ])
                except Exception:
                    break
            
            for _ in range(10):
                try:
                    execute_iptables([
                        "-D", "FORWARD",
                        "-i", upstream,
                        "-o", wifi_interface,
                        "-m", "state",
                        "--state", "RELATED,ESTABLISHED",
                        "-j", "ACCEPT",
                        "-m", "comment",
                        "--comment", f"wilab-forward-{net_id}"
                    ])
                except Exception:
                    break
            
            logger.info(f"NAT disabled for {net_id} ({wifi_interface})")
        
        except Exception as e:
            # Don't fail if rules don't exist (might have been cleaned up already)
            logger.warning(f"Error disabling NAT for {net_id} ({wifi_interface}): {e}")
    
    def flush_all_rules(self) -> None:
        """Flush all NAT and FORWARD rules (use with caution)."""
        logger.warning("Flushing all NAT and FORWARD rules")
        try:
            execute_iptables(["-t", "nat", "-F"])
            execute_iptables(["-F", "FORWARD"])
        except Exception as e:
            logger.error(f"Failed to flush iptables rules: {e}")

    def status(self) -> dict:
        """Return minimal iptables status for debugging (nat + forward chains)."""
        nat_rules = None
        fwd_rules = None
        errors = []
        try:
            nat_rules = execute_command(["iptables", "-t", "nat", "-S"])
        except Exception as e:
            errors.append(f"nat: {e}")
        try:
            fwd_rules = execute_command(["iptables", "-S", "FORWARD"])
        except Exception as e:
            errors.append(f"forward: {e}")
        return {
            "nat": nat_rules,
            "forward": fwd_rules,
            "errors": errors,
        }
