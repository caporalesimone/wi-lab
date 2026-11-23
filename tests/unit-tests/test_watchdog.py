"""AP watchdog: restore budget (WD-1)."""

from unittest.mock import Mock

import pytest

from wilab.api import dependencies
from wilab.models import NetworkStatus
from wilab.wifi import watchdog as watchdog_module


def _setup(monkeypatch, times, recreate_at=None):
    """Run the watch loop once per value in `times` with hostapd always dead."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(manager.active, device, NetworkStatus(interface=device, active=True))
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=False))
    clock = iter(times)
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: next(clock))
    flags: list[bool] = []

    def restore(_reservations, _reservation, _status, exhausted):
        flags.append(exhausted)
        if recreate_at is not None and len(flags) == recreate_at:
            # The client deleted and recreated the network: a new status object.
            manager.active[device] = NetworkStatus(interface=device, active=True)

    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(
        manager.watchdog.stopping, "wait", Mock(side_effect=[False] * len(times) + [True]),
    )
    manager.watchdog._watch(reservations, device)
    return flags


def test_second_ap_failure_is_restored_not_quarantined(monkeypatch):
    # Before WD-1 the second failure in the life of a network quarantined the adapter.
    assert _setup(monkeypatch, [0.0, 86400.0]) == [False, False]


def test_budget_is_three_restores_per_hour(monkeypatch):
    assert _setup(monkeypatch, [0.0, 600.0, 1200.0, 1800.0]) == [False, False, False, True]


def test_old_restores_leave_the_window(monkeypatch):
    times = [0.0, 1000.0, 2000.0, 3601.0, 3700.0]
    # At 3601 the restore at 0 is older than an hour; at 3700 three restores
    # (1000, 2000, 3601) are inside the window again.
    assert _setup(monkeypatch, times) == [False, False, False, False, True]


def test_recreating_the_network_does_not_reset_the_budget(monkeypatch):
    flags = _setup(monkeypatch, [0.0, 10.0, 20.0, 30.0], recreate_at=2)
    assert flags == [False, False, False, True]


@pytest.mark.parametrize("exhausted", [False, True])
def test_exhausted_budget_quarantines_instead_of_restarting(monkeypatch, exhausted):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    device = reservation.device_id
    status = NetworkStatus(
        interface=device, active=True, ssid="net", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4,
    )
    monkeypatch.setattr(manager, "release_device", Mock())
    start = Mock()
    quarantine = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)
    manager.watchdog._restore_ap(reservations, reservation, status, exhausted)
    assert start.called is not exhausted
    assert quarantine.called is exhausted
