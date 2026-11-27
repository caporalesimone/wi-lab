"""`health` of GET /antennas/{interface}: repair budgets, quarantines, USB resets."""

import time
from datetime import datetime

from fastapi.testclient import TestClient

from wilab.config import DriverWatchdog, RepairBudgetOverride, WatchdogConfig
from wilab.wifi.watchdog import DeviceWatch


def _antenna(client, context, interface):
    headers = {"Authorization": f"Bearer {context.config.auth_token}"}
    response = client.get(f"/api/v2/antennas/{interface}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["health"]


def test_a_fresh_antenna_has_its_whole_budget(context, app):
    device = context.manager.devices.all()[0].interface
    with TestClient(app) as client:
        health = _antenna(client, context, device)
    assert health == {
        "ap_restores": {"used": 0, "limit": 3, "window_minutes": 60, "frees_at": None},
        "dhcp_restarts": {"used": 0, "limit": 3, "window_minutes": 60, "frees_at": None},
        "quarantines": {"count": 0, "last_at": None, "last_usb_recovery": None},
        "last_usb_reset_at": None,
    }


def test_used_repairs_limit_by_driver_quarantines_and_usb_reset(monkeypatch, context, app):
    manager = context.manager
    device = manager.devices.all()[0]
    monkeypatch.setattr(device, "driver", "mt7921u")
    monkeypatch.setattr(manager.config, "watchdog", WatchdogConfig(
        drivers={"mt7921u": DriverWatchdog(ap_restores=RepairBudgetOverride(limit=5))},
    ))
    now = time.monotonic()
    watch = DeviceWatch(device.interface)
    watch.restores.extend([now - 5_000, now - 1_000, now - 500])   # the first is older than an hour
    watch.dhcp_restores.append(now - 100)
    manager.watchdog._watches[device.interface] = watch
    manager.quarantines[device.interface] = (2, 1_799_999_000.0, True)
    manager.recovery.last_usb_reset[device.interface] = 1_799_999_100.0
    with TestClient(app) as client:
        health = _antenna(client, context, device.interface)
    ap = health["ap_restores"]
    assert (ap["used"], ap["limit"], ap["window_minutes"]) == (2, 5, 60)
    # the restore of 1000 s ago leaves the window in 2600 s
    frees_in = datetime.fromisoformat(ap["frees_at"]).timestamp() - time.time()
    assert 2590 < frees_in < 2610
    assert health["dhcp_restarts"]["used"] == 1 and health["dhcp_restarts"]["limit"] == 3
    assert health["quarantines"] == {"count": 2, "last_at": "2027-01-15T07:43:20Z", "last_usb_recovery": True}
    assert health["last_usb_reset_at"] == "2027-01-15T07:45:00Z"


def test_a_quarantine_is_counted(monkeypatch, context):
    from unittest.mock import Mock

    manager = context.manager
    reservations = context.reservations
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    reservation = reservations.create(60)
    manager.quarantine_radio(reservations, reservation, radio_fault=False, band="5ghz", channel=36)
    count, _last_at, usb = manager.quarantines[reservation.device_id]
    assert (count, usb) == (1, False)
