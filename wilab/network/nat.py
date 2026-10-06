"""NAT and Internet forwarding management using iptables."""

import logging
import shlex
from typing import List, Optional, Set
from .commands import execute_command, execute_iptables, execute_sysctl

logger = logging.getLogger(__name__)

# Rule shared by every network with Internet access (only added when the FORWARD policy is DROP).
PROTECT_EXISTING_RULE = [
    "FORWARD",
    "-m", "conntrack",
    "--ctstate", "ESTABLISHED,RELATED",
    "-j", "ACCEPT",
    "-m", "comment",
    "--comment", "wilab-protect-existing"
]


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
        # Networks whose NAT rules are in place, to know when the shared rule is no longer needed
        self._nat_networks: Set[str] = set()
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

    @staticmethod
    def _delete_rule(args: List[str], table: Optional[str] = None) -> None:
        """Delete every copy of a rule (duplicates may be left by previous runs)."""
        prefix = ["-t", table] if table else []
        for _ in range(10):  # Max 10 attempts to avoid infinite loop
            try:
                execute_iptables([*prefix, "-D", *args])
            except Exception:
                break  # No more rules to delete

    @staticmethod
    def _block_rules(wifi_interface: str, net_id: str) -> List[List[str]]:
        """
        FORWARD rules that cut one network off the Internet, in chain order.

        They match only this network's interface, so other networks are not affected.
        TCP gets a reset so that clients fail at once instead of waiting for a timeout.
        """
        comment = ["-m", "comment", "--comment", f"wilab-block-{net_id}"]
        return [
            ["FORWARD", "-i", wifi_interface, "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset", *comment],
            ["FORWARD", "-i", wifi_interface, "-j", "REJECT", "--reject-with", "icmp-port-unreachable", *comment],
            ["FORWARD", "-o", wifi_interface, "-j", "DROP", *comment],
        ]

    def _add_block_rules(self, wifi_interface: str, net_id: str) -> None:
        """
        Insert the block rules at the top of FORWARD, ahead of any ACCEPT for established traffic.

        Raises:
            RuntimeError: If iptables commands fail
        """
        # Start clean so the rules are never duplicated and always end up in the expected order
        self._remove_block_rules(wifi_interface, net_id)
        try:
            for rule in reversed(self._block_rules(wifi_interface, net_id)):
                execute_iptables(["-I", rule[0], "1", *rule[1:]])
        except Exception as e:
            logger.error(f"Failed to block Internet for {net_id} ({wifi_interface}): {e}")
            raise RuntimeError(f"Cannot block Internet: {e}") from e
        logger.debug(f"Added block rules for {net_id}")

    def _remove_block_rules(self, wifi_interface: str, net_id: str) -> None:
        """Remove the block rules of one network (no error if they are absent)."""
        for rule in self._block_rules(wifi_interface, net_id):
            self._delete_rule(rule)

    def enable_nat(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Enable NAT for a WiFi interface to allow Internet access.
        
        Args:
            wifi_interface: WiFi interface to enable NAT for (e.g., "wlan0")
            net_id: Network identifier for tracking rules (e.g., "ap-01")
            subnet: CIDR subnet of the network: only its clients are translated (e.g., "192.168.120.0/24")
            
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
                    if not self._rule_exists(None, PROTECT_EXISTING_RULE):
                        logger.warning("FORWARD policy is DROP - adding accept rule for existing connections first")
                        execute_iptables(["-I", "FORWARD", "1", *PROTECT_EXISTING_RULE[1:]])
                    else:
                        logger.debug("FORWARD protection rule already exists")
            except Exception as e:
                logger.warning(f"Could not check FORWARD policy: {e}")
            
            # Enable IP forwarding first
            self.enable_ip_forwarding()
            
            # Add MASQUERADE rule (check if exists first to avoid duplicates)
            masquerade_rule = [
                "POSTROUTING",
                "-s", subnet,
                "-o", upstream,
                "-j", "MASQUERADE",
                "-m", "comment",
                "--comment", f"wilab-nat-{net_id}"
            ]
            if not self._rule_exists("nat", masquerade_rule):
                execute_iptables([
                    "-t", "nat",
                    "-A", "POSTROUTING",
                    "-s", subnet,
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

            # Lift the block last: if anything above failed, the network stays blocked
            self._remove_block_rules(wifi_interface, net_id)
            self._nat_networks.add(net_id)

            logger.info(f"NAT enabled for {net_id} ({wifi_interface})")
        
        except Exception as e:
            logger.error(f"Failed to enable NAT for {net_id} ({wifi_interface}): {e}")
            raise RuntimeError(f"Cannot enable NAT: {e}") from e
    
    def disable_nat(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Cut one network off the Internet, including the connections already open.

        Removing the NAT rules is not enough: netfilter applies NAT to the first packet of a
        connection and keeps the translation in conntrack, so an open download would go on.
        Block rules on this network's interface stop those too. Other networks are not touched.

        Args:
            wifi_interface: WiFi interface to disable NAT for
            net_id: Network identifier to match rules (e.g., "ap-01")

        Raises:
            RuntimeError: If the block rules cannot be applied
        """
        logger.info(f"Disabling Internet for {net_id} ({wifi_interface})")
        # Block first, so there is no window in which open connections still pass
        self._add_block_rules(wifi_interface, net_id)
        self._remove_nat_rules(wifi_interface, net_id, subnet)
        logger.info(f"Internet disabled for {net_id} ({wifi_interface})")

    def release_network(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Remove every rule of one network (NAT and block rules), when the network stops.

        Args:
            wifi_interface: WiFi interface of the network
            net_id: Network identifier to match rules (e.g., "ap-01")
        """
        logger.info(f"Removing NAT and block rules for {net_id} ({wifi_interface})")
        self._remove_nat_rules(wifi_interface, net_id, subnet)
        self._remove_block_rules(wifi_interface, net_id)

    def _remove_nat_rules(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Remove the NAT and FORWARD accept rules of one network (no error if they are absent).

        The shared protect rule is removed as well once no network has NAT any more.
        """
        self._nat_networks.discard(net_id)
        if not self._nat_networks:
            self._delete_rule(PROTECT_EXISTING_RULE)

        try:
            upstream = self.get_upstream_interface()
        except RuntimeError as e:
            # Without an upstream interface no NAT rule can have been added
            logger.warning(f"No NAT rules to remove for {net_id}: {e}")
            return

        # Rules carry a net_id-specific comment, so only this network's rules are removed
        self._delete_rule([
            "POSTROUTING",
            "-s", subnet,
            "-o", upstream,
            "-j", "MASQUERADE",
            "-m", "comment",
            "--comment", f"wilab-nat-{net_id}"
        ], table="nat")
        self._delete_rule([
            "FORWARD",
            "-i", wifi_interface,
            "-o", upstream,
            "-j", "ACCEPT",
            "-m", "comment",
            "--comment", f"wilab-forward-{net_id}"
        ])
        self._delete_rule([
            "FORWARD",
            "-i", upstream,
            "-o", wifi_interface,
            "-m", "state",
            "--state", "RELATED,ESTABLISHED",
            "-j", "ACCEPT",
            "-m", "comment",
            "--comment", f"wilab-forward-{net_id}"
        ])
        logger.info(f"NAT rules removed for {net_id} ({wifi_interface})")
    
    def remove_stale_rules(self) -> int:
        """
        Remove every rule Wi-Lab left behind (comment starting with ``wilab-``), at service start.

        A crash or a kill skips the normal cleanup, and nothing remembers the rules after a
        restart. Rules without the ``wilab-`` comment are never touched. Failures are logged,
        never raised: starting the service must not depend on the firewall being readable.

        Returns:
            Number of rules removed
        """
        self._nat_networks.clear()
        removed = 0
        for table, chain in ((None, "FORWARD"), ("nat", "POSTROUTING")):
            prefix = ["-t", table] if table else []
            try:
                listing = execute_command(["iptables", *prefix, "-S", chain])
            except Exception as e:
                logger.warning(f"Cannot list {chain} rules to remove stale ones: {e}")
                continue
            for line in listing.splitlines():
                tokens = shlex.split(line)
                if tokens[:1] != ["-A"] or not any(
                    a == "--comment" and b.startswith("wilab-") for a, b in zip(tokens, tokens[1:])
                ):
                    continue
                try:
                    execute_iptables([*prefix, "-D", *tokens[1:]])
                    removed += 1
                except Exception as e:
                    logger.warning(f"Cannot remove stale rule '{line}': {e}")
        if removed:
            logger.warning(f"Removed {removed} stale Wi-Lab firewall rule(s) left by a previous run")
        return removed

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
