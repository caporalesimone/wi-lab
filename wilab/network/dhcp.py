import logging
import os
import time
from ipaddress import IPv4Network
from typing import Any

from .commands import CommandError, ForegroundProcess, execute_command, start_foreground

logger = logging.getLogger(__name__)

from ..paths import DNSMASQ_RUNTIME_DIR, make_private_dir

# dnsmasq configuration and leases (STAB-2: private, not /tmp).
DNSMASQ_CONFIG_DIR = DNSMASQ_RUNTIME_DIR
# A configuration or bind error ends dnsmasq before it serves (it checks and binds
# before its main loop): a start waits this long to see such an exit (ARCH-6).
STARTUP_CHECK = 0.3
OUTPUT_TAIL_LINES = 20      # dnsmasq output kept to explain an early exit


def _no_event(line: bytes) -> str | None:
    """dnsmasq output has no events to classify; it is only drained and kept."""
    return None


class DhcpServerError(Exception):
    """Exception raised for DHCP server issues."""


class DhcpServer:
    """
    Manages dnsmasq DHCP server for WiFi AP networks.
    Uses static configuration from config.yaml - one subnet per interface.
    """
    
    def __init__(self):
        """Initialize DHCP server manager."""
        self._instances: dict[str, dict] = {}  # net_id -> {interface, subnet, config_file, gateway, process}
        self._ensure_config_dir()
    
    def _ensure_config_dir(self) -> None:
        """Ensure the config directory exists."""
        try:
            make_private_dir(DNSMASQ_CONFIG_DIR)
        except OSError as e:
            logger.warning("Could not create dnsmasq dir: %s", e)
    
    def _parse_subnet(self, subnet: str) -> tuple[str, str, str]:
        """
        Parse CIDR subnet into network, gateway, and DHCP range.
        
        Args:
            subnet: CIDR notation (e.g., "192.168.10.0/24")
            
        Returns:
            (network_addr, gateway_addr, dhcp_range_start-end)
        """
        try:
            net = IPv4Network(subnet, strict=False)
            total = net.num_addresses
            network_addr = str(net.network_address)
            gateway_addr = str(net[1])  # .1 of the subnet
            # Choose start/end safely for small subnets (e.g., /25) while preserving .250 for /24+
            start_idx = 10 if total > 20 else 2
            end_idx = min(total - 2, 250)
            if end_idx <= start_idx:
                end_idx = min(total - 2, start_idx + 5)
            dhcp_start = str(net[start_idx])
            dhcp_end = str(net[end_idx])
            dhcp_range = f"{dhcp_start},{dhcp_end}"
            
            return network_addr, gateway_addr, dhcp_range
        except ValueError as e:
            raise DhcpServerError(f"Invalid subnet {subnet}: {e}") from e
    
    def _generate_config(
        self,
        interface: str,
        gateway: str,
        dhcp_range: str,
        lease_file: str,
        dns_server: str, *, probe: bool = False, captive_dns: bool = False,
    ) -> str:
        """
        Generate dnsmasq configuration for an interface.
        
        Args:
            interface: WiFi interface name (e.g., "wlan0")
            gateway: Gateway IP address (e.g., "192.168.10.1")
            dhcp_range: DHCP range (e.g., "192.168.10.10,192.168.10.250")
            dns_server: DNS server IP address (e.g., "192.168.10.21")
            captive_dns: Answer every DNS query on the gateway with the gateway
                address. Clients still receive ``dns_server``; the captive
                portal redirects only unauthorized clients' queries here.
            
        Returns:
            dnsmasq configuration as string
        """
        config_lines = [
            f"# Wi-Lab dnsmasq config for {interface}",
            f"interface={interface}",
            "bind-interfaces",
            f"listen-address={gateway}",
            f"dhcp-range={dhcp_range},255.255.255.0,12h",
            f"dhcp-leasefile={lease_file}",
        ]
        
        if probe:
            config_lines.extend([
                "leasefile-ro", "dhcp-option=option:router", "dhcp-option=option:dns-server",
            ])
        else:
            config_lines.extend([
                f"dhcp-option=option:router,{gateway}", f"dhcp-option=option:dns-server,{dns_server}",
            ])
        
        if captive_dns:
            # --interface implicitly adds lo; exclude it so several portals can coexist.
            config_lines.extend(["except-interface=lo", f"address=/#/{gateway}"])
        else:
            config_lines.append("port=0")  # DHCP-only, avoids 127.0.0.1 conflicts

        # Minimal additional settings
        config_lines.extend([
            "no-resolv",  # Don't read /etc/resolv.conf
            "no-poll",    # Don't poll /etc/resolv.conf for changes
            "log-dhcp",   # Log DHCP transactions for debugging
        ])
        
        return "\n".join(config_lines) + "\n"
    
    def start(
        self,
        net_id: str,
        interface: str,
        subnet: str,
        dns_server: str, *, probe: bool = False, captive_dns: bool = False,
    ) -> dict:
        """
        Start DHCP server for a network interface with static subnet configuration.
        
        Args:
            net_id: Network identifier (for tracking)
            interface: WiFi interface name
            subnet: CIDR subnet (e.g., "192.168.10.0/24")
            dns_server: DNS server IP address (e.g., "192.168.10.21")
            
        Returns:
            Dictionary with subnet info (gateway, DHCP range, etc.)
            
        Raises:
            DhcpServerError: If server fails to start or already running
        """
        if net_id in self._instances:
            logger.warning("DHCP server already running for %s, skipping start", net_id)
            return self._instances[net_id]
        
        try:
            # Parse subnet
            network_addr, gateway_addr, dhcp_range = self._parse_subnet(subnet)
            
            lease_file = os.path.join(DNSMASQ_CONFIG_DIR, f"leases-{net_id}.db")
            
            # Generate config
            config_content = self._generate_config(
                interface,
                gateway_addr,
                dhcp_range,
                lease_file,
                dns_server, probe=probe, captive_dns=captive_dns,
            )
            
            # Write config to file
            config_file = os.path.join(DNSMASQ_CONFIG_DIR, f"dnsmasq-{net_id}.conf")
            # Registered before the launch, so stop() cleans up after a failed start.
            instance: dict[str, Any] = {
                "interface": interface,
                "subnet": subnet,
                "gateway": gateway_addr,
                "config_file": config_file,
                "lease_file": lease_file,
                "network_addr": network_addr,
                "dhcp_range": dhcp_range,
                "process": None,
            }
            self._instances[net_id] = instance
            with open(config_file, "w") as f:
                f.write(config_content)
            
            logger.info("Generated dnsmasq config at %s", config_file)
            
            # No separate `dnsmasq --version` (PERF-1): the config test below fails with
            # "Command not found: dnsmasq" when it is missing.
            # Pre-flight check config (static, minimal) to fail fast on syntax issues
            try:
                execute_command([
                    "dnsmasq",
                    "--test",
                    f"--conf-file={config_file}",
                ])
            except CommandError as e:
                raise DhcpServerError(f"dnsmasq config test failed: {e}") from e
            
            # A directly owned child, like hostapd (ARCH-6): no PID file to trust or
            # clean up. An empty --pid-file stops dnsmasq writing its default
            # /run/dnsmasq.pid, which every instance (and a system dnsmasq) would share.
            # The --conf-file argument stays: startup cleanup recognises a dnsmasq
            # orphaned by a crashed service by it (STAB-4).
            process = start_foreground(
                ["dnsmasq", "--keep-in-foreground", "--pid-file=", f"--conf-file={config_file}"],
                classify_output=_no_event, keep_lines=OUTPUT_TAIL_LINES,
            )
            instance["process"] = process
            self._check_started(process, net_id)
            logger.info("dnsmasq started for %s on %s", net_id, interface)
            
            logger.info("DHCP server started for %s: %s (gateway: %s)", net_id, subnet, gateway_addr)
            
            return self._instances[net_id]
        
        except Exception as e:
            raise DhcpServerError(f"Failed to start DHCP server for {net_id}: {e}") from e

    @staticmethod
    def _check_started(process: ForegroundProcess, net_id: str) -> None:
        """Raise if dnsmasq exits during STARTUP_CHECK (bad option, address in use)."""
        deadline = time.monotonic() + STARTUP_CHECK
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        code = process.poll()
        if code is None:
            return
        # dnsmasq output holds no secrets (DHCP options, addresses, its own errors).
        tail = "; ".join(line for line in process.output_tail(exited=True) if line.strip())
        raise DhcpServerError(
            f"dnsmasq for {net_id} exited at once with code {code}" + (f": {tail}" if tail else ""),
        )
    
    def stop(self, net_id: str, *, keep_leases: bool = False) -> None:
        """
        Stop DHCP server for a network interface.
        
        Args:
            net_id: Network identifier
            keep_leases: Keep the lease file. Only for a restart of dnsmasq on a
                network that goes on (watchdog repair): its clients keep their
                addresses. Otherwise the leases end with the network, so the
                next user of the adapter never inherits the previous clients
                (NET-7).
        """
        if net_id not in self._instances:
            # Normal after a startup that failed before DHCP started (NET-5).
            logger.debug("No DHCP server running for %s", net_id)
            return
        
        try:
            instance = self._instances[net_id]
            config_file = instance["config_file"]
            process = instance.get("process")
            if process is not None:
                process.stop()
                instance["process"] = None
            
            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info("Removed dnsmasq config %s", config_file)
            if not keep_leases:
                try:
                    os.remove(instance["lease_file"])
                except (KeyError, FileNotFoundError):
                    pass
            
            del self._instances[net_id]
            logger.info("DHCP server stopped for %s", net_id)
        
        except Exception as e:
            logger.warning("Error stopping DHCP server for %s: %s", net_id, e)
            raise DhcpServerError(f"Failed to stop DHCP server for {net_id}: {e}") from e
    
    def get_subnet_info(self, net_id: str) -> dict | None:
        """
        Get subnet information for a network.
        
        Args:
            net_id: Network identifier
            
        Returns:
            Dictionary with subnet info or None if not active
        """
        instance = self._instances.get(net_id)
        if instance is None:
            return None
        return {key: value for key, value in instance.items() if key != "process"}

    def is_running(self, net_id: str) -> bool:
        """Whether the dnsmasq child of this network is alive."""
        instance = self._instances.get(net_id)
        process = instance.get("process") if instance is not None else None
        return process is not None and process.poll() is None
    
    def list_active(self) -> list[str]:
        """Get list of active DHCP server net_ids."""
        return list(self._instances.keys())
    
    def status(self) -> dict:
        """Return minimal status for dnsmasq instances."""
        instances = []
        for net_id, data in self._instances.copy().items():
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "running": self.is_running(net_id),
            })
        return {
            "running": any(item["running"] for item in instances),
            "instances": instances,
        }
    