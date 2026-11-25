"""HAP-3: a startup failure is classified by its exception, not by the attempt number."""

from unittest.mock import Mock

import pytest

from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.wifi import manager as manager_module
from wilab.wifi.hostapd import HostapdError, HostapdInitFailure, HostapdRadioFailure
from wilab.wifi.manager import NetworkManager, StartupFailure


def _request() -> NetworkCreateRequest:
    return NetworkCreateRequest(ssid="cls", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)


@pytest.fixture
def manager(monkeypatch) -> NetworkManager:
    mgr = NetworkManager(load_config())
    monkeypatch.setattr(manager_module, "STARTUP_RETRY_DELAY", 0.0)
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    return mgr


def _init_failure() -> HostapdInitFailure:
    return HostapdInitFailure("hostapd exited with code 1 on wlan0: beacon setup failed")


def test_init_failure_is_a_radio_failure() -> None:
    assert issubclass(HostapdInitFailure, HostapdRadioFailure)


@pytest.mark.parametrize("allow_internal_retry", [True, False])
def test_init_failure_is_radio_on_every_request(monkeypatch, manager, allow_internal_retry) -> None:
    """The second and third create of a sequence (no internal retry) and the
    watchdog restart got a generic 500 for the same failure the first create
    reported as 409 / 1001."""
    device = manager.config.antennas[0].device_id
    start = Mock(side_effect=_init_failure())
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=allow_internal_retry)
    assert failure.value.radio and not failure.value.cleanup_failed
    assert start.call_count == (3 if allow_internal_retry else 1)


def test_unclassified_hostapd_error_is_not_radio(monkeypatch, manager) -> None:
    device = manager.config.antennas[0].device_id
    start = Mock(side_effect=HostapdError("hostapd exited with code 1 on wlan0"))
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert not failure.value.radio
    assert start.call_count == 1  # not retried


def test_retry_after_a_radio_failure_keeps_the_classification(monkeypatch, manager) -> None:
    """An unclassified exit on the retry still follows a radio failure of this request."""
    device = manager.config.antennas[0].device_id
    start = Mock(side_effect=[_init_failure(), HostapdError("hostapd exited with code 1 on wlan0")])
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert failure.value.radio
    assert start.call_count == 2


def test_non_ap_stage_after_a_radio_retry_is_not_radio(monkeypatch, manager) -> None:
    """A DHCP failure after the AP came up on the retry is not a radio failure."""
    from wilab.network.dhcp import DhcpServerError

    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(manager.hostapd_manager, "start", Mock(side_effect=[_init_failure(), None]))
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(side_effect=DhcpServerError("port 67 in use")))
    with pytest.raises(StartupFailure, match="configure DHCP") as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert not failure.value.radio


# --------------------------------------------------------------------------- HAP-4


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 100.0}
    monkeypatch.setattr(manager_module.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(manager_module.time, "sleep", lambda s: now.__setitem__("t", now["t"] + s))
    return now


def _timed_start(clock, durations, budgets):
    """hostapd start that records its remaining budget, then fails after `durations[i]` s."""
    from wilab.network import commands

    calls = iter(durations)

    def start(*args, **kwargs):
        deadline = commands._command_deadline.get()
        budgets.append(None if deadline is None else round(deadline - clock["t"], 2))
        clock["t"] += next(calls)
        raise HostapdRadioFailure("AP not ready on wlan0 (hostapd state: COUNTRY_UPDATE)")

    return start


def test_every_internal_retry_gets_at_least_four_seconds(monkeypatch, manager, clock):
    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(manager_module, "STARTUP_RETRY_DELAY", 1.0)
    budgets: list[float | None] = []
    # First start: 10 s readiness timeout plus 2 s of rollback. With the old values
    # (15 s budget, 0.75 s minimum) the retry started with 2 s left.
    monkeypatch.setattr(manager.hostapd_manager, "start", _timed_start(clock, [12.0, 4.0, 4.0], budgets))
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert failure.value.radio
    assert budgets[0] is None  # the first start is not cut by the retry budget
    assert len(budgets) >= 2
    assert all(b is not None and b >= 4.0 for b in budgets[1:]), budgets


def test_no_retry_is_started_without_enough_time(monkeypatch, manager, clock):
    """Before HAP-4 a retry could start with 0.75 s and add an artificial radio failure."""
    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(manager_module, "STARTUP_RETRY_DELAY", 1.0)
    budgets: list[float | None] = []
    # 16 s used: 4 s left, less than the 1 s wait plus a 4 s attempt.
    monkeypatch.setattr(manager.hostapd_manager, "start", _timed_start(clock, [16.0], budgets))
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert failure.value.radio
    assert len(budgets) == 1


# --------------------------------------------------------------------------- PERF-1


def test_start_runs_no_redundant_commands(monkeypatch, manager):
    """PERF-1: no iw capability checks, no nmcli/dnsmasq --version on each start."""
    from wilab.wifi import interface as interface_module

    device = manager.config.antennas[0].device_id
    monkeypatch.setattr(manager.hostapd_manager, "start", Mock())
    seen: list[list[str]] = []
    real = manager_module.execute_command

    def record(cmd, *args, **kwargs):
        seen.append(cmd)
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(manager_module, "execute_command", record)
    monkeypatch.setattr(interface_module, "execute_command", record)
    monkeypatch.setattr(manager_module, "_nmcli_available", lambda: True)
    manager.start_network(device, _request())
    assert ["nmcli", "--version"] not in seen
    assert not any(cmd[:2] == ["iw", "phy"] or cmd[-1:] == ["info"] for cmd in seen if cmd[:1] == ["iw"])
