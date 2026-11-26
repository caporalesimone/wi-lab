"""Asynchronous create: 202 + polling of GET .../network, cancel by release or stop.

The contract agreed with the client developers (4.0.0):
- POST answers 202 with the network in `runtime_state: starting`, the same schema as GET;
- GET shows `starting`, then the network (`runtime_state: null`), `start_failed` with
  `error`, or 404 with the reason when the reservation ended;
- the same body again answers 202 while starting and 200 once running; another body 409 / 1008;
- DELETE of the reservation or of the network cancels a start in progress.
"""

import threading
import time
from unittest.mock import Mock

import pytest
from conftest import network_body
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.api.routes import network
from wilab.models import NetworkStatus
from wilab.wifi.manager import StartupFailure

RESERVE = "/api/v2/reservations"
BODY = network_body(ssid="async-test", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)


def _wait_until(predicate, timeout: float = 5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.fixture
def api(monkeypatch):
    """Background creates on, a scripted start_network, and a reserved antenna."""
    monkeypatch.setattr(network, "CREATE_RETRY_DELAYS", (0, 0))
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    monkeypatch.setattr(dependencies.get_channel_manager(), "validate_network", Mock())
    script = {"outcome": "ok", "release": threading.Event(), "calls": 0}
    script["release"].set()

    def start_network(device, req, *args, cancelled=None, **kwargs):
        script["calls"] += 1
        while not script["release"].wait(0.01):
            if cancelled is not None and cancelled():
                raise StartupFailure("AP start cancelled", stage="hostapd")
        outcome = script["outcome"]
        if outcome == "radio":
            raise StartupFailure("radio timeout", radio=True)
        if outcome == "stage":
            raise StartupFailure("dnsmasq refused the configuration", stage="dhcp")
        manager.active[device] = NetworkStatus(interface=device, active=True)
        return manager.active[device]

    monkeypatch.setattr(manager, "start_network", start_network)
    monkeypatch.setattr(
        manager, "get_status",
        lambda device: manager.active.get(device) or NetworkStatus(interface=device, active=False),
    )
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(create_app()) as client:
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 300}).json()["reservation_id"]
        yield client, headers, f"{RESERVE}/{rid}", script, manager
        script["release"].set()
        with manager.start_jobs_lock:
            threads = [job.thread for job in manager.start_jobs.values() if job.thread is not None]
        for thread in threads:
            thread.join(timeout=5)  # never leave a start running into the next test
        manager.active.clear()


def _state(client, headers, url):
    return client.get(f"{url}/network", headers=headers)


def test_create_answers_202_and_the_network_appears_by_polling(api):
    client, headers, url, script, _manager = api
    script["release"].clear()
    created = client.post(f"{url}/network", headers=headers, json=BODY)
    assert created.status_code == 202
    assert (created.json()["active"], created.json()["runtime_state"]) == (False, "starting")
    polled = _state(client, headers, url)
    assert polled.json()["runtime_state"] == "starting"
    assert set(created.json()) == set(polled.json())  # same schema as GET (the library reads the body)
    status = client.get("/api/v2/status", headers=headers).json()
    assert status["antennas"][0]["runtime_state"] == "starting"
    assert status["status"] != "degraded"
    script["release"].set()
    done = _wait_until(lambda: (r := _state(client, headers, url).json())["runtime_state"] is None and r)
    assert done["active"] is True and done["error"] is None


def test_same_body_while_starting_is_202_then_200_another_body_is_1008(api):
    client, headers, url, script, _manager = api
    script["release"].clear()
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    other = network_body(ssid="other", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
    resp = client.post(f"{url}/network", headers=headers, json=other)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, 1008)
    script["release"].set()
    _wait_until(lambda: _state(client, headers, url).json()["active"])
    assert script["calls"] == 1  # the repeated create did not start a second AP


def test_non_radio_failure_is_start_failed_until_a_new_create_or_a_stop(api):
    client, headers, url, script, _manager = api
    script["outcome"] = "stage"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    failed = _wait_until(lambda: (r := _state(client, headers, url).json())["runtime_state"] == "start_failed" and r)
    assert failed["error"]["code"] == 1013 and failed["error"]["stage"] == "dhcp"
    assert client.get(url, headers=headers).status_code == 200  # the reservation is still valid
    assert _state(client, headers, url).json()["runtime_state"] == "start_failed"  # stays visible
    assert client.delete(f"{url}/network", headers=headers).status_code == 200
    cleared = _state(client, headers, url).json()
    assert (cleared["active"], cleared["runtime_state"], cleared["error"]) == (False, None, None)
    script["outcome"] = "ok"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    _wait_until(lambda: _state(client, headers, url).json()["active"])


def test_every_start_failing_ends_with_404_reservation_invalidated(api):
    client, headers, url, script, _manager = api
    script["outcome"] = "radio"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    gone = _wait_until(lambda: (r := _state(client, headers, url)).status_code == 404 and r)
    assert gone.json()["detail"]["reason"] == "reservation_invalidated"
    assert script["calls"] == 3


def test_reservation_too_short_for_another_start_ends_with_404_expired(api, monkeypatch):
    client, headers, url, script, _manager = api
    monkeypatch.setattr(network, "START_MARGIN", 400)
    script["outcome"] = "radio"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    gone = _wait_until(lambda: (r := _state(client, headers, url)).status_code == 404 and r)
    assert gone.json()["detail"]["reason"] == "reservation_expired"


def test_release_during_a_start_cancels_it_at_once(api):
    client, headers, url, script, manager = api
    script["release"].clear()  # a long start (e.g. a DFS channel)
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    began = time.monotonic()
    assert client.delete(url, headers=headers).status_code == 200
    assert time.monotonic() - began < 3
    assert _state(client, headers, url).json()["detail"]["reason"] == "reservation_released"
    assert not manager.start_jobs


def test_stop_during_a_start_cancels_it_and_keeps_the_reservation(api):
    client, headers, url, script, manager = api
    script["release"].clear()
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    assert client.delete(f"{url}/network", headers=headers).status_code == 200
    state = _state(client, headers, url).json()
    assert (state["active"], state["runtime_state"]) == (False, None)
    assert client.get(url, headers=headers).status_code == 200
    assert not manager.start_jobs


@pytest.mark.parametrize("watchdog_state", ["restoring_ap", "restoring_dhcp", "dhcp_failed"])
def test_create_during_a_watchdog_repair_is_1009(api, monkeypatch, watchdog_state):
    client, headers, url, _script, manager = api
    monkeypatch.setattr(manager.watchdog, "state", lambda _reservation: watchdog_state)
    resp = client.post(f"{url}/network", headers=headers, json=BODY)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, 1009)


def test_the_same_create_sent_twice_at_once_starts_one_ap_and_both_get_202(api):
    client, headers, url, script, manager = api
    script["release"].clear()
    inside, go = threading.Event(), threading.Event()

    def slow_validation(*_args, **_kwargs):
        inside.set()
        go.wait(5)

    dependencies.get_channel_manager().validate_network.side_effect = slow_validation
    answers = []
    first = threading.Thread(
        target=lambda: answers.append(client.post(f"{url}/network", headers=headers, json=BODY).status_code),
    )
    first.start()
    assert inside.wait(5)  # the first request is past the job check, not yet registered
    dependencies.get_channel_manager().validate_network.side_effect = None
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    go.set()
    first.join(5)
    assert answers == [202]
    script["release"].set()
    _wait_until(lambda: _state(client, headers, url).json()["active"])
    assert script["calls"] == 1


def test_start_failed_always_carries_1013_also_for_an_unexpected_error(api):
    client, headers, url, script, manager = api
    for error in (ValueError("No available /24 AP subnet"), KeyError("boom")):
        def start_network(*_args, _error=error, **_kwargs):
            raise _error
        manager.start_network = start_network
        assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
        failed = _wait_until(
            lambda: (r := _state(client, headers, url).json())["runtime_state"] == "start_failed" and r,
        )
        assert (failed["error"]["code"], failed["error"]["reason"]) == (1013, "startup_failed")
        assert failed["error"]["stage"] is None and failed["error"]["message"]


# --------------------------------------------------------------------------- REV-1 (unit-test-1)


@pytest.fixture
def real_start(monkeypatch):
    """Background creates with the real start_network: hostapd and DHCP are fakes that track state."""
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    monkeypatch.setattr(dependencies.get_channel_manager(), "validate_network", Mock())
    monkeypatch.setattr(manager._channel_manager, "validate_network", Mock())
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    instances = manager.hostapd_manager._instances

    def hostapd_start(*, net_id, **kwargs):
        instances[net_id] = Mock()

    stop = Mock(side_effect=lambda net_id: instances.pop(net_id, None))
    monkeypatch.setattr(manager.hostapd_manager, "start", hostapd_start)
    monkeypatch.setattr(manager.hostapd_manager, "stop", stop)
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock())
    monkeypatch.setattr(manager.dhcp_server, "list_active", Mock(return_value=[]))
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(create_app()) as client:
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 300}).json()["reservation_id"]
        yield client, headers, f"{RESERVE}/{rid}", manager, stop
        with manager.start_jobs_lock:
            threads = [job.thread for job in manager.start_jobs.values() if job.thread is not None]
        for thread in threads:
            thread.join(timeout=5)
        manager.active.clear()


@pytest.mark.parametrize("error", [KeyError("subnet"), OSError(24, "Too many open files")])
def test_unexpected_error_in_a_start_leaves_nothing_running(real_start, monkeypatch, error):
    client, headers, url, manager, stop = real_start
    monkeypatch.setattr(manager.isolation_manager, "add_network", Mock(side_effect=error))
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    failed = _wait_until(lambda: (r := _state(client, headers, url).json())["runtime_state"] == "start_failed" and r)
    assert (failed["error"]["code"], failed["error"]["stage"]) == (1013, "isolation")
    device = failed["interface"]
    stop.assert_called_with(device)   # the rollback stopped hostapd
    assert not manager.has_leftovers(device)
    assert device not in manager.active
    assert client.delete(f"{url}/network", headers=headers).status_code == 200   # clears start_failed
    again = client.delete(f"{url}/network", headers=headers)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, 1007)


def test_stop_releases_what_a_failed_start_left(real_start):
    """A start whose rollback failed left hostapd: DELETE .../network stops it instead of a bare 200."""
    client, headers, url, manager, stop = real_start
    device = manager.config.antennas[0].device_id
    manager.hostapd_manager._instances[device] = Mock()   # left by an earlier start
    assert client.delete(f"{url}/network", headers=headers).status_code == 200
    stop.assert_called_with(device)
    assert not manager.has_leftovers(device)
    again = client.delete(f"{url}/network", headers=headers)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, 1007)
