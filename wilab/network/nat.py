"""NAT and Internet forwarding management using iptables."""

import logging
import shlex
from itertools import pairwise

from .commands import CommandError, execute_command, execute_iptables, execute_sysctl

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
        # Last interface found on the default route, for logging a change only.
        self._last_upstream: str | None = None
        # net_id -> upstream interface named by that network's NAT rules (STAB-6)
        self._upstream_by_network: dict[str, str] = {}
        self._blocked_rules: dict[str, list[list[str]]] = {}
        self._nat_networks: set[str] = set()
        logger.info(f"NatManager initialized with upstream={upstream_interface}")

    def remove_stale_rules(self) -> None:
        """Remove only rules owned by Wi-Lab from the chains it manages."""
        for table, chain in ((None, "FORWARD"), ("nat", "POSTROUTING")):
            prefix = ["-t", table] if table else []
            try:
                listing = execute_iptables([*prefix, "-S", chain])
            except CommandError as exc:
                logger.warning("Cannot list stale Wi-Lab rules in %s: %s", chain, exc)
                continue
            for line in listing.splitlines():
                try:
                    tokens = shlex.split(line)
                except ValueError:
                    logger.warning("Cannot parse firewall rule in %s", chain)
                    continue
                if tokens[:2] != ["-A", chain]:
                    continue
                comments = [b for a, b in pairwise(tokens) if a == "--comment"]
                if not any(
                    comment in ("wilab-isolation", "wilab-protect-existing")
                    or comment.startswith(("wilab-nat-", "wilab-forward-", "wilab-block-"))
                    for comment in comments
                ):
                    continue
                try:
                    execute_iptables([*prefix, "-D", *tokens[1:]])
                except CommandError as exc:
                    logger.warning("Cannot remove stale Wi-Lab rule in %s: %s", chain, exc)
    
    def _discover_upstream_interface(self) -> str:
        """
        Discover upstream interface from default route.
        
        Returns:
            Interface name (e.g., "eth0")
            
        Raises:
            RuntimeError: If no default route found
        """
        # Resolved on every use (STAB-6): the default route can move to another
        # interface (cable moved, VPN, failover) while the service runs.
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
                        if interface != self._last_upstream:
                            log = logger.info if self._last_upstream is None else logger.warning
                            log("Upstream interface (default route): %s", interface)
                            self._last_upstream = interface
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
    
    def _rule_exists(self, table: str | None, args: list) -> bool:
        """
        Check if an iptables rule exists.
        
        Args:
            table: Table name (e.g., "nat") or None for filter
            args: Rule arguments to check
            
        Returns:
            True if rule exists, False otherwise
        """
        try:
            cmd = ["-t", table] if table else []
            cmd.extend(["-C", *args])
            execute_iptables(cmd)
            return True
        except Exception:
            return False

    def block_internet(self, wifi_interface: str, net_id: str) -> None:
        """Block forwarded traffic for an AP, including established flows."""
        comment = ["-m", "comment", "--comment", f"wilab-block-{net_id}"]
        rules = [
            ["FORWARD", "-i", wifi_interface, "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset", *comment],
            ["FORWARD", "-i", wifi_interface, "-j", "REJECT", *comment],
            ["FORWARD", "-o", wifi_interface, "-j", "DROP", *comment],
        ]
        if net_id in self._blocked_rules:
            if self._blocked_rules[net_id] == list(reversed(rules)):
                return
            raise RuntimeError(f"Incomplete Internet block for {net_id}; cleanup required")
        installed = self._blocked_rules[net_id] = []
        try:
            for rule in reversed(rules):
                execute_iptables(["-I", rule[0], "1", *rule[1:]])
                installed.append(rule)
        except CommandError as exc:
            raise RuntimeError(f"Cannot block Internet for {net_id}: {exc}") from exc

    def has_pending_network(self, net_id: str) -> bool:
        return net_id in self._blocked_rules or net_id in self._nat_networks

    def unblock_internet(self, net_id: str) -> None:
        """Remove tracked blocks, retaining failed rules for another cleanup."""
        rules = self._blocked_rules.get(net_id, [])
        removed: list[list[str]] = []
        while rules:
            rule = rules[-1]
            try:
                execute_iptables(["-D", *rule])
            except CommandError as exc:
                for removed_rule in reversed(removed):
                    try:
                        execute_iptables(["-I", removed_rule[0], "1", *removed_rule[1:]])
                        rules.append(removed_rule)
                    except CommandError as restore_exc:
                        logger.error("Cannot restore Internet block for %s: %s", net_id, restore_exc)
                raise RuntimeError(f"Cannot remove Internet block for {net_id}: {exc}") from exc
            removed.append(rules.pop())
        self._blocked_rules.pop(net_id, None)
    
    @staticmethod
    def _nat_rules(
        wifi_interface: str, net_id: str, subnet: str, upstream: str,
    ) -> list[tuple[str | None, list[str]]]:
        """The (table, rule) pairs that give one AP subnet Internet access."""
        return [
            ("nat", [
                "POSTROUTING", "-s", subnet, "-o", upstream, "-j", "MASQUERADE",
                "-m", "comment", "--comment", f"wilab-nat-{net_id}",
            ]),
            (None, [
                "FORWARD", "-i", wifi_interface, "-o", upstream, "-j", "ACCEPT",
                "-m", "comment", "--comment", f"wilab-forward-{net_id}",
            ]),
            (None, [
                "FORWARD", "-i", upstream, "-o", wifi_interface, "-m", "state",
                "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT",
                "-m", "comment", "--comment", f"wilab-forward-{net_id}",
            ]),
        ]

    def verify(self, wifi_interface: str, net_id: str, subnet: str) -> list[str]:
        """Restore what a running network lost from its NAT or Internet block (WD-7).

        Returns a description of each repair; an empty list when all was in place.
        """
        repaired: list[str] = []
        if net_id in self._nat_networks:
            if execute_sysctl("net.ipv4.ip_forward").strip() != "1":
                repaired.append("ip_forward")
            upstream = self.get_upstream_interface()
            previous = self._upstream_by_network.get(net_id)
            if previous not in (None, upstream):
                repaired.append(f"NAT upstream {previous} -> {upstream}")
            missing = [
                rule[0] for table, rule in self._nat_rules(wifi_interface, net_id, subnet, upstream)
                if not self._rule_exists(table, rule)
            ]
            repaired += [f"NAT {chain} rule" for chain in missing]
            if repaired:
                self.enable_nat(wifi_interface, net_id, subnet)
        installed = self._blocked_rules.get(net_id, [])
        present = [rule for rule in installed if self._rule_exists(None, rule)]
        if len(present) != len(installed):
            # Reinstall the whole block in its order: TCP reset before the generic reject.
            for rule in present:
                execute_iptables(["-D", *rule])
            for rule in installed:  # stored in insertion order, each inserted at the top
                execute_iptables(["-I", rule[0], "1", *rule[1:]])
            repaired.append("Internet block rules")
        return repaired

    def enable_nat(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Enable NAT for a WiFi interface to allow Internet access.
        
        Args:
            wifi_interface: WiFi interface to enable NAT for (e.g., "wlan0")
            net_id: Network identifier for tracking rules (e.g., "ap-01")
            
        Raises:
            RuntimeError: If iptables commands fail
        """
        upstream = self.get_upstream_interface()
        previous = self._upstream_by_network.get(net_id)
        if previous not in (None, upstream):
            # The default route moved: rules naming the old interface give no Internet.
            logger.warning("Moving NAT of %s from %s to %s", net_id, previous, upstream)
            self._remove_nat_rules(wifi_interface, net_id)
        self._upstream_by_network[net_id] = upstream
        self._nat_networks.add(net_id)
        
        logger.info(f"Enabling NAT for {net_id}: {wifi_interface} -> {upstream}")
        
        try:
            # SAFETY: Check default FORWARD policy first
            # If policy is DROP, we need to be extremely careful with rule order
            try:
                forward_policy = execute_iptables(["-S", "FORWARD"])
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
                            "-I", "FORWARD", str(1 + sum(len(r) for r in self._blocked_rules.values())),
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
            
            # Add each rule only if it is missing, so this also repairs a partial set (WD-7).
            for table, rule in self._nat_rules(wifi_interface, net_id, subnet, upstream):
                if not self._rule_exists(table, rule):
                    execute_iptables([*(["-t", table] if table else []), "-A", *rule])
                    logger.debug("Added %s rule for %s", rule[0], net_id)

            self.unblock_internet(net_id)
            logger.info(f"NAT enabled for {net_id} ({wifi_interface})")
        
        except Exception as e:
            logger.error(f"Failed to enable NAT for {net_id} ({wifi_interface}): {e}")
            raise RuntimeError(f"Cannot enable NAT: {e}") from e
    
    def disable_nat(self, wifi_interface: str, net_id: str, subnet: str) -> None:
        """
        Disable NAT for a WiFi interface.
        
        Args:
            wifi_interface: WiFi interface to disable NAT for
            net_id: Network identifier to match rules (e.g., "ap-01")
        """
        self.block_internet(wifi_interface, net_id)
        self._remove_nat_rules(wifi_interface, net_id)

    def release_network(self, wifi_interface: str, net_id: str) -> None:
        if net_id in self._nat_networks:
            self._remove_nat_rules(wifi_interface, net_id)
            self._nat_networks.discard(net_id)
            self._upstream_by_network.pop(net_id, None)
        self.unblock_internet(net_id)

    def _remove_nat_rules(self, wifi_interface: str, net_id: str) -> None:
        for table, chain, comment in (
            ("nat", "POSTROUTING", f"wilab-nat-{net_id}"),
            (None, "FORWARD", f"wilab-forward-{net_id}"),
        ):
            prefix = ["-t", table] if table else []
            try:
                listing = execute_iptables([*prefix, "-S", chain])
                for line in listing.splitlines():
                    tokens = shlex.split(line)
                    if tokens[:2] == ["-A", chain] and comment in [
                        value for option, value in pairwise(tokens) if option == "--comment"
                    ]:
                        execute_iptables([*prefix, "-D", *tokens[1:]])
            except (CommandError, ValueError) as exc:
                raise RuntimeError(f"Cannot remove NAT rules for {net_id}: {exc}") from exc
        logger.info("NAT disabled for %s (%s)", net_id, wifi_interface)
    
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
            nat_rules = execute_iptables(["-t", "nat", "-S"])
        except Exception as e:
            errors.append(f"nat: {e}")
        try:
            fwd_rules = execute_iptables(["-S", "FORWARD"])
        except Exception as e:
            errors.append(f"forward: {e}")
        return {
            "nat": nat_rules,
            "forward": fwd_rules,
            "errors": errors,
        }
