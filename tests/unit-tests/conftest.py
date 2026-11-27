# pytest configuration and shared fixtures
import os
import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from wilab.config import AppConfig, load_config
from wilab.devices import Device, DeviceRegistry
from wilab.models import NetworkCreateRequest
from wilab.wifi.active import ActiveNetwork

TEST_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'test.config.yaml')

# `iw phy phy1 info` read on the lab machine (MediaTek mt7921u, 2026-11-25).
MOCK_PHY_INFO = (Path(__file__).parent / "data" / "iw_phy_info_mt7921u.txt").read_text()


# Every setting of config.yaml is required (only hostapd_debug_dir and antennas
# may be omitted): tests that build a config start from these values.
REQUIRED_SETTINGS = {
    "api_port": 8080, "captive_portal_port": 8081, "max_timeout": 86400, "min_timeout": 60,
    "allow_unlimited_reservation": False, "upstream_interface": "auto", "country_code": "IT",
    "protected_commands_password": None, "internet_enabled_by_default": True, "cors_origins": None,
}
REQUIRED_YAML = "".join(
    f"{key}: {'null' if value is None else str(value).lower() if isinstance(value, bool) else value}\n"
    for key, value in REQUIRED_SETTINGS.items()
)


def make_config(**settings) -> AppConfig:
    """An AppConfig with every required setting, overridden by *settings*."""
    return AppConfig(**{**REQUIRED_SETTINGS, **settings})


# ActiveNetwork fields that are not request settings (ARCH-3).
_NETWORK_FIELDS = {"subnet", "internet_enabled", "tx_power_level", "captive_portal_url",
                   "expires_at", "deadline", "active"}


def active_network(interface: str, **fields: Any) -> ActiveNetwork:
    """An ActiveNetwork for `manager.active`, as start_network stores it.

    *fields* are ActiveNetwork fields or request settings (ssid, channel, ...);
    the request is built without validation, like a stored one never re-checked.
    """
    settings: dict[str, Any] = {
        "ssid": "test", "channel": 6, "password": None, "encryption": "open", "band": "2.4ghz",
        "hidden": False, "internet_enabled": None, "captive_portal": False, "tx_power_level": 4,
        "channel_width": 20, "wifi_generation": 4,
    }
    own = {key: fields.pop(key) for key in list(fields) if key in _NETWORK_FIELDS}
    settings.update(fields)
    if "tx_power_level" in own:
        settings["tx_power_level"] = own["tx_power_level"]   # the create's level too
    request = NetworkCreateRequest.model_construct(**settings)
    own.setdefault("subnet", None)
    own.setdefault("internet_enabled", False)
    own.setdefault("tx_power_level", request.tx_power_level)
    return ActiveNetwork(interface=interface, request=request, **own)


def _configured_devices_only(config: AppConfig) -> list[Device]:
    """Start with every enabled configured interface managed (tests must not probe real hardware)."""
    return [
        Device(interface=label.interface, display_name=label.display_name,
               show_dfs_channels=label.show_dfs_channels)
        for label in config.antennas if not label.disable
    ]


def configured_devices(config: AppConfig | None = None) -> DeviceRegistry:
    """A registry with every enabled antenna of *config* (default: the test config).

    The devices an app built from that config starts with (ARCH-4).
    """
    return DeviceRegistry(_configured_devices_only(config or load_config()))


def registry_of(*interfaces: str) -> DeviceRegistry:
    """A registry with one device per interface, in this order (display name = interface)."""
    return DeviceRegistry(Device(interface=interface, display_name=interface) for interface in interfaces)


@pytest.fixture(scope="session")
def config():
    """Load test config once per test session."""
    return load_config(TEST_CONFIG_PATH)


@pytest.fixture(autouse=True)
def _test_config_env(monkeypatch):
    """Point load_config() to the test config; never touch the host from tests."""
    from wilab.api import context as context_module
    from wilab.api import discovery as discovery_service
    from wilab.wifi import discovery
    monkeypatch.setattr(context_module, '_initial_devices', _configured_devices_only)
    # The discovery service runs with every app; it must not probe real hardware.
    monkeypatch.setattr(discovery, 'discover_radios', lambda **kwargs: [])
    monkeypatch.setattr(discovery, 'default_route_interfaces', set)
    # Never write host network manager rules under /run from tests.
    monkeypatch.setattr(discovery_service, 'exclude_from_host_managers', lambda interfaces: None)
    monkeypatch.setattr(discovery_service, 'warn_wpa_supplicant', lambda interfaces: None)
    # Startup cleanup kills Wi-Lab's hostapd/dnsmasq and empties /tmp/wilab-*: on the
    # Wi-Lab machine that would hit the real service (STAB-4). Never run it from tests.
    monkeypatch.setattr(context_module, 'cleanup_runtime', lambda: None)
    monkeypatch.setattr(context_module, 'remove_stale_guards', lambda: None)
    monkeypatch.setattr(discovery_service, 'reset_interface', lambda interface: None)
    monkeypatch.setenv('CONFIG_PATH', TEST_CONFIG_PATH)


@pytest.fixture
def app():
    """The application built from the test config; its context starts with a TestClient."""
    from wilab.api import create_app
    return create_app()


@pytest.fixture
def context(app):
    """The AppContext of `app` (ARCH-5): its config, managers and discovery."""
    return app.state.context


@pytest.fixture(autouse=True)
def _stop_background_threads(monkeypatch):
    """Stop the loops of every NetworkManager a test created.

    A started manager runs an expiry loop, a watchdog per antenna and a re-probe
    loop (AppContext.start, or a test starting them itself). Left running they outlive the
    test's mocks (the next tick would run the real host commands) and add up to
    about 400 threads by the end of a run.
    """
    from wilab.wifi.manager import NetworkManager
    created = []
    original_init = NetworkManager.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(NetworkManager, "__init__", tracking_init)
    yield
    for manager in created:
        manager.watchdog.stopping.set()
        manager.recovery.stop()


@pytest.fixture(autouse=True)
def mock_network_operations(monkeypatch, tmp_path):
    """Auto-mock network operations that require root privileges."""
    from wilab.network import captive, commands, dhcp, nat, subnet
    from wilab.wifi import channels, clients, hostapd, manager, startup, txpower

    # No control connection to a hostapd that only the tests' fakes play (PERF-4):
    # test_hostapd_ctrl.py turns it on with its own fake hostapd.
    monkeypatch.setattr(hostapd, "MONITOR_CONTROL", False)

    # Mock execute_ip to avoid RTNETLINK errors (requires root)
    def mock_execute_ip(args):
        # Return empty string for most commands, simulate success
        cmd = args[0] if args else ""
        if cmd == "addr" and "show" in args:
            # Simulate interface exists
            return "inet 192.168.120.1/24\nstate UP"
        return ""
    
    # Realistic iw phy channels output with 2.4 GHz, 5 GHz, No IR, and disabled channels
    _MOCK_PHY_CHANNELS = """\
Band 1:
        * 2412 MHz [1] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2417 MHz [2] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2422 MHz [3] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2427 MHz [4] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2432 MHz [5] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2437 MHz [6] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2442 MHz [7] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2447 MHz [8] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2452 MHz [9] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+
        * 2457 MHz [10] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2462 MHz [11] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2467 MHz [12] 
          Maximum TX power: 20.0 dBm
          No IR
          Channel widths: 20MHz HT40-
        * 2472 MHz [13] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40-
        * 2484 MHz [14] (disabled)
Band 2:
        * 5180 MHz [36] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5200 MHz [40] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5220 MHz [44] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5240 MHz [48] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5260 MHz [52] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5280 MHz [56] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5300 MHz [60] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5320 MHz [64] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5500 MHz [100] 
          Maximum TX power: 26.0 dBm
          Radar detection
          Channel widths: 20MHz HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms
        * 5745 MHz [149] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5765 MHz [153] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5785 MHz [157] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5805 MHz [161] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5825 MHz [165] 
          Maximum TX power: 13.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 5845 MHz [169] (disabled)
        * 5955 MHz [1] 
          Maximum TX power: 12.0 dBm
          Channel widths: 20MHz HT40- HT40+ VHT80
        * 6695 MHz [149] (disabled)
"""

    # Mock execute_iw to avoid needing real WiFi hardware
    def mock_execute_iw(args):
        # Return mock wiphy info
        if not args:
            return ""
        
        # Handle: execute_iw(["reg", "set", ...])
        if args[0] == "reg":
            return ""

        # Handle: execute_iw([interface, "info"])
        if len(args) >= 2 and args[1] == "info" and not args[0].startswith("phy"):
            # Return wiphy info for interface
            return f"Interface {args[0]}\nwiphy 0\ntxpower 20.00 dBm"
        
        # Handle: execute_iw(["phy0", "info"]): a real mt7921u reading (HAP-10, HAP-11)
        elif args[0].startswith("phy") and args[1:] == ["info"]:
            return MOCK_PHY_INFO

        # Handle: execute_iw(["phy0", "channels"])
        elif args[0].startswith("phy"):
            return _MOCK_PHY_CHANNELS
        
        # Handle: execute_iw(["dev", interface, "station", "dump"])
        elif "station" in args:
            return ""
        
        return ""
    
    # Mock execute_command for network operations
    def mock_execute_command(cmd, **kwargs):
        if cmd[:4] == ["ip", "route", "show", "default"]:
            return "default via 192.0.2.1 dev eth0"
        if cmd[0] == "iptables" and "-C" in cmd:
            raise commands.CommandError("Rule not found", returncode=1)
        if cmd[0] == "ip":
            return mock_execute_ip(cmd[1:])
        # For other commands, return empty string
        return ""
    
    # Patch in manager module (where they're imported)
    monkeypatch.setattr(manager, "validate_interface_exists", lambda iface: None)
    # Test interfaces are not in /sys/class/net: treat every adapter as present.
    from wilab.wifi import recovery, watchdog
    for module in (manager, startup, hostapd, recovery, watchdog):
        monkeypatch.setattr(module, "interface_present", lambda iface: True)
    monkeypatch.setattr(manager, "execute_iw", mock_execute_iw)
    monkeypatch.setattr(manager, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(startup, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(txpower, "execute_iw", mock_execute_iw)
    monkeypatch.setattr(clients, "execute_iw", mock_execute_iw)
    monkeypatch.setattr(clients, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(hostapd, "execute_command", mock_execute_command)
    monkeypatch.setattr(hostapd, "execute_iw", mock_execute_iw)
    def reject_real_hostapd(*args, **kwargs) -> None:
        raise commands.CommandError("hostapd must be mocked in tests")

    monkeypatch.setattr(hostapd, "HOSTAPD_CONFIG_DIR", str(tmp_path / "hostapd"))
    monkeypatch.setattr(hostapd, "start_foreground", reject_real_hostapd)
    monkeypatch.setattr(dhcp, "execute_command", mock_execute_command)
    # dnsmasq is a foreground child (ARCH-6): never launch the real one from tests.
    def reject_real_dnsmasq(*args, **kwargs) -> None:
        raise commands.CommandError("dnsmasq must be mocked in tests")

    monkeypatch.setattr(dhcp, "DNSMASQ_CONFIG_DIR", str(tmp_path / "dnsmasq"))
    monkeypatch.setattr(dhcp, "start_foreground", reject_real_dnsmasq)
    monkeypatch.setattr(nat, "execute_command", mock_execute_command)
    from wilab.network import host_guard
    monkeypatch.setattr(host_guard, "execute_command", mock_execute_command)  # ip6tables
    monkeypatch.setattr(subnet, "execute_command", lambda cmd, **kwargs: "[]")
    # /status reads the upstream link with `ip -j addr show`: a healthy uplink on every
    # host, instead of whatever the machine running the tests has as "eth0".
    from wilab import health
    monkeypatch.setattr(health, "execute_command", lambda cmd, **kwargs: (
        '[{"operstate": "UP", "flags": ["UP", "LOWER_UP"], "addr_info": [{"family": "inet"}]}]'
    ))

    class _UnboundPortalServer:
        """Stands in for the portal web server, which would bind the AP gateway."""

        def serve_forever(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    monkeypatch.setattr(captive.CaptivePortal, "_open_server", lambda self: _UnboundPortalServer())
    
    # Patch commands
    monkeypatch.setattr(commands, "execute_ip", mock_execute_ip)
    monkeypatch.setattr(commands, "execute_iw", mock_execute_iw)
    monkeypatch.setattr(commands, "execute_tc", lambda args, **kwargs: "")
    monkeypatch.setattr(commands, "execute_command", mock_execute_command)

    # Patch in channels module
    monkeypatch.setattr(channels, "execute_iw", mock_execute_iw)


@pytest.fixture
def clean_manager(config, monkeypatch):
    """Create a fresh NetworkManager with no active networks."""
    from wilab.wifi.manager import NetworkManager
    mgr = NetworkManager(config, configured_devices(config))
    
    # Mock DHCP to avoid system calls
    def mock_dhcp_start(*args, **kwargs):
        return {
            'gateway': '192.168.10.1',
            'dhcp_range': '192.168.10.10,192.168.10.250',
            'config_file': '/tmp/mock-dnsmasq.conf'
        }
    
    def mock_dhcp_stop(*args, **kwargs):
        pass
    
    monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
    monkeypatch.setattr(mgr.dhcp_server, 'stop', mock_dhcp_stop)
    
    return mgr


_RADIO_FIELDS = ("band", "channel", "channel_width", "wifi_generation", "tx_power_level")


def network_body(**flat):
    """The sectioned create body (radio, wifi, internet, captive_portal) from flat fields.

    Unknown keys stay at the top level, so invalid bodies can still be built.
    """
    body: dict = {}
    radio = {key: flat.pop(key) for key in _RADIO_FIELDS if key in flat}
    security = {key: flat.pop(key) for key in ("encryption", "password") if key in flat}
    wifi = {key: flat.pop(key) for key in ("ssid", "hidden") if key in flat}
    if security:
        wifi["security"] = security
    if radio:
        body["radio"] = radio
    if wifi:
        body["wifi"] = wifi
    if "internet_enabled" in flat:
        body["internet"] = {"enabled": flat.pop("internet_enabled")}
    if "captive_portal" in flat:
        body["captive_portal"] = {"enabled": flat.pop("captive_portal")}
    body.update(flat)
    return body


@pytest.fixture(autouse=True)
def _fresh_health_checks(monkeypatch):
    """Tests change state and read /status at once: recompute the checks on every read."""
    from wilab import health
    monkeypatch.setattr(health, "MAX_AGE", -1.0)


def create_network(client, headers, url, body, timeout: float = 5.0):
    """POST a create and poll GET .../network until the start ends (REV-16).

    *url* is the network URL (`/api/v2/reservations/{id}/network`). Returns
    `(created, outcome)`: the POST answer, and the first GET answer that is not
    `starting` (the network, `start_failed`, or 404 with the reason). A POST
    refused at once (422, 409, 404) is returned as both.
    """
    import time

    created = client.post(url, headers=headers, json=body)
    if created.status_code != 202:
        return created, created
    end = time.monotonic() + timeout
    while True:
        outcome = client.get(url, headers=headers)
        if outcome.status_code != 200 or outcome.json()["runtime_state"] != "starting":
            return created, outcome
        if time.monotonic() > end:
            raise AssertionError("the start did not end")
        time.sleep(0.01)
