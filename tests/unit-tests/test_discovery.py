import logging
import time
from unittest.mock import Mock

import pytest
from conftest import REQUIRED_YAML, make_config
from fastapi.testclient import TestClient

from wilab import config as config_module
from wilab.api import create_app
from wilab.config import NetworkEntry, load_config, resolve_networks
from wilab.wifi import discovery
from wilab.wifi.discovery import DiscoveredRadio

IW_DEV = """\
phy#1
\tInterface wlx001122334455
\t\tifindex 5
\t\ttype managed
phy#0
\tInterface wlan0
\t\ttype managed
phy#2
\tInterface wlan-sta
\t\ttype managed
"""

PHY_INFO = {
    "phy0": "Wiphy phy0\n\tSupported interface modes:\n\t\t * managed\n\t\t * AP\n\t\t * monitor\n\tBand 1:\n",
    "phy1": "Wiphy phy1\n\tSupported interface modes:\n\t\t * managed\n\t\t * AP\n\tBand 1:\n",
    "phy2": "Wiphy phy2\n\tSupported interface modes:\n\t\t * managed\n\t\t * AP/VLAN\n\tBand 1:\n\t\t * AP\n",
}


# Captured at import, before conftest stubs discovery for every test.
_REAL_DISCOVER_RADIOS = discovery.discover_radios


@pytest.fixture
def real_discovery(monkeypatch):
    monkeypatch.setattr(discovery, "discover_radios", _REAL_DISCOVER_RADIOS)


def _sysfs(tmp_path, interface, function_path, subsystem):
    function = tmp_path / "devices" / function_path
    function.mkdir(parents=True)
    bus = tmp_path / "bus" / subsystem
    bus.mkdir(parents=True, exist_ok=True)
    (function / "subsystem").symlink_to(bus)
    net = tmp_path / "class" / "net" / interface
    net.mkdir(parents=True)
    (net / "device").symlink_to(function)
    (net / "ifindex").write_text("5\n")


def _udev_properties(cmd, **kwargs):
    interface = cmd[-1].split("/")[-1]
    return f"INTERFACE={interface}\nIFINDEX=5\nUSEC_INITIALIZED=42\n"


def test_discover_radios_keeps_ap_capable_and_detects_usb(monkeypatch, tmp_path, real_discovery):
    monkeypatch.setattr(discovery, "SYS_CLASS_NET", tmp_path / "class" / "net")
    _sysfs(tmp_path, "wlx001122334455", "pci0/usb2/2-1/2-1:1.0", "usb")
    _sysfs(tmp_path, "wlan0", "pci0/0000:03:00.0", "pci")

    def fake_iw(args):
        return IW_DEV if args == ["dev"] else PHY_INFO[args[1]]

    monkeypatch.setattr(discovery, "execute_iw", fake_iw)
    monkeypatch.setattr(discovery, "execute_command", _udev_properties)

    assert discovery.discover_radios() == [
        DiscoveredRadio("wlx001122334455", "phy1", "2-1"),
        DiscoveredRadio("wlan0", "phy0", None),
    ]


def test_discovery_reenumerates_interface_while_udev_renames_it(monkeypatch, tmp_path, real_discovery):
    original = "wlan0"
    final = "wlx001122334455"
    sys_net = tmp_path / "class" / "net"
    _sysfs(tmp_path, original, "usb2/2-2/2-2:1.0", "usb")
    monkeypatch.setattr(discovery, "SYS_CLASS_NET", sys_net)
    monkeypatch.setattr(discovery, "execute_iw", lambda args: (
        f"phy#0\n\tInterface {next(sys_net.iterdir()).name}\n"
        if args == ["dev"] else PHY_INFO["phy0"]
    ))

    monkeypatch.setattr(
        discovery, "execute_command", lambda cmd, **kwargs: _udev_properties(cmd) + f"ID_NET_NAME={final}\n",
    )
    monkeypatch.setattr(discovery, "sleep", lambda _: (sys_net / original).rename(sys_net / final))

    assert discovery.discover_radios() == [DiscoveredRadio(final, "phy0", "2-2")]


def test_discovery_skips_interfaces_without_udev_initialization(monkeypatch, tmp_path, real_discovery):
    _sysfs(tmp_path, "wlan0", "usb2/2-2/2-2:1.0", "usb")
    monkeypatch.setattr(discovery, "SYS_CLASS_NET", tmp_path / "class" / "net")
    monkeypatch.setattr(discovery, "execute_iw", lambda args: (
        "phy#0\n\tInterface wlan0\n" if args == ["dev"] else PHY_INFO["phy0"]
    ))
    monkeypatch.setattr(discovery, "execute_command", lambda *args, **kwargs: "INTERFACE=wlan0\nIFINDEX=5\n")
    monkeypatch.setattr(discovery, "sleep", lambda _: None)

    assert discovery.discover_radios() == []


def test_usb_port_detection_supports_downstream_ports(monkeypatch, tmp_path):
    monkeypatch.setattr(discovery, "SYS_CLASS_NET", tmp_path / "class" / "net")
    _sysfs(tmp_path, "wlx1", "usb1/1-2/1-2.3/1-2.3:1.0", "usb")
    assert discovery.detect_usb_port("wlx1") == "1-2.3"
    assert discovery.detect_usb_port("missing0") is None


def test_resolve_networks_names_orders_and_filters():
    labels = [
        NetworkEntry(interface="wlx-b", display_name="Antenna B"),
        NetworkEntry(interface="wlx-gone", display_name="Unplugged"),
        NetworkEntry(interface="wlan0-virt", display_name="Preferred"),
    ]
    radios = [
        DiscoveredRadio("wlan0", "phy0", None),
        DiscoveredRadio("wlan0-virt", "phy0", None),
        DiscoveredRadio("wlx-c", "phy3", "2-3"),
        DiscoveredRadio("wlx-b", "phy2", "2-2"),
        DiscoveredRadio("wlan-up", "phy4", None),
    ]

    result = resolve_networks(labels, radios, excluded={"wlan-up", "ens18"})

    assert [(n.interface, n.display_name, n.usb_recovery_port) for n in result] == [
        ("wlx-b", "Antenna B", "2-2"),
        ("wlan0-virt", "Preferred", None),
        ("wlx-c", "wlx-c", "2-3"),
    ]


def test_disabled_interface_excludes_its_radio(caplog):
    caplog.set_level(logging.INFO, logger="wilab.config")
    labels = [
        NetworkEntry(interface="wlan0", display_name="Built-in", disable=True),
        NetworkEntry(interface="wlx-gone", display_name="Unplugged", disable=True),
    ]
    radios = [
        DiscoveredRadio("wlan0", "phy0", None),
        DiscoveredRadio("wlan0-virt", "phy0", None),
        DiscoveredRadio("wlx-a", "phy1", "2-1"),
    ]

    result = resolve_networks(labels, radios, excluded=set())

    assert [n.interface for n in result] == ["wlx-a"]
    assert "Skipping wlan0: disabled in configuration" in caplog.text
    assert "not found or not usable" not in caplog.text


def _write_config(tmp_path, networks_yaml):
    path = tmp_path / "config.yaml"
    path.write_text(
        "auth_token: test-token\n"
        "dhcp_base_network: '192.168.120.0/24'\n"
        "dns_server: '8.8.8.8'\n" + REQUIRED_YAML + ""
        "upstream_interface: wlan-up\n"
        + networks_yaml
    )
    return str(path)


# Captured at import, before conftest replaces the seam for each test.
_REAL_INITIAL = config_module._initial_networks


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


def test_load_config_starts_empty_and_scan_applies_labels(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(config_module, "_initial_networks", _REAL_INITIAL)
    monkeypatch.setattr(discovery, "default_route_interfaces", lambda: {"ens18"})
    monkeypatch.setattr(discovery, "discover_radios", lambda **kwargs: [
        DiscoveredRadio("wlan-up", "phy0", None),
        DiscoveredRadio("wlx-a", "phy1", "2-1"),
        DiscoveredRadio("wlx-b", "phy2", "2-2"),
    ])
    path = _write_config(
        tmp_path,
        "antennas:\n"
        "  - interface: wlx-b\n"
        "    display_name: Bench B\n"
        "    show_dfs_channels: false\n"
        "    usb_recovery_port: '9-9'\n"
        "  - interface: wlx-missing\n"
        "    display_name: Missing\n"
        "    show_dfs_channels: false\n",
    )

    cfg = load_config(path)
    assert cfg.antennas == []
    assert "usb_recovery_port" not in caplog.text

    added = config_module.scan_new_networks(cfg, path)

    assert [(n.interface, n.display_name, n.usb_recovery_port, n.show_dfs_channels) for n in added] == [
        ("wlx-b", "Bench B", "2-2", False),
        ("wlx-a", "wlx-a", "2-1", True),   # not listed: DFS channels are offered
    ]
    assert "Ignoring usb_recovery_port for wlx-b" in caplog.text
    assert "wlx-missing" in caplog.text


def test_scan_skips_disabled_entry_without_display_name(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "_initial_networks", _REAL_INITIAL)
    monkeypatch.setattr(discovery, "discover_radios", lambda **kwargs: [
        DiscoveredRadio("wlx-a", "phy1", "2-1"),
        DiscoveredRadio("wlx-b", "phy2", "2-2"),
    ])
    path = _write_config(tmp_path, "antennas:\n  - interface: wlx-a\n    disable: true\n    show_dfs_channels: false\n")

    added = config_module.scan_new_networks(load_config(path), path)

    assert [n.interface for n in added] == ["wlx-b"]


def test_load_config_without_networks(tmp_path):
    assert load_config(_write_config(tmp_path, "")).antennas == []
    assert load_config(_write_config(tmp_path, "antennas:\n")).antennas == []


def test_select_new_networks_skips_managed_and_disabled_radios():
    current = [NetworkEntry(interface="wlx-a", display_name="A", usb_recovery_port="2-1")]
    labels = [
        NetworkEntry(interface="wlx-a", display_name="A"),
        NetworkEntry(interface="wlx-off", display_name="Off", disable=True),
        NetworkEntry(interface="wlx-new", display_name="New"),
    ]
    radios = [
        DiscoveredRadio("wlx-a", "phy0", "2-1"),
        DiscoveredRadio("wlx-a-p2p", "phy0", "2-1"),
        DiscoveredRadio("wlx-off", "phy1", "2-2"),
        DiscoveredRadio("wlx-new", "phy2", "2-3"),
        DiscoveredRadio("wlan9", "phy3", None),
    ]

    added = config_module.select_new_networks(current, labels, radios, excluded={"wlan9"})

    assert [(n.interface, n.display_name, n.usb_recovery_port) for n in added] == [
        ("wlx-new", "New", "2-3"),
    ]


class _StopAfter:
    def __init__(self, waits: int) -> None:
        self.waits: list[float] = []
        self._limit = waits

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        return len(self.waits) > self._limit


def test_discovery_loop_scans_every_5s_until_an_antenna_then_every_30s(monkeypatch, caplog):
    from wilab.api.discovery import DeviceDiscovery

    config = make_config(auth_token="t", dhcp_base_network="192.168.120.0/24", dns_server="8.8.8.8")
    quiet_flags = []

    def scan(cfg, *, quiet):
        quiet_flags.append(quiet)
        if len(quiet_flags) <= 2:
            raise ValueError("Cannot read configuration")
        if len(quiet_flags) == 3:
            cfg.antennas = [NetworkEntry(interface="wlx-a", display_name="A")]
        return []

    service = DeviceDiscovery(config, Mock(), Mock(), Mock())
    monkeypatch.setattr(service, "scan", lambda *, quiet: scan(config, quiet=quiet))
    stop = _StopAfter(4)

    service.loop(stop)

    assert stop.waits == [0.0, 5.0, 5.0, 30.0, 30.0]
    assert quiet_flags == [False, True, True, True]
    assert caplog.text.count("Device discovery failed") == 1
    assert caplog.text.count("No Wi-Fi adapter available") == 1


def test_discovery_adds_antennas_found_after_startup(monkeypatch, tmp_path):
    from wilab.api import discovery as discovery_service

    path = tmp_path / "config.yaml"
    base = (
        "auth_token: test-token\n"
        "dhcp_base_network: '192.168.120.0/24'\n"
        "dns_server: '8.8.8.8'\n" + REQUIRED_YAML + ""
        "antennas:\n"
        "  - interface: wlx-a\n"
        "    display_name: Antenna A\n"
        "    show_dfs_channels: false\n"
        "  - interface: wlx-off\n"
        "    disable: true\n"
        "    show_dfs_channels: false\n"
    )
    path.write_text(base)
    monkeypatch.setenv("CONFIG_PATH", str(path))
    monkeypatch.setattr(config_module, "_initial_networks", _REAL_INITIAL)
    monkeypatch.setattr(discovery_service, "DISCOVERY_FAST_INTERVAL", 0.01)
    monkeypatch.setattr(discovery_service, "DISCOVERY_SLOW_INTERVAL", 0.01)
    radios: list[DiscoveredRadio] = []
    monkeypatch.setattr(discovery, "discover_radios", lambda **kwargs: list(radios))
    headers = {"Authorization": "Bearer test-token"}

    def managed():
        return [(n["interface"], n["display_name"])
                for n in client.get("/api/v2/status", headers=headers).json()["antennas"]]

    with TestClient(create_app()) as client:
        empty = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 60})
        radios[:] = [DiscoveredRadio("wlx-a", "phy0", "2-1"), DiscoveredRadio("wlx-off", "phy1", "2-2")]
        _wait_for(lambda: managed() == [("wlx-a", "Antenna A")])
        # A label added after startup must be read by the next scan.
        path.write_text(base + "  - interface: wlx-new\n    display_name: Antenna New\n    show_dfs_channels: true\n")
        radios.append(DiscoveredRadio("wlx-new", "phy2", "2-3"))
        _wait_for(lambda: len(managed()) == 2)
        final = managed()
        first = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 60})
        second = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 60})

    assert (empty.status_code, empty.json()["detail"]["code"]) == (503, 1003)
    assert final == [("wlx-a", "Antenna A"), ("wlx-new", "Antenna New")]
    assert {first.json()["interface"], second.json()["interface"]} == {"wlx-a", "wlx-new"}


def test_added_antenna_gets_a_watchdog(monkeypatch, context):
    monkeypatch.setattr(discovery, "discover_radios", lambda **kwargs: [
        DiscoveredRadio("wlx-late", "phy9", "2-1"),
    ])
    config = context.config
    watchdog = context.manager.watchdog
    try:
        watchdog.start(context.reservations)
        started = set(watchdog._watched)
        context.discovery.scan()
        context.discovery.scan()

        assert started == {n.device_id for n in config.antennas} - {"wlx-late"}
        assert watchdog._watched == started | {"wlx-late"}
    finally:
        watchdog.stopping.set()


def test_interface_that_udev_never_renames_is_accepted(monkeypatch, tmp_path, real_discovery, caplog):
    """BUG-5: an ID_NET_NAME that never comes no longer hides the adapter forever."""
    _sysfs(tmp_path, "wlan0", "usb2/2-2/2-2:1.0", "usb")
    monkeypatch.setattr(discovery, "SYS_CLASS_NET", tmp_path / "class" / "net")
    monkeypatch.setattr(discovery, "_rename_waits", {})
    monkeypatch.setattr(discovery, "execute_iw", lambda args: (
        "phy#0\n\tInterface wlan0\n" if args == ["dev"] else PHY_INFO["phy0"]
    ))
    monkeypatch.setattr(
        discovery, "execute_command",
        lambda cmd, **kwargs: _udev_properties(cmd) + "ID_NET_NAME=wlx00c0ca112233\n",
    )
    monkeypatch.setattr(discovery, "sleep", lambda _: None)

    scans = [discovery.discover_radios(quiet=True) for _ in range(discovery.RENAME_GRACE_SCANS + 2)]
    assert scans[: discovery.RENAME_GRACE_SCANS] == [[]] * discovery.RENAME_GRACE_SCANS
    assert scans[-2:] == [[DiscoveredRadio("wlan0", "phy0", "2-2")]] * 2
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len([w for w in warnings if "wlx00c0ca112233" in w]) == 1
