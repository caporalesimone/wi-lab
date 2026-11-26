"""STAB-4: startup removes what an unclean shutdown left behind."""

from pathlib import Path

import pytest

from wilab import runtime_cleanup
from wilab.network.commands import CommandError
from wilab.wifi import interface as interface_module


def _proc(root: Path, pid: int, *args: str) -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")


def test_orphans_are_only_wilab_hostapd_and_dnsmasq(tmp_path):
    _proc(tmp_path, 10, "/usr/sbin/hostapd", "/tmp/wilab-hostapd/ap-x/hostapd.conf")
    _proc(tmp_path, 11, "dnsmasq", "--conf-file=/tmp/wilab-dnsmasq/dnsmasq-wlan0.conf")
    _proc(tmp_path, 12, "/usr/sbin/dnsmasq", "--conf-file=/etc/dnsmasq.conf")  # libvirt, not ours
    _proc(tmp_path, 13, "/usr/bin/python3", "/tmp/wilab-hostapd/x")  # not a daemon we start
    (tmp_path / "self").mkdir()
    assert sorted(runtime_cleanup._orphans(tmp_path)) == [(10, "hostapd"), (11, "dnsmasq")]


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    hostapd_dir, dnsmasq_dir = tmp_path / "wilab-hostapd", tmp_path / "wilab-dnsmasq"
    (hostapd_dir / "ap-old").mkdir(parents=True)
    (hostapd_dir / "ap-old" / "hostapd.conf").write_text("ssid2=...")
    dnsmasq_dir.mkdir()
    (dnsmasq_dir / "dnsmasq-wlan0.conf").write_text("interface=wlan0")
    legacy = tmp_path / "tmp-wilab-hostapd"
    (legacy / "ap-x").mkdir(parents=True)
    monkeypatch.setattr(runtime_cleanup, "RUNTIME_DIRS", (str(hostapd_dir), str(dnsmasq_dir), str(legacy)))
    # Never the real /tmp/wilab-* of a running service (STAB-2).
    monkeypatch.setattr(runtime_cleanup, "LEGACY_RUNTIME_DIRS", (str(legacy),))
    stopped: list[int] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(runtime_cleanup, "_orphans", lambda: [(4242, "dnsmasq")])
    monkeypatch.setattr(runtime_cleanup, "stop_process", stopped.append)

    def command(cmd, check=True):
        commands.append(cmd)
        if cmd[:3] == ["ip", "-o", "link"]:
            return (
                "7: ifb0: <BROADCAST,NOARP> mtu 1500 qdisc noop state DOWN\n"
                "8: wilab-ifb0: <BROADCAST,NOARP,UP> mtu 1500 qdisc htb state UNKNOWN\n"
            )
        return ""

    monkeypatch.setattr(runtime_cleanup, "execute_command", command)
    return hostapd_dir, dnsmasq_dir, stopped, commands


def test_cleanup_stops_orphans_empties_runtime_dirs_and_removes_own_ifbs(runtime):
    hostapd_dir, dnsmasq_dir, stopped, commands = runtime
    runtime_cleanup.cleanup_runtime()
    assert stopped == [4242]
    assert list(hostapd_dir.iterdir()) == []
    assert list(dnsmasq_dir.iterdir()) == []
    assert ["ip", "link", "del", "wilab-ifb0"] in commands
    assert ["ip", "link", "del", "ifb0"] not in commands  # may belong to other software


def test_cleanup_never_raises(runtime, monkeypatch):
    def boom(_pid):
        raise CommandError("Process 4242 did not exit")

    monkeypatch.setattr(runtime_cleanup, "stop_process", boom)
    runtime_cleanup.cleanup_runtime()


def test_reset_interface_clears_address_mode_and_traffic_control(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(interface_module, "interface_present", lambda name: True)
    monkeypatch.setattr(interface_module, "execute_command", lambda cmd, check=True: calls.append(cmd) or "")
    interface_module.reset_interface("wlan0")
    assert calls == [
        ["ip", "link", "set", "wlan0", "down"],
        ["iw", "dev", "wlan0", "set", "type", "managed"],
        ["ip", "addr", "flush", "dev", "wlan0"],
        ["tc", "qdisc", "del", "dev", "wlan0", "root"],
        ["tc", "qdisc", "del", "dev", "wlan0", "ingress"],
    ]


def test_reset_interface_skips_a_missing_adapter_and_survives_failures(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(interface_module, "execute_command", lambda cmd, check=True: calls.append(cmd))
    monkeypatch.setattr(interface_module, "interface_present", lambda name: False)
    interface_module.reset_interface("wlan0")
    assert calls == []

    def fail(cmd, check=True):
        calls.append(cmd)
        raise CommandError("RTNETLINK answers: Operation not permitted")

    monkeypatch.setattr(interface_module, "interface_present", lambda name: True)
    monkeypatch.setattr(interface_module, "execute_command", fail)
    interface_module.reset_interface("wlan0")
    assert len(calls) == 5  # every step is still tried


@pytest.mark.parametrize("reset_works", [True, False])
def test_a_stale_gateway_address_does_not_shift_the_subnet(monkeypatch, reset_works):
    """NET-9: after an unclean restart a radio keeps the gateway address of its subnet.

    Discovery resets the radio (STAB-4) before any allocation, so the radio gets its
    own subnet again instead of the next one. Without the reset it would shift.
    """
    from ipaddress import IPv4Network

    from wilab.api import dependencies
    from wilab.config import NetworkEntry
    from wilab.wifi import manager as manager_module

    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    radio = NetworkEntry(interface="wlxstale", display_name="stale")
    base = IPv4Network(config.dhcp_base_network)
    natural = IPv4Network((int(base.network_address) + 256 * len(config.antennas), 24))
    routes = {natural}   # the address the radio kept from the previous run

    def reset(interface):
        if reset_works and interface == radio.interface:
            routes.clear()

    monkeypatch.setattr(dependencies, "scan_new_networks", lambda cfg, quiet=False: [radio])
    monkeypatch.setattr(dependencies, "exclude_from_host_managers", lambda names: None)
    monkeypatch.setattr(dependencies, "reset_interface", reset)
    monkeypatch.setattr(manager.watchdog, "watch", lambda devices: None)
    monkeypatch.setattr(manager_module, "host_ipv4_networks", lambda: set(routes))
    dependencies.scan_devices(config)
    subnet = IPv4Network(manager._get_subnet(radio.device_id))
    assert (subnet == natural) is reset_works


def test_the_pre_4_1_directories_in_tmp_are_removed(runtime, tmp_path):
    """STAB-2: after an upgrade, startup empties and removes /tmp/wilab-*."""
    runtime_cleanup.cleanup_runtime()
    assert not (tmp_path / "tmp-wilab-hostapd").exists()


def test_runtime_files_live_in_the_private_directory_systemd_creates():
    from pathlib import Path

    from wilab import paths

    # The tests point hostapd to tmp_path: check the defaults the service uses.
    assert paths.HOSTAPD_RUNTIME_DIR.startswith(paths.RUNTIME_DIR)
    assert paths.DNSMASQ_RUNTIME_DIR.startswith(paths.RUNTIME_DIR)
    assert not paths.RUNTIME_DIR.startswith("/tmp")
    unit = (Path(__file__).resolve().parents[2] / "install/systemd/wi-lab.service.template").read_text()
    assert "RuntimeDirectory=wilab" in unit and "RuntimeDirectoryMode=0700" in unit
