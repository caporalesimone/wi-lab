"""WD-9: background loops survive any exception and log a repeated one once."""

import logging
import threading
from unittest.mock import Mock

import pytest
from conftest import active_network

from wilab import heartbeat
from wilab.config import _read_raw_config, load_config
from wilab.wifi import watchdog as watchdog_module


def _stop_after(event: threading.Event, ticks: int) -> Mock:
    return Mock(side_effect=[False] * ticks + [True])


def test_discovery_survives_any_exception(monkeypatch, caplog, context):
    calls = Mock(side_effect=[TypeError("boom"), TypeError("boom"), []])
    monkeypatch.setattr(context.discovery, "scan", calls)
    stop = threading.Event()
    monkeypatch.setattr(stop, "wait", _stop_after(stop, 3))
    caplog.set_level(logging.ERROR)
    context.discovery.loop(stop)
    assert calls.call_count == 3  # before WD-9 the thread died on the TypeError
    assert sum("Device discovery failed" in r.getMessage() for r in caplog.records) == 1


def test_watchdog_survives_any_exception_and_logs_it_once(monkeypatch, caplog, context):
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(0)
    device = reservation.device_id
    monkeypatch.setitem(manager.active, device, active_network(interface=device))
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)
    probe = Mock(side_effect=[KeyError("x"), KeyError("x"), KeyError("x"), True])
    monkeypatch.setattr(manager.hostapd_manager, "is_running", probe)
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", Mock(return_value=True))
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=True))
    monkeypatch.setattr(manager.watchdog.stopping, "wait", Mock(side_effect=[False] * 4 + [True]))
    monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: 0.0)
    caplog.set_level(logging.ERROR)
    manager.watchdog._watch(reservations, device)
    assert probe.call_count == 4
    assert sum("Could not check or restore" in r.getMessage() for r in caplog.records) == 1


def test_expiry_loop_logs_unexpected_errors_once(monkeypatch, caplog, context):
    manager = context.manager
    monkeypatch.setattr(heartbeat, "beat", lambda _name: None)
    monkeypatch.setattr(manager, "expire_reservations", Mock(side_effect=AttributeError("gone")))
    monkeypatch.setattr(manager.watchdog.stopping, "wait", Mock(side_effect=[False] * 3 + [True]))
    caplog.set_level(logging.ERROR)
    manager._expiry_loop()
    assert manager.expire_reservations.call_count == 3
    errors = [r for r in caplog.records if "[expiry-loop]" in r.getMessage()]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR  # was DEBUG, invisible


@pytest.mark.parametrize(("content", "message"), [
    ("- a\n- b\n", "must be a YAML mapping"),
    ("antennas: 5\n", "antennas must be a list"),
])
def test_config_with_the_wrong_shape_is_a_clear_error(tmp_path, content, message):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    with pytest.raises(TypeError, match=message):
        _read_raw_config(str(path))
    with pytest.raises(SystemExit, match="Configuration error"):
        load_config(str(path))
