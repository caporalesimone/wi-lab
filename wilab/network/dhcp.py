import logging
import os
import tempfile
from typing import Optional, List, Tuple
from ipaddress import IPv4Network
from .commands import execute_command, CommandError

logger = logging.getLogger(__name__)

# Directory for dnsmasq config files
DNSMASQ_CONFIG_DIR = "/tmp/wilab-dnsmasq"
DNSMASQ_PID_DIR = "/tmp/wilab-dnsmasq/pids"


class DhcpServerError(Exception):
    """Exception raised for DHCP server issues."""
    pass


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
    
    def _parse_subnet(self, subnet: str) -> Tuple[str, str, str]:
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
        dns_server: str
    ) -> str:
        """
        Generate dnsmasq configuration for an interface.
        
        Args:
            interface: WiFi interface name (e.g., "wlan0")
            gateway: Gateway IP address (e.g., "192.168.10.1")
            dhcp_range: DHCP range (e.g., "192.168.10.10,192.168.10.250")
            dns_server: DNS server IP address (e.g., "192.168.10.21")
            
        Returns:
            dnsmasq configuration as string
        """
        config_lines = [
            f"# Wi-Lab dnsmasq config for {interface}",
            f"interface={interface}",
            f"bind-interfaces",
            f"listen-address={gateway}",
            f"dhcp-range={dhcp_range},255.255.255.0,12h",
            f"dhcp-option=option:router,{gateway}",
            f"dhcp-leasefile={lease_file}",
        ]
        
        # DNS server configuration (always use explicit value from config)
        config_lines.append(f"dhcp-option=option:dns-server,{dns_server}")
        
        # Minimal additional settings
        config_lines.extend([
            "port=0",    # Disable DNS server; DHCP-only to avoid 127.0.0.1 conflicts
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
        dns_server: str
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
                dns_server
            )
            
            # Write config to file
            config_file = os.path.join(DNSMASQ_CONFIG_DIR, f"dnsmasq-{net_id}.conf")
            with open(config_file, "w") as f:
                f.write(config_content)
            
            logger.info(f"Generated dnsmasq config at {config_file}")
            
            # Configure interface IP address (gateway)
            self._configure_interface(interface, gateway_addr, subnet)
            
            # Ensure dnsmasq is available
            try:
                execute_command(["dnsmasq", "--version"])
            except CommandError:
                raise DhcpServerError("dnsmasq not installed")

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
            try:
                execute_command([
                    "dnsmasq",
                    f"--conf-file={config_file}",
                    f"--pid-file={pid_file}",
                ])
            except CommandError as e:
                raise DhcpServerError(f"dnsmasq failed to start: {e}") from e
            
            logger.info(f"dnsmasq started for {net_id} on {interface}")
            
            # Store instance info
            self._instances[net_id] = {
                "interface": interface,
                "subnet": subnet,
                "gateway": gateway_addr,
                "config_file": config_file,
                "pid_file": pid_file,
                "lease_file": lease_file,
                "network_addr": network_addr,
                "dhcp_range": dhcp_range,
            }
            
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
            if pid_file and os.path.exists(pid_file):
                try:
                    with open(pid_file, "r") as f:
                        pid = f.read().strip()
                    if pid:
                        execute_command(["kill", pid], check=False)
                except Exception as e:
                    logger.warning(f"Could not stop dnsmasq for {net_id}: {e}")
                try:
                    os.remove(pid_file)
                except OSError:
                    pass
            
            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info(f"Removed dnsmasq config {config_file}")
            
            del self._instances[net_id]
            logger.info(f"DHCP server stopped for {net_id}")
        
        except Exception as e:
            logger.error(f"Error stopping DHCP server for {net_id}: {e}")
    
    def _configure_interface(self, interface: str, ip_address: str, subnet: str) -> None:
        """
        Configure interface with IP address and bring it up.
        
        Args:
            interface: Interface name
            ip_address: IP address to assign (e.g., "192.168.10.1")
            subnet: CIDR subnet for calculating prefix length
        """
        try:
            # Extract prefix length from CIDR
            prefix_len = subnet.split('/')[-1]
            
            # Bring interface up
            try:
                execute_command(["ip", "link", "set", interface, "up"])
            except CommandError as e:
                logger.warning(f"Could not bring up interface {interface}: {e}")
            
            # Flush existing addresses (non-fatal if fails)
            try:
                execute_command(
                    ["ip", "addr", "flush", "dev", interface],
                    check=False
                )
            except CommandError:
                pass
            
            # Assign new address
            try:
                execute_command([
                    "ip", "addr", "add",
                    f"{ip_address}/{prefix_len}",
                    "dev", interface
                ])
                logger.info(f"Configured interface {interface} with {ip_address}/{prefix_len}")
            except CommandError as e:
                logger.warning(f"Could not configure interface {interface}: {e}")
        
        except Exception as e:
            logger.error(f"Error in interface configuration: {e}")
    
    def get_subnet_info(self, net_id: str) -> Optional[dict]:
        """
        Get subnet information for a network.
        
        Args:
            net_id: Network identifier
            
        Returns:
            Dictionary with subnet info or None if not active
        """
        return self._instances.get(net_id)
    
    def list_active(self) -> List[str]:
        """Get list of active DHCP server net_ids."""
        return list(self._instances.keys())
    
    def status(self) -> dict:
        """Return minimal status for dnsmasq instances."""
        instances = []
        for net_id, data in self._instances.items():
            pid_file = data.get("pid_file")
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "pid_file": pid_file,
                "pid_file_exists": bool(pid_file and os.path.exists(pid_file)),
            })
        return {
            "running": any(item["pid_file_exists"] for item in instances),
            "instances": instances,
        }
    
    def stop_all(self) -> None:
        """Stop all active DHCP servers."""
        net_ids = list(self._instances.keys())
        for net_id in net_ids:
            self.stop(net_id)
        logger.info("All DHCP servers stopped")


