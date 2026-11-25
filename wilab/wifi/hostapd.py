"""hostapd configuration generation and process management for WiFi AP mode."""

import logging
import os
import re
import signal
import tempfile
import time
from typing import TypedDict

from ..network.commands import (
    CommandError,
    CommandTimeout,
    ForegroundProcess,
    bounded_timeout,
    execute_command,
    execute_iw,
    start_foreground,
)
from .channels import ChannelLayout, channel_layouts
from .interface import interface_present

logger = logging.getLogger(__name__)

HOSTAPD_CONFIG_DIR = "/tmp/wilab-hostapd"
AP_READY_TIMEOUT = 10.0
# hostapd_cli waits for a reply that never comes if hostapd exits meanwhile,
# so each status probe is short and the process is checked between probes.
STATUS_PROBE_TIMEOUT = 1.0
_TRANSIENT_INIT_EVENTS = frozenset({"beacon_failed", "interface_init_failed"})
# Seconds to wait for hostapd to exit after it reports DISABLED (HAP-2).
DISABLED_SETTLE = 0.5
DFS_READY_TIMEOUT = 75.0
_STARTUP_STATES = frozenset({
    "UNINITIALIZED", "DISABLED", "COUNTRY_UPDATE", "ACS", "HT_SCAN", "DFS",
    "NO_IR", "ENABLED",
})
_OUTPUT_EVENTS = (
    (b"nl80211: Scan timeout", "scan_timeout"),
    (b"nl80211: Failed to set beacon", "beacon_failed"),
    (b"nl80211: Beacon set failed", "beacon_failed"),
    (b"nl80211: Failed to set channel", "channel_failed"),
    (b"nl80211: Failed to set interface", "interface_failed"),
    (b"Could not select hw_mode and channel", "channel_selection_failed"),
    (b"Failed to set beacon parameters", "beacon_failed"),
    (b"Failed to set channel", "channel_failed"),
    (b"Failed to initialize interface", "interface_init_failed"),
    (b"Interface initialization failed", "interface_init_failed"),
    (b"Channel list update timeout", "channel_list_timeout"),
    (b"Channel list updated - continue setup", "channel_list_updated"),
)
_INTERFACE_EVENT = re.compile(rb"^[\w.-]+: (AP-ENABLED|AP-DISABLED|DFS-CAC-START|DFS-CAC-COMPLETED)(?: |$)")
_STATE_TRANSITION = re.compile(rb"^[\w.-]+: interface state [A-Z_]+->([A-Z_]+)$")


# hostapd security lines per encryption, one line per key (HAP-10).
# wpa1 is legacy WPA/TKIP: TKIP is not allowed with HT, so it runs 802.11a/g only.
SECURITY_LINES: dict[str, list[str]] = {
    "open": [],
    "wpa1": ["wpa=1", "wpa_key_mgmt=WPA-PSK", "wpa_pairwise=TKIP"],
    "wpa2": ["wpa=2", "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP"],
    "wpa3": ["wpa=2", "wpa_key_mgmt=SAE", "rsn_pairwise=CCMP", "ieee80211w=2", "sae_pwe=2"],
    "wpa2-wpa3": [
        "wpa=2", "wpa_key_mgmt=WPA-PSK SAE", "rsn_pairwise=CCMP", "ieee80211w=1",
        "sae_require_mfp=1", "sae_pwe=2",
    ],
}


def mode_lines(band: str, width: int, generation: int, layout: ChannelLayout, encryption: str) -> list[str]:
    """hostapd lines for the Wi-Fi generation and channel width (HAP-11).

    generation 4 = 802.11n, 5 = 802.11ac (5 GHz only), 6 = 802.11ax. On 5 GHz
    802.11ax is announced together with 802.11ac, as clients expect. wpa1 turns
    HT off: the network is 802.11a/g at 20 MHz.
    """
    if encryption == "wpa1":
        return ["ieee80211n=0"]
    lines = ["ieee80211n=1"]
    if width >= 40:
        lines.append("ht_capab=[HT40+]" if layout.secondary_above else "ht_capab=[HT40-]")
    vht_width = 1 if width == 80 else 0
    if band == "5ghz" and generation >= 5:
        lines += ["ieee80211ac=1", f"vht_oper_chwidth={vht_width}"]
        if width == 80:
            lines.append(f"vht_oper_centr_freq_seg0_idx={layout.center}")
    if generation == 6:
        lines += ["ieee80211ax=1", f"he_oper_chwidth={vht_width}"]
        if width == 80:
            lines.append(f"he_oper_centr_freq_seg0_idx={layout.center}")
    return lines


def _classify_output(line: bytes) -> str | None:
    if match := _INTERFACE_EVENT.match(line):
        return match[1].decode("ascii").lower().replace("-", "_")
    if match := _STATE_TRANSITION.match(line):
        state = match[1].decode("ascii")
        if state in _STARTUP_STATES:
            return f"state_{state.lower()}"
    return next((event for prefix, event in _OUTPUT_EVENTS if line.startswith(prefix)), None)


class HostapdError(Exception):
    """Exception raised for hostapd operation failures."""


class HostapdRadioFailure(HostapdError):
    """Radio startup failed without a confirmed configuration error."""


class HostapdSegfault(HostapdRadioFailure):
    """The hostapd process terminated with SIGSEGV during startup."""


class HostapdInitFailure(HostapdRadioFailure):
    """hostapd exited after the driver rejected the beacon during interface setup.

    Observed as a transient failure: an immediate new start on the same radio succeeds.
    A radio failure on every attempt and request, not only during a retry (HAP-3).
    """


class HostapdInstance(TypedDict):
    interface: str
    config_file: str
    control_dir: str
    ssid: str
    process: ForegroundProcess | None


class HostapdManager:
    """Manages hostapd processes for WiFi AP networks."""
    
    def __init__(self) -> None:
        """Initialize hostapd manager."""
        self._instances: dict[str, HostapdInstance] = {}
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """Ensure the config directory exists."""
        try:
            os.makedirs(HOSTAPD_CONFIG_DIR, exist_ok=True)
        except OSError as e:
            logger.warning(f"Could not create hostapd dirs: {e}")
    
    def _generate_config(
        self,
        interface: str,
        ssid: str,
        channel: int,
        encryption: str,
        password: str | None,
        hidden: bool,
        band: str,
        country_code: str = "IT",
        channel_width: int = 20,
        wifi_generation: int = 4,
        layout: ChannelLayout | None = None,
    ) -> str:
        """
        Generate hostapd.conf content.
        
        Args:
            interface: WiFi interface name
            ssid: Network SSID
            channel: WiFi channel
            encryption: Encryption type (open, wpa1, wpa2, wpa3, wpa2-wpa3)
            password: WPA password (None for open networks)
            hidden: Whether to hide SSID broadcast
            band: WiFi band (2.4ghz, 5ghz)
            country_code: ISO 3166-1 alpha-2 country code for regulatory domain
            channel_width: 20, 40 or 80 MHz
            wifi_generation: 4 (802.11n), 5 (802.11ac) or 6 (802.11ax)
            layout: channel block chosen by the channel manager; the first
                possible one when omitted

        Returns:
            hostapd configuration as string
        """
        # Defence in depth: the API model already rejects control characters, but a
        # line break here would add arbitrary lines to a file read by a root process.
        for name, value in (("ssid", ssid), ("password", password or ""), ("country_code", country_code)):
            if "\n" in value or "\r" in value:
                raise HostapdError(f"Invalid {name}: line breaks are not allowed")
        config_lines = [
            f"# Wi-Lab hostapd config for {interface}",
            f"interface={interface}",
            "driver=nl80211",
            # ssid2 as a hex string: no SSID byte can be interpreted by the parser.
            f"ssid2={ssid.encode('utf-8').hex()}",
            f"channel={channel}",
        ]
        
        # HW mode based on band
        if band == "5ghz":
            config_lines.append("hw_mode=a")
        else:  # 2.4ghz
            config_lines.append("hw_mode=g")
        
        # Hidden SSID
        if hidden:
            config_lines.append("ignore_broadcast_ssid=1")
        
        if encryption not in SECURITY_LINES:
            raise HostapdError(f"Unsupported encryption: {encryption}")
        if encryption != "open" and not password:
            raise HostapdError(f"Password required for {encryption} encryption")
        config_lines.extend(SECURITY_LINES[encryption])
        if encryption != "open":
            config_lines.append(f"wpa_passphrase={password}")

        if layout is None:
            try:
                layout = channel_layouts(band, channel, channel_width)[0]
            except ValueError as e:
                raise HostapdError(str(e)) from e
        config_lines.extend([
            f"country_code={country_code}",
            "ieee80211d=1",  # Advertise country code and apply regulatory domain
            *mode_lines(band, channel_width, wifi_generation, layout, encryption),
            "wmm_enabled=1",  # WMM/QoS
        ])

        # Enable 802.11h (DFS/TPC) on 5 GHz where regulatory rules require it
        if band == "5ghz":
            config_lines.append("ieee80211h=1")
        
        return "\n".join(config_lines) + "\n"
    
    def start(
        self,
        net_id: str,
        interface: str,
        ssid: str,
        channel: int,
        encryption: str,
        password: str | None,
        hidden: bool,
        band: str,
        country_code: str = "IT",
        channel_width: int = 20,
        wifi_generation: int = 4,
        layout: ChannelLayout | None = None,
    ) -> HostapdInstance:
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
            country_code: ISO 3166-1 alpha-2 country code
            channel_width, wifi_generation, layout: see :meth:`_generate_config`

        Returns:
            Dictionary with hostapd instance info
            
        Raises:
            HostapdError: If hostapd fails to start or already running
        """
        if net_id in self._instances:
            raise HostapdError(f"hostapd cleanup required for {net_id}")

        try:
            config_content = self._generate_config(
                interface, ssid, channel, encryption, password, hidden, band, country_code,
                channel_width, wifi_generation, layout,
            )
            instance_dir = tempfile.mkdtemp(prefix="ap-", dir=HOSTAPD_CONFIG_DIR)
            control_dir = os.path.join(instance_dir, "ctrl")
            config_file = os.path.join(instance_dir, "hostapd.conf")
            instance: HostapdInstance = {
                "interface": interface,
                "config_file": config_file,
                "control_dir": control_dir,
                "ssid": ssid,
                "process": None,
            }
            self._instances[net_id] = instance
            with open(config_file, "w", encoding="utf-8") as f:
                f.write(config_content + f"ctrl_interface={control_dir}\n")

            logger.info(f"Preparing interface {interface} for AP mode")
            try:
                execute_command(["ip", "link", "set", interface, "down"])
                execute_iw(["dev", interface, "set", "type", "managed"])
                execute_command(["ip", "addr", "flush", "dev", interface])
            except CommandTimeout as e:
                raise HostapdRadioFailure(f"Radio preparation timed out on {interface}") from e

            process = start_foreground(["hostapd", "-d", config_file], classify_output=_classify_output)
            instance["process"] = process
            sub_channels = layout.channels if layout is not None else (channel,)
            dfs = band == "5ghz" and any(52 <= c <= 144 for c in sub_channels)
            timeout = DFS_READY_TIMEOUT if dfs else AP_READY_TIMEOUT
            self._wait_until_ready(process, interface, control_dir, timeout)
            logger.info(f"hostapd started for {net_id} on {interface}")
            return instance

        except (CommandError, OSError) as e:
            raise HostapdError(f"Failed to start hostapd for {net_id}: {e}") from e

    @staticmethod
    def _check_process(process: ForegroundProcess, interface: str) -> None:
        code = process.poll()
        if code == -signal.SIGSEGV:
            raise HostapdSegfault(f"hostapd segfault on {interface}")
        if code is not None:
            if _TRANSIENT_INIT_EVENTS <= set(process.output_events(exited=True)):
                raise HostapdInitFailure(
                    f"hostapd exited with code {code} on {interface}: beacon setup failed",
                )
            raise HostapdError(f"hostapd exited with code {code} on {interface}")

    def _wait_until_ready(
        self, process: ForegroundProcess, interface: str, control_dir: str, timeout: float,
    ) -> None:
        """Wait for state ENABLED on *interface*.

        The SSID is not compared: hostapd escapes it in ``ssid[0]`` (``\\xNN``, ``\\"``),
        and the control directory is private to this instance, so state and
        interface identify the AP.
        """
        started = time.monotonic()
        deadline = started + bounded_timeout(timeout)
        state = "unavailable"
        last_state = state
        socket_seen = False
        probe = "not_attempted"
        exit_code = None

        def check_process() -> None:
            nonlocal exit_code
            try:
                self._check_process(process, interface)
            except HostapdError:
                exit_code = process.poll()
                raise

        try:
            while (remaining := deadline - time.monotonic()) > 0:
                check_process()
                fields: dict[str, str] = {}
                if os.path.exists(os.path.join(control_dir, interface)):
                    socket_seen = True
                    command = ["hostapd_cli", "-p", control_dir, "-i", interface, "status"]
                    try:
                        status = execute_command(
                            command, check=False, timeout=min(remaining, STATUS_PROBE_TIMEOUT),
                            exact_timeout=True,
                        )
                    except CommandTimeout as e:
                        probe = "timed_out"
                        check_process()
                        if remaining <= STATUS_PROBE_TIMEOUT:
                            raise HostapdRadioFailure(f"AP status timed out on {interface}") from e
                        continue
                    except CommandError:
                        probe = "command_error"
                        check_process()
                        raise
                    fields = dict(line.split("=", 1) for line in status.splitlines() if "=" in line)
                    reported = fields.get("state")
                    probe = "state_received" if reported in _STARTUP_STATES else "no_known_state"
                    if reported is not None and reported in _STARTUP_STATES:
                        last_state = reported
                    check_process()
                state = fields.get("state", "unavailable")
                if (
                    time.monotonic() < deadline
                    and state == "ENABLED"
                    and fields.get("bss[0]") == interface
                ):
                    return
                if state == "DISABLED":
                    break
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
            if state == "DISABLED":
                # hostapd exits right after reporting DISABLED: give it a moment so
                # the failure is classified from its exit and output, whichever of
                # the two the probe happened to see first (HAP-2).
                settle = time.monotonic() + DISABLED_SETTLE
                while process.poll() is None and time.monotonic() < settle:
                    time.sleep(0.05)
            check_process()
            if state == "DISABLED" and _TRANSIENT_INIT_EVENTS <= set(process.output_events()):
                raise HostapdInitFailure(f"hostapd disabled the AP on {interface}: beacon setup failed")
            raise HostapdRadioFailure(f"AP not ready on {interface} (hostapd state: {last_state})")
        except (HostapdError, CommandError) as exc:
            elapsed = time.monotonic() - started
            logger.warning(
                "hostapd startup failure on %s elapsed=%.3fs budget=%.3fs "
                "socket_seen=%s last_state=%s last_probe=%s error=%s exit_code=%s events=%s",
                interface, elapsed, deadline - started, socket_seen, last_state, probe,
                type(exc).__name__, exit_code,
                ",".join(process.output_events(exited=exit_code is not None)) or "none",
            )
            raise
    
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
            config_file = instance["config_file"]
            interface = instance["interface"]
            process = instance["process"]

            if process is not None:
                process.stop()
                instance["process"] = None

            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info(f"Removed hostapd config {config_file}")

            control_dir = instance["control_dir"]
            for path, remove in (
                (os.path.join(control_dir, interface), os.unlink),
                (control_dir, os.rmdir),
                (os.path.dirname(control_dir), os.rmdir),
            ):
                try:
                    remove(path)
                except FileNotFoundError:
                    pass

            if interface_present(interface):
                # Leave the interface down until the next network starts.
                execute_command(["ip", "link", "set", interface, "down"])
                execute_command(["iw", "dev", interface, "set", "type", "managed"])
                execute_command(["ip", "addr", "flush", "dev", interface])
                logger.info(f"Reset interface {interface} to managed mode, down")
            else:
                # The adapter disconnected: there is nothing to reset, and a
                # re-enumerated netdev starts down and managed with no address.
                logger.warning("Interface %s is gone; skipping interface reset", interface)

            del self._instances[net_id]
            logger.info(f"hostapd stopped for {net_id}")

        except (CommandError, OSError) as e:
            logger.error(f"Error stopping hostapd for {net_id}: {e}")
            raise HostapdError(f"Failed to stop hostapd for {net_id}: {e}") from e
    
    def is_running(self, net_id: str) -> bool:
        """Check if hostapd is running for a network."""
        if net_id not in self._instances:
            return False
        
        process = self._instances[net_id]["process"]
        return process is not None and process.poll() is None

    def is_enabled(self, net_id: str) -> bool:
        """Check the private control socket with a short, bounded timeout."""
        instance = self._instances.get(net_id)
        if instance is None or not self.is_running(net_id):
            return False
        interface = instance["interface"]
        try:
            status = execute_command(
                ["hostapd_cli", "-p", instance["control_dir"], "-i", interface, "status"],
                check=False, timeout=1.0, exact_timeout=True,
            )
        except CommandError:
            return False
        fields = dict(line.split("=", 1) for line in status.splitlines() if "=" in line)
        # The control socket is private to this instance, so state and interface
        # are enough; hostapd escapes the SSID in this output.
        return fields.get("state") == "ENABLED" and fields.get("bss[0]") == interface
    
    def status(self) -> dict:
        """Return status of all hostapd instances."""
        instances = []
        for net_id, data in self._instances.copy().items():
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "ssid": data.get("ssid"),
                "pid_file": None,
                "running": (process := data["process"]) is not None and process.poll() is None,
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

