"""The client list of a running network (wifi/clients.py): station dump joined with the leases."""

import time
from unittest.mock import Mock

import pytest
from conftest import registry_of

from wilab.network.commands import CommandError
from wilab.wifi import clients as clients_module
from wilab.wifi.clients import ClientLister

STATIONS = """Station AA:BB:CC:00:00:01 (on wlan0)
\tinactive time:\t10 ms
\trx bytes:\t1234
Station aa:bb:cc:00:00:02 (on wlan0)
\tinactive time:\t20 ms
Station aa:bb:cc:00:00:03 (on wlan0)
"""


@pytest.fixture
def leases(tmp_path):
    path = tmp_path / "wlan0.leases"
    future, past = int(time.time()) + 3600, int(time.time()) - 10
    path.write_text(
        f"{future} aa:bb:cc:00:00:01 192.168.120.10 phone *\n"
        f"{future} AA:BB:CC:00:00:02 192.168.120.11 laptop 01:aa\n"
        f"{past} aa:bb:cc:00:00:03 192.168.120.12 old *\n"       # expired: not a client
        "duid 00:01:00:01\n"                                       # dnsmasq's own line
    )
    return path


def _lister(leases_path=None, portals=None):
    dhcp = Mock()
    dhcp.get_subnet_info.return_value = {"lease_file": str(leases_path)} if leases_path else None
    return ClientLister(registry_of("wlan0"), dhcp, portals if portals is not None else {})


def test_only_associated_stations_with_a_lease_are_clients(monkeypatch, leases):
    monkeypatch.setattr(clients_module, "execute_iw", lambda args: STATIONS)
    found = _lister(leases).connected("wlan0")
    assert [(c.mac, c.ip) for c in found] == [
        ("aa:bb:cc:00:00:01", "192.168.120.10"), ("aa:bb:cc:00:00:02", "192.168.120.11"),
    ]
    assert all(c.captive_authorized is None for c in found)   # no portal on this network


def test_the_portal_tells_each_client_sign_in(monkeypatch, leases):
    monkeypatch.setattr(clients_module, "execute_iw", lambda args: STATIONS)
    portal = Mock()
    portal.is_authorized.side_effect = lambda ip, mac: ip.endswith(".10")
    found = _lister(leases, {"wlan0": portal}).connected("wlan0")
    assert [c.captive_authorized for c in found] == [True, False]


def test_the_list_is_reused_for_a_short_time(monkeypatch, leases):
    dump = Mock(return_value=STATIONS)
    monkeypatch.setattr(clients_module, "execute_iw", dump)
    now = {"t": 100.0}
    monkeypatch.setattr(clients_module.time, "monotonic", lambda: now["t"])
    lister = _lister(leases)
    lister.connected("wlan0")
    lister.connected("wlan0")
    assert dump.call_count == 1                       # PERF-2
    now["t"] += clients_module.CLIENTS_CACHE_SECONDS
    lister.connected("wlan0")
    assert dump.call_count == 2
    lister.forget("wlan0")
    lister.connected("wlan0")
    assert dump.call_count == 3                       # a stopped network starts over


@pytest.mark.parametrize("case", ["unknown_device", "dump_fails", "no_station", "no_lease_file"])
def test_no_clients(monkeypatch, leases, case):
    def dump(args):
        if case == "dump_fails":
            raise CommandError("device busy")
        return "" if case == "no_station" else STATIONS

    monkeypatch.setattr(clients_module, "execute_iw", dump)
    lister = _lister(None if case == "no_lease_file" else leases)
    assert lister.connected("wlan9" if case == "unknown_device" else "wlan0") == []


def test_an_unreadable_lease_file_gives_no_leases(monkeypatch, leases):
    monkeypatch.setattr("builtins.open", Mock(side_effect=PermissionError("denied")))
    assert _lister(leases).leases("wlan0") == {}


def test_mac_of_uses_the_lease_then_the_neighbour_table(monkeypatch, leases):
    neigh = Mock(return_value="192.168.120.50 lladdr aa:bb:cc:00:00:09 REACHABLE")
    monkeypatch.setattr(clients_module, "execute_ip", neigh)
    lister = _lister(leases)
    assert lister.mac_of("wlan0", "192.168.120.11") == "aa:bb:cc:00:00:02"
    neigh.assert_not_called()
    assert lister.mac_of("wlan0", "192.168.120.50") == "aa:bb:cc:00:00:09"


@pytest.mark.parametrize("answer", ["192.168.120.60 FAILED", "", CommandError("no table")])
def test_mac_of_an_unknown_address_is_none(monkeypatch, leases, answer):
    neigh = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    monkeypatch.setattr(clients_module, "execute_ip", neigh)
    assert _lister(leases).mac_of("wlan0", "192.168.120.60") is None
