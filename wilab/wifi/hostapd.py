"""hostapd configuration generation and process management for WiFi AP mode."""

import logging
import os
import re
import signal
import tempfile
import time
from collections.abc import Callable
from functools import partial
from typing import NotRequired, TypedDict

from ..network.commands import (
    CommandError,
    CommandTimeout,
    ForegroundProcess,
    bounded_timeout,
    execute_command,
    execute_iw,
    start_foreground,
)
from ..paths import HOSTAPD_RUNTIME_DIR, make_private_dir
from .channels import ChannelLayout, channel_layouts
from .failures import FailureKind
from .hostapd_ctrl import ControlError, HostapdMonitor, parse_fields
from .interface import interface_present

logger = logging.getLogger(__name__)

HOSTAPD_CONFIG_DIR = HOSTAPD_RUNTIME_DIR   # configuration and control sockets (STAB-2)
AP_READY_TIMEOUT = 10.0
# hostapd_cli waits for a reply that never comes if hostapd exits meanwhile,
# so each status probe is short and the process is checked between probes.
STATUS_PROBE_TIMEOUT = 1.0
_TRANSIENT_INIT_EVENTS = frozenset({"beacon_failed", "interface_init_failed"})
# Seconds to wait for hostapd to exit after it reports DISABLED (HAP-2).
DISABLED_SETTLE = 0.5
DFS_READY_TIMEOUT = 75.0
# Hold a persistent control connection per running AP (PERF-4); the unit tests
# turn it off where hostapd is a fake without a control socket.
MONITOR_CONTROL = True
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

    # hostapd refused or exited without a radio symptom: the request cannot work as is.
    kind = FailureKind.CONFIGURATION


class HostapdCancelled(HostapdError):
    """The start was cancelled (release or stop of the client): not a failure (ARCH-10)."""


class HostapdRadioFailure(HostapdError):
    """Radio startup failed without a confirmed configuration error."""

    kind = FailureKind.TRANSIENT_RADIO


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
    monitor: NotRequired[HostapdMonitor | None]


DEBUG_TAIL_LINES = 400      # `hostapd -d` lines kept per start when hostapd_debug_dir is set
LOG_TAIL_LINES = 80         # kept always, so a failure can be reported without hostapd_debug_dir (HAP-8)
LOGGED_TAIL_LINES = 40      # written to the journal when hostapd fails or dies
# Lines of `hostapd -d` that may carry key material or passwords: never logged or saved.
_SECRET_OUTPUT = re.compile(r"psk|pmk|ptk|gtk|igtk|kck|kek|passphrase|password|key", re.IGNORECASE)
DEBUG_MAX_FILES = 100       # failure reports kept in hostapd_debug_dir (oldest removed)
_SECRET_KEYS = ("wpa_passphrase=", "sae_password=", "wpa_psk=")


def redacted_tail(process: ForegroundProcess, *, exited: bool = False) -> list[str]:
    """The kept output lines of hostapd without lines that may contain secrets."""
    return [line for line in process.output_tail(exited=exited) if not _SECRET_OUTPUT.search(line)]


def log_tail(interface: str, what: str, process: ForegroundProcess) -> None:
    """Write the last hostapd output lines to the journal (HAP-8).

    The lines just before a crash are what a driver developer asks for; only
    the twelve classified labels were kept before.
    """
    try:
        lines = redacted_tail(process, exited=True)[-LOGGED_TAIL_LINES:]
        if lines:
            logger.warning(
                "hostapd on %s %s (exit code %s); last output lines:\n%s",
                interface, what, process.poll(), "\n".join(lines),
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics never change how a start ends
        logger.debug("Cannot log the hostapd output of %s: %s", interface, exc)


def save_failure(
    directory: str, interface: str, exc: BaseException, process: ForegroundProcess, config: str,
) -> str | None:
    """Write the configuration (no secrets) and last `hostapd -d` lines of a failed start.

    Diagnostics only (`hostapd_debug_dir`): a failure here is logged and ignored.
    """
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = os.path.join(directory, f"{stamp}-{interface}-{type(exc).__name__}.log")
    config_lines = [
        line.split("=", 1)[0] + "=<removed>" if line.startswith(_SECRET_KEYS) else line
        for line in config.splitlines()
    ]
    try:
        os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"interface: {interface}\nerror: {type(exc).__name__}: {exc}\n")
            f.write(f"exit code: {process.poll()}\n\n--- hostapd.conf ---\n")
            f.write("\n".join(config_lines))
            f.write("\n\n--- hostapd -d (last lines) ---\n")
            f.write("\n".join(redacted_tail(process, exited=True)) + "\n")
        reports = sorted(
            os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".log")
        )
        for old in reports[:-DEBUG_MAX_FILES]:
            os.remove(old)
    except OSError as error:
        logger.warning("Cannot save hostapd failure report in %s: %s", directory, error)
        return None
    logger.info("hostapd failure report saved: %s", path)
    return path


class HostapdManager:
    """Manages hostapd processes for WiFi AP networks."""
    
    def __init__(
        self, *, debug_dir: str | None = None, on_change: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize hostapd manager.

        Args:
            debug_dir: `hostapd_debug_dir`: where to save the `hostapd -d` output and
                configuration of every start that fails (None: not saved).
            on_change: called with the network id when its control connection is
                lost or hostapd reports AP-DISABLED (the watchdog wakes up, PERF-4).
        """
        self._instances: dict[str, HostapdInstance] = {}
        self._debug_dir = debug_dir
        self.on_change = on_change
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """Ensure the config directory exists."""
        try:
            make_private_dir(HOSTAPD_CONFIG_DIR)
        except OSError as e:
            logger.warning("Could not create hostapd dirs: %s", e)
    
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
        cancelled: Callable[[], bool] | None = None,
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

            logger.info("Preparing interface %s for AP mode", interface)
            try:
                execute_command(["ip", "link", "set", interface, "down"])
                execute_iw(["dev", interface, "set", "type", "managed"])
                execute_command(["ip", "addr", "flush", "dev", interface])
            except CommandTimeout as e:
                raise HostapdRadioFailure(f"Radio preparation timed out on {interface}") from e

            process = start_foreground(
                ["hostapd", "-d", config_file], classify_output=_classify_output,
                keep_lines=DEBUG_TAIL_LINES if self._debug_dir else LOG_TAIL_LINES,
            )
            instance["process"] = process
            sub_channels = layout.channels if layout is not None else (channel,)
            dfs = band == "5ghz" and any(52 <= c <= 144 for c in sub_channels)
            timeout = DFS_READY_TIMEOUT if dfs else AP_READY_TIMEOUT
            try:
                self._wait_until_ready(process, interface, control_dir, timeout, cancelled)
            except HostapdCancelled:
                raise   # what the client asked for: no failure report
            except (HostapdError, CommandError) as exc:
                log_tail(interface, f"failed to start ({type(exc).__name__})", process)
                if self._debug_dir:
                    save_failure(self._debug_dir, interface, exc, process, config_content)
                raise
            if MONITOR_CONTROL:
                monitor = HostapdMonitor(
                    os.path.join(control_dir, interface), instance_dir, interface,
                    on_change=partial(self._changed, net_id),
                )
                instance["monitor"] = monitor
                monitor.start()
            logger.info("hostapd started for %s on %s", net_id, interface)
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
        cancelled: Callable[[], bool] | None = None,
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
                if cancelled is not None and cancelled():
                    # The client released the reservation or stopped the network
                    # during the start (up to 75 s on DFS): stop waiting.
                    raise HostapdCancelled(f"AP start on {interface} cancelled")
                check_process()
                fields: dict[str, str] = {}
                if os.path.exists(os.path.join(control_dir, interface)):
                    socket_seen = True
                    command = ["hostapd_cli", "-p", control_dir, "-i", interface, "status"]
                    try:
                        status = execute_command(
                            command, check=False, timeout=min(remaining, STATUS_PROBE_TIMEOUT),
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
        except HostapdCancelled:
            raise
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
            logger.warning("No hostapd running for %s", net_id)
            return
        
        try:
            instance = self._instances[net_id]
            config_file = instance["config_file"]
            interface = instance["interface"]
            process = instance["process"]

            # First, so a hostapd going away is not reported as a lost connection,
            # and its client sockets leave the instance directory before rmdir.
            monitor = instance.get("monitor")
            if monitor is not None:
                monitor.close()
                instance["monitor"] = None

            if process is not None:
                process.stop()
                instance["process"] = None

            # Remove config file
            if os.path.exists(config_file):
                os.remove(config_file)
                logger.info("Removed hostapd config %s", config_file)

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
                logger.info("Reset interface %s to managed mode, down", interface)
            else:
                # The adapter disconnected: there is nothing to reset, and a
                # re-enumerated netdev starts down and managed with no address.
                logger.warning("Interface %s is gone; skipping interface reset", interface)

            del self._instances[net_id]
            logger.info("hostapd stopped for %s", net_id)

        except (CommandError, OSError) as e:
            logger.warning("Error stopping hostapd for %s: %s", net_id, e)
            raise HostapdError(f"Failed to stop hostapd for {net_id}: {e}") from e
    
    def is_tracked(self, net_id: str) -> bool:
        """True while resources of this network still need a stop() (ARCH-8)."""
        return net_id in self._instances

    def report_exit(self, net_id: str) -> None:
        """Log (and with hostapd_debug_dir save) the output of a hostapd that died (HAP-8).

        Called by the watchdog when it finds hostapd gone on an active network,
        before the restore replaces the process. Never raises.
        """
        instance = self._instances.get(net_id)
        process = instance["process"] if instance is not None else None
        if instance is None or process is None or process.poll() is None:
            return
        try:
            log_tail(instance["interface"], "died on an active network", process)
            if self._debug_dir:
                try:
                    with open(instance["config_file"], encoding="utf-8") as f:
                        config = f.read()
                except OSError:
                    config = ""
                save_failure(
                    self._debug_dir, instance["interface"],
                    HostapdError(f"hostapd exited with code {process.poll()} on an active network"),
                    process, config,
                )
        except Exception as exc:  # noqa: BLE001 - diagnostics must never break the watchdog
            logger.warning("Cannot report the hostapd exit on %s: %s", net_id, exc)

    def is_running(self, net_id: str) -> bool:
        """Check if hostapd is running for a network."""
        if net_id not in self._instances:
            return False
        
        process = self._instances[net_id]["process"]
        return process is not None and process.poll() is None

    def is_enabled(self, net_id: str) -> bool | None:
        """Check the private control socket with a short, bounded timeout.

        True or False is hostapd's answer; None when hostapd_cli did not answer
        in time (a loaded host, not necessarily a broken AP: WD-10).
        """
        instance = self._instances.get(net_id)
        if instance is None or not self.is_running(net_id):
            return False
        interface = instance["interface"]
        monitor = instance.get("monitor")
        fields: dict[str, str] | None = None
        if monitor is not None and monitor.connected:
            # The persistent connection: no process per probe (PERF-4).
            try:
                fields = monitor.status(STATUS_PROBE_TIMEOUT)
            except ControlError:
                fields = None   # lost meanwhile: the monitor reconnects, this probe falls back
        if fields is None:
            try:
                status = execute_command(
                    ["hostapd_cli", "-p", instance["control_dir"], "-i", interface, "status"],
                    check=False, timeout=STATUS_PROBE_TIMEOUT,
                )
            except CommandTimeout:
                return None
            except CommandError:
                return False
            fields = parse_fields(status)
        # The control socket is private to this instance, so state and interface
        # are enough; hostapd escapes the SSID in this output.
        return fields.get("state") == "ENABLED" and fields.get("bss[0]") == interface
    
    def stations(self, net_id: str) -> set[str] | None:
        """Associated stations from the control connection; None when it is not connected."""
        instance = self._instances.get(net_id)
        monitor = instance.get("monitor") if instance is not None else None
        return monitor.stations() if monitor is not None else None

    def control_connected(self, net_id: str) -> bool:
        instance = self._instances.get(net_id)
        monitor = instance.get("monitor") if instance is not None else None
        return monitor is not None and monitor.connected

    def _changed(self, net_id: str) -> None:
        if self.on_change is not None:
            self.on_change(net_id)

    def status(self) -> dict:
        """Return status of all hostapd instances."""
        instances = []
        for net_id, data in self._instances.copy().items():
            instances.append({
                "net_id": net_id,
                "interface": data.get("interface"),
                "ssid": data.get("ssid"),
                "running": (process := data["process"]) is not None and process.poll() is None,
            })
        return {
            "running": any(inst["running"] for inst in instances),
            "instances": instances,
        }
    