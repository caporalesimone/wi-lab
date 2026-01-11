"""hostapd configuration generation and process management for WiFi AP mode."""

import os
import logging
import tempfile
import time
from typing import Optional, Dict
from ..network.commands import execute_command, execute_iw, CommandError

logger = logging.getLogger(__name__)

HOSTAPD_CONFIG_DIR = "/tmp/wilab-hostapd"
HOSTAPD_PID_DIR = "/tmp/wilab-hostapd/pids"


class HostapdError(Exception):
    """Exception raised for hostapd operation failures."""
    pass


class HostapdManager:
    """Manages hostapd processes for WiFi AP networks."""
    
    def __init__(self):
        """Initialize hostapd manager."""
        self._instances: Dict[str, dict] = {}  # net_id -> {config_file, pid_file, interface}
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """Ensure config and pid directories exist."""
        try:
            os.makedirs(HOSTAPD_CONFIG_DIR, exist_ok=True)
            os.makedirs(HOSTAPD_PID_DIR, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not create hostapd dirs: {e}")
    
    def _generate_config(
        self,
        interface: str,
        ssid: str,
        channel: int,
        encryption: str,
        password: Optional[str],
        hidden: bool,
        band: str
    ) -> str:
        """
        Generate hostapd.conf content.
        
        Args:
            interface: WiFi interface name
            ssid: Network SSID
            channel: WiFi channel
            encryption: Encryption type (open, wpa, wpa2, wpa3, wpa2-wpa3)
            password: WPA password (None for open networks)
            hidden: Whether to hide SSID broadcast
            band: WiFi band (2.4ghz, 5ghz)
            
        Returns:
            hostapd configuration as string
        """
        config_lines = [
            f"# Wi-Lab hostapd config for {interface}",
            f"interface={interface}",
            f"driver=nl80211",
            f"ssid={ssid}",
            f"channel={channel}",
        ]
        
        # HW mode based on band
        if band == "5ghz":
            config_lines.append("hw_mode=a")
        else:  # 2.4ghz or dual
            config_lines.append("hw_mode=g")
        
        # Hidden SSID
        if hidden:
            config_lines.append("ignore_broadcast_ssid=1")
        
        # Encryption configuration
        if encryption == "open":
            # No encryption
            pass
        elif encryption in ["wpa", "wpa2", "wpa3", "wpa2-wpa3"]:
            if not password:
                raise HostapdError(f"Password required for {encryption} encryption")
            
            config_lines.append("wpa=2")  # WPA2
            config_lines.append(f"wpa_passphrase={password}")
            config_lines.append("wpa_key_mgmt=WPA-PSK")
            config_lines.append("rsn_pairwise=CCMP")
            
            # WPA3-specific settings
            if encryption in ["wpa3", "wpa2-wpa3"]:
                config_lines.append("ieee80211w=2")  # Management frame protection required
                config_lines.append("wpa_key_mgmt=SAE")
                
                if encryption == "wpa2-wpa3":
                    # Mixed mode
                    config_lines.append("wpa_key_mgmt=WPA-PSK SAE")
                    config_lines.append("ieee80211w=1")  # MFP optional for mixed
        
        # Additional recommended settings
        config_lines.extend([
            "country_code=IT",
            "ieee80211n=1",  # 802.11n support
            "wmm_enabled=1",  # WMM/QoS
        ])
        
        return "\n".join(config_lines) + "\n"
    
    def start(
        self,
        net_id: str,
        interface: str,
        ssid: str,
        channel: int,
        encryption: str,
        password: Optional[str],
        hidden: bool,
        band: str
    ) -> dict:
        """
        Start hostapd for an AP network.
        
        Args:
            net_id: Network identifier
            interface: WiFi interface
            ssid: Network SSID
            channel: WiFi channel
            encryption: Encryption type
            password: WPA password (None for open)
            hidden: Hide SSID broadcast
            band: WiFi band (2.4ghz/5ghz)
            
        Returns:
            Dictionary with hostapd instance info
            
        Raises:
            HostapdError: If hostapd fails to start or already running
        """
        if net_id in self._instances:
            logger.warning(f"hostapd already running for {net_id}")
            return self._instances[net_id]
        
        try:
            # Generate config
            config_content = self._generate_config(
                interface, ssid, channel, encryption, password, hidden, band
            )
            
            # Write config file
            config_file = os.path.join(HOSTAPD_CONFIG_DIR, f"hostapd-{net_id}.conf")
            with open(config_file, "w") as f:
                f.write(config_content)
            
            logger.info(f"Generated hostapd config at {config_file}")
            
            # Paths
            pid_file = os.path.join(HOSTAPD_PID_DIR, f"hostapd-{net_id}.pid")
            
            # Check hostapd is available
            try:
                execute_command(["which", "hostapd"])
            except CommandError:
                raise HostapdError("hostapd not installed")
            
            # Prepare interface for AP mode
            # This prevents hostapd from crashing due to interface state issues
            try:
                logger.info(f"Preparing interface {interface} for AP mode")
                # Bring interface down
                execute_command(["ip", "link", "set", interface, "down"])
                # Set to managed mode first (clean slate)
                execute_iw(["dev", interface, "set", "type", "managed"])
                # Flush any IP addresses
                execute_command(["ip", "addr", "flush", "dev", interface])
                # Leave interface DOWN - hostapd will bring it up itself
                # Small delay to let interface stabilize
                time.sleep(0.2)
            except CommandError as e:
                logger.warning(f"Failed to prepare interface {interface}: {e}")
                # Continue anyway - hostapd might still work
            
            # Start hostapd in background (config validation happens at startup)
            try:
                # Use -B for background mode and -P for pid file
                execute_command([
                    "hostapd",
                    "-B",  # Background
                    "-P", pid_file,  # PID file
                    config_file
                ])
            except CommandError as e:
                raise HostapdError(f"hostapd failed to start: {e}") from e
            
            # Verify process started
            time.sleep(0.5)
            if not os.path.exists(pid_file):
                raise HostapdError(f"hostapd pid file not created for {net_id}")
            
            logger.info(f"hostapd started for {net_id} on {interface}")
            
            # Store instance info
            self._instances[net_id] = {
                "interface": interface,
                "config_file": config_file,
                "pid_file": pid_file,
                "ssid": ssid,
                "channel": channel,
            }
            
            return self._instances[net_id]
        
        except Exception as e:
            raise HostapdError(f"Failed to start hostapd for {net_id}: {e}") from e
    
    def stop(self, net_id: str) -> None:
        """
        Stop hostapd for a network.
        
        Args:
            net_id: Network identifier
        """
        if net_id not in self._instances:
            logger.warning(f"No hostapd running for {net_id}")
            return
        
        try:
            instance = self._instances[net_id]
            pid_file = instance.get("pid_file")
            config_file = instance["config_file"]
            interface = instance.get("interface")

            # Stop hostapd process
            if pid_file and os.path.exists(pid_file):
                try:
                    with open(pid_file, "r") as f:
                        pid = f.read().strip()
                    if pid:
                        execute_command(["kill", pid], check=False)
                        logger.info(f"Sent SIGTERM to hostapd pid {pid}")
                        time.sleep(0.3)
                        # Force kill if still running
                        execute_command(["kill", "-9", pid], check=False)
                except Exception as e:
                    logger.warning(f"Could not stop hostapd for {net_id}: {e}")

                try:
                    os.remove(pid_file)
                except OSError:
                    pass

            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info(f"Removed hostapd config {config_file}")

            # Reset interface mode to managed to avoid lingering AP mode
            if interface:
                try:
                    execute_command(["ip", "link", "set", interface, "down"], check=False)
                    execute_command(["iw", "dev", interface, "set", "type", "managed"], check=False)
                    execute_command(["ip", "addr", "flush", "dev", interface], check=False)
                    execute_command(["ip", "link", "set", interface, "up"], check=False)
                    logger.info(f"Reset interface {interface} to managed mode")
                except Exception as e:
                    logger.warning(f"Failed to reset interface {interface} to managed: {e}")

            del self._instances[net_id]
            logger.info(f"hostapd stopped for {net_id}")

        except Exception as e:
            logger.error(f"Error stopping hostapd for {net_id}: {e}")
    
    def is_running(self, net_id: str) -> bool:
        """Check if hostapd is running for a network."""
        if net_id not in self._instances:
            return False
        
        pid_file = self._instances[net_id].get("pid_file")
        if not pid_file or not os.path.exists(pid_file):
            return False
        
        try:
            with open(pid_file, "r") as f:
                pid = f.read().strip()
            # Check if process exists
            execute_command(["kill", "-0", pid], check=True)
            return True
        except (CommandError, FileNotFoundError):
            return False
    
    def status(self) -> dict:
        """Return status of all hostapd instances."""
        instances = []
        for net_id, data in self._instances.items():
            pid_file = data.get("pid_file")
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "ssid": data.get("ssid"),
                "pid_file": pid_file,
                "running": self.is_running(net_id),
            })
        return {
            "running": any(inst["running"] for inst in instances),
            "instances": instances,
        }
    
    def stop_all(self) -> None:
        """Stop all hostapd instances."""
        net_ids = list(self._instances.keys())
        for net_id in net_ids:
            self.stop(net_id)
        logger.info("All hostapd instances stopped")

