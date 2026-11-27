"""NET-1: every iptables call waits for the xtables lock, and status reads take the firewall lock."""

from unittest.mock import Mock

from conftest import configured_devices

from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.network import commands, safety
from wilab.network.commands import IPTABLES_LOCK_WAIT, execute_iptables
from wilab.wifi.manager import NetworkManager


def _record_commands(monkeypatch):
    """Wrap the (already mocked) command runner and record every argv."""
    calls: list[list[str]] = []
    mocked = commands.execute_command

    def recording(cmd, **kwargs):
        calls.append(list(cmd))
        return mocked(cmd, **kwargs)

    monkeypatch.setattr(commands, "execute_command", recording)
    return calls


def test_execute_iptables_waits_for_the_lock(monkeypatch):
    calls = _record_commands(monkeypatch)
    execute_iptables(["-S", "FORWARD"])
    assert calls == [["iptables", "-w", IPTABLES_LOCK_WAIT, "-S", "FORWARD"]]


def test_full_network_cycle_never_calls_iptables_without_wait(monkeypatch):
    calls = _record_commands(monkeypatch)
    manager = NetworkManager(load_config(), configured_devices())
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock())
    monkeypatch.setattr(manager.hostapd_manager, "start", Mock())
    monkeypatch.setattr(manager.hostapd_manager, "stop", Mock())
    request = NetworkCreateRequest(
        ssid="lock", channel=6, encryption="open", band="2.4ghz", tx_power_level=4,
        internet_enabled=True, captive_portal=True,
    )
    device = manager.config.antennas[0].device_id
    manager.start_network(device, request)
    manager.firewall_status()
    manager.stop_network(device)
    manager.nat_manager.remove_stale_rules()
    safety.list_wilab_rules()

    iptables = [cmd for cmd in calls if cmd and cmd[0] == "iptables"]
    # NAT, isolation, captive portal, status, stale cleanup and safety listing all ran.
    assert len(iptables) > 20
    assert all(cmd[1:3] == ["-w", IPTABLES_LOCK_WAIT] for cmd in iptables), [
        cmd for cmd in iptables if cmd[1:3] != ["-w", IPTABLES_LOCK_WAIT]
    ]


def test_firewall_status_holds_the_firewall_lock(monkeypatch):
    manager = NetworkManager(load_config(), configured_devices())
    held = []
    monkeypatch.setattr(
        manager.nat_manager, "status", lambda: held.append(manager._firewall_lock.locked()) or {},
    )
    manager.firewall_status()
    manager.services_status()
    assert held == [True, True]
