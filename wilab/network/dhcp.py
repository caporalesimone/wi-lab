import logging
import os
from ipaddress import IPv4Network
from pathlib import Path

from .commands import CommandError, CommandTimeout, execute_command, stop_process

logger = logging.getLogger(__name__)

# Directory for dnsmasq config files
DNSMASQ_CONFIG_DIR = "/tmp/wilab-dnsmasq"
DNSMASQ_PID_DIR = "/tmp/wilab-dnsmasq/pids"


class DhcpServerError(Exception):
    """Exception raised for DHCP server issues."""


class DhcpServer:
    """
    Manages dnsmasq DHCP server for WiFi AP networks.
    Uses static configuration from config.yaml - one subnet per interface.
    """
    
    def __init__(self):
        """Initialize DHCP server manager."""
        self._instances: dict[str, dict] = {}  # net_id -> {interface, subnet, config_file, gateway, pid_file}
        self._ensure_config_dir()
    
    def _ensure_config_dir(self) -> None:
        """Ensure config and pid directories exist."""
        try:
            os.makedirs(DNSMASQ_CONFIG_DIR, exist_ok=True)
            os.makedirs(DNSMASQ_PID_DIR, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not create dnsmasq dir: {e}")
    
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
            logger.warning(f"DHCP server already running for {net_id}, skipping start")
            return self._instances[net_id]
        
        try:
            # Parse subnet
            network_addr, gateway_addr, dhcp_range = self._parse_subnet(subnet)
            
            # Paths for pid and leases
            pid_file = os.path.join(DNSMASQ_PID_DIR, f"dnsmasq-{net_id}.pid")
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
            if os.path.lexists(pid_file):
                raise DhcpServerError(f"Existing dnsmasq PID file for {net_id}")
            instance = {
                "interface": interface,
                "subnet": subnet,
                "gateway": gateway_addr,
                "config_file": config_file,
                "pid_file": pid_file,
                "lease_file": lease_file,
                "network_addr": network_addr,
                "dhcp_range": dhcp_range,
                "process_stopped": True,
            }
            self._instances[net_id] = instance
            with open(config_file, "w") as f:
                f.write(config_content)
            
            logger.info(f"Generated dnsmasq config at {config_file}")
            
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
            
            # Start dnsmasq for this interface (daemonizes by default)
            instance["process_stopped"] = False
            try:
                execute_command([
                    "dnsmasq",
                    f"--conf-file={config_file}",
                    f"--pid-file={pid_file}",
                ])
            except CommandTimeout:
                # The launcher may already have forked.
                raise
            except CommandError as e:
                instance["process_stopped"] = not os.path.exists(pid_file)
                raise DhcpServerError(f"dnsmasq failed to start: {e}") from e
            
            if not os.path.isfile(pid_file):
                raise DhcpServerError(f"Missing dnsmasq PID file for {net_id}")
            pid = int(Path(pid_file).read_text().strip())
            if pid <= 0:
                raise DhcpServerError(f"Invalid dnsmasq PID for {net_id}")
            instance["pid"] = pid
            logger.info(f"dnsmasq started for {net_id} on {interface}")
            
            logger.info(f"DHCP server started for {net_id}: {subnet} (gateway: {gateway_addr})")
            
            return self._instances[net_id]
        
        except Exception as e:
            raise DhcpServerError(f"Failed to start DHCP server for {net_id}: {e}") from e
    
    def stop(self, net_id: str) -> None:
        """
        Stop DHCP server for a network interface.
        
        Args:
            net_id: Network identifier
        """
        if net_id not in self._instances:
            logger.warning(f"No DHCP server running for {net_id}")
            return
        
        try:
            instance = self._instances[net_id]
            config_file = instance["config_file"]
            pid_file = instance.get("pid_file")
            
            # Stop dnsmasq process if pid file exists
            if not instance.get("process_stopped"):
                pid = instance.get("pid")
                if pid is not None:
                    if self._owns_process(instance):
                        stop_process(pid)
                elif not pid_file or not os.path.exists(pid_file):
                    # The launch timed out before dnsmasq wrote its PID file (NET-6):
                    # find it by its --conf-file, which is unique per network. None
                    # found means the killed launcher never started a daemon.
                    found = self._find_process(config_file)
                    if found is not None:
                        logger.warning("Stopping dnsmasq for %s found without a PID file (pid %d)", net_id, found)
                        stop_process(found)
                    else:
                        logger.info("No dnsmasq process for %s; the launch never started one", net_id)
                else:
                    pid = int(Path(pid_file).read_text().strip())
                    if self._owns_process({**instance, "pid": pid}):
                        stop_process(pid)
                instance["process_stopped"] = True
            if pid_file:
                try:
                    os.remove(pid_file)
                except FileNotFoundError:
                    pass
            
            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info(f"Removed dnsmasq config {config_file}")
            
            del self._instances[net_id]
            logger.info(f"DHCP server stopped for {net_id}")
        
        except Exception as e:
            logger.error(f"Error stopping DHCP server for {net_id}: {e}")
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
        return {key: value for key, value in instance.items() if key != "pid"}

    @staticmethod
    def _find_process(config_file: str) -> int | None:
        """PID of the dnsmasq started with this configuration file, if any (NET-6)."""
        wanted = os.fsencode(f"--conf-file={config_file}")
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                args = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if args and Path(os.fsdecode(args[0])).name == "dnsmasq" and wanted in args[1:]:
                return int(entry.name)
        return None

    @staticmethod
    def _owns_process(instance: dict) -> bool:
        pid = instance.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            return False
        return (
            Path(os.fsdecode(args[0])).name == "dnsmasq"
            and os.fsencode(f"--conf-file={instance['config_file']}") in args[1:]
        )

    def is_running(self, net_id: str) -> bool:
        """Check the tracked DHCP daemon, not just its PID file."""
        instance = self._instances.get(net_id)
        return instance is not None and not instance.get("process_stopped") and self._owns_process(instance)
    
    def list_active(self) -> list[str]:
        """Get list of active DHCP server net_ids."""
        return list(self._instances.keys())
    
    def status(self) -> dict:
        """Return minimal status for dnsmasq instances."""
        instances = []
        for net_id, data in self._instances.copy().items():
            pid_file = data.get("pid_file")
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "pid_file": pid_file,
                "pid_file_exists": bool(pid_file and os.path.exists(pid_file)),
                # The process, not the PID file (BUG-2).
                "running": self.is_running(net_id),
            })
        return {
            "running": any(item["running"] for item in instances),
            "instances": instances,
        }
    
    def stop_all(self) -> None:
        """Stop all active DHCP servers."""
        net_ids = list(self._instances.keys())
        for net_id in net_ids:
            self.stop(net_id)
        logger.info("All DHCP servers stopped")


