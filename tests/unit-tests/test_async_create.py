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
from conftest import active_network, configured_devices, network_body
from fastapi.testclient import TestClient

from wilab.api.routes import network
from wilab.models import NetworkStatus
from wilab.wifi.failures import FailureKind
from wilab.wifi.hostapd import HostapdError
from wilab.wifi.manager import NetworkManager, StartupFailure

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
def api(monkeypatch, context, app):
    """Background creates on, a scripted start_network, and a reserved antenna."""
    monkeypatch.setattr(network, "CREATE_RETRY_DELAYS", (0, 0))
    config = context.config
    manager = context.manager
    monkeypatch.setattr(context.channels, "validate_network", Mock())
    script = {"outcome": "ok", "release": threading.Event(), "calls": 0}
    script["release"].set()

    def start_network(device, req, *args, cancelled=None, **kwargs):
        script["calls"] += 1
        while not script["release"].wait(0.01):
            if cancelled is not None and cancelled():
                raise StartupFailure("AP start cancelled", stage="hostapd")
        outcome = script["outcome"]
        if outcome == "radio":
            raise StartupFailure("radio timeout", kind=FailureKind.TRANSIENT_RADIO)
        if outcome == "stage":
            raise StartupFailure("dnsmasq refused the configuration", stage="dhcp")
        manager.active[device] = active_network(interface=device)
        return manager.active[device]

    monkeypatch.setattr(manager, "start_network", start_network)
    monkeypatch.setattr(
        manager, "get_status",
        lambda device: manager.active[device].status() if device in manager.active
        else NetworkStatus(interface=device, active=False),
    )
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
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
    assert status["status"]["health"] != "degraded"
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


def test_the_same_create_sent_twice_at_once_starts_one_ap_and_both_get_202(api, context):
    client, headers, url, script, manager = api
    script["release"].clear()
    inside, go = threading.Event(), threading.Event()

    def slow_validation(*_args, **_kwargs):
        inside.set()
        go.wait(5)

    context.channels.validate_network.side_effect = slow_validation
    answers = []
    first = threading.Thread(
        target=lambda: answers.append(client.post(f"{url}/network", headers=headers, json=BODY).status_code),
    )
    first.start()
    assert inside.wait(5)  # the first request is past the job check, not yet registered
    context.channels.validate_network.side_effect = None
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
def real_start(monkeypatch, context, app):
    """Background creates with the real start_network: hostapd and DHCP are fakes that track state."""
    config = context.config
    manager = context.manager
    monkeypatch.setattr(context.channels, "validate_network", Mock())
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
    with TestClient(app) as client:
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


# --------------------------------------------------------------------------- unit-test-7


def test_a_cancel_that_times_out_is_503_then_the_real_state_and_a_working_stop(api, monkeypatch):
    """unit-test-7: a start that ignores the cancel; DELETE .../network answers 503 / 1006, then works."""
    client, headers, url, _script, manager = api
    monkeypatch.setattr(NetworkManager.cancel_start, "__defaults__", (0.05,))   # CANCEL_TIMEOUT
    finish = threading.Event()

    def start_ignoring_the_cancel(device, req, *args, cancelled=None, **kwargs):
        finish.wait(5)
        manager.active[device] = active_network(interface=device)
        return manager.active[device]

    monkeypatch.setattr(manager, "start_network", start_ignoring_the_cancel)
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    job = next(iter(manager.start_jobs.values()))
    device = job.reservation.device_id
    busy = client.delete(f"{url}/network", headers=headers)
    assert (busy.status_code, busy.json()["detail"]["code"]) == (503, 1006)
    assert busy.headers["Retry-After"] == "2"
    # REV-8: the job is kept while its thread runs: the repeated stop is busy again,
    # and a create with other settings is refused instead of starting a second thread.
    assert manager.start_jobs.get(device) is job
    again = client.delete(f"{url}/network", headers=headers)
    assert (again.status_code, again.json()["detail"]["code"]) == (503, 1006)
    other = client.post(f"{url}/network", headers=headers, json={**BODY, "wifi": {**BODY["wifi"], "ssid": "other"}})
    assert (other.status_code, other.json()["detail"]["code"]) == (409, 1008)
    assert manager.start_jobs.get(device) is job
    finish.set()
    job.thread.join(5)
    assert not job.thread.is_alive()
    state = _state(client, headers, url)
    assert state.status_code == 200
    assert (state.json()["active"], state.json()["runtime_state"]) == (True, None)
    assert client.delete(f"{url}/network", headers=headers).status_code == 200
    assert device not in manager.active
    assert manager.start_jobs == {}
    after = _state(client, headers, url).json()
    assert (after["active"], after["runtime_state"]) == (False, None)


# --------------------------------------------------------------------------- unit-test-9


@pytest.fixture
def tracked_start(real_start, monkeypatch):
    """real_start, with dnsmasq tracked too, so a DHCP server left running is a leftover."""
    client, headers, url, manager, stop = real_start
    running: set[str] = set()
    monkeypatch.setattr(
        manager.dhcp_server, "start", Mock(side_effect=lambda net_id, **_kwargs: running.add(net_id) or {}),
    )
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock(side_effect=running.discard))
    monkeypatch.setattr(manager.dhcp_server, "list_active", lambda: sorted(running))
    return client, headers, url, manager, stop


def _block_until_cancelled(monkeypatch, manager, phase, entered):
    """Make *phase* of the real start wait for the cancel, like a slow step (a DFS check, a slow dnsmasq)."""
    if phase == "hostapd":
        instances = manager.hostapd_manager._instances

        def hostapd_start(*, net_id, cancelled=None, **_kwargs):
            instances[net_id] = Mock()   # the process runs; hostapd waits for the radio
            entered.set()
            end = time.monotonic() + 5
            while not cancelled() and time.monotonic() < end:
                time.sleep(0.01)
            raise HostapdError(f"AP start on {net_id} cancelled")

        monkeypatch.setattr(manager.hostapd_manager, "start", hostapd_start)
        return
    owner, name = {"dhcp": (manager.dhcp_server, "start"), "nat": (manager.nat_manager, "enable_nat")}[phase]
    real = getattr(owner, name)

    def slow_step(*args, **kwargs):
        with manager.start_jobs_lock:
            job = next(iter(manager.start_jobs.values()))
        entered.set()
        job.cancel.wait(5)   # this step does not check the cancel: it ends, and the start goes on
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, slow_step)


@pytest.mark.parametrize("phase", ["hostapd", "dhcp", "nat"])
def test_release_during_each_phase_of_the_real_start_leaves_nothing(tracked_start, monkeypatch, phase):
    """unit-test-9: release while the real _start_network is blocked in hostapd, dnsmasq or NAT."""
    client, headers, url, manager, stop = tracked_start
    entered = threading.Event()
    _block_until_cancelled(monkeypatch, manager, phase, entered)
    body = network_body(
        ssid="phases", channel=6, encryption="open", band="2.4ghz", tx_power_level=4,
        internet_enabled=True, captive_portal=True,
    )
    assert client.post(f"{url}/network", headers=headers, json=body).status_code == 202
    assert entered.wait(5)
    job = next(iter(manager.start_jobs.values()))
    device = job.reservation.device_id
    # hostapd runs: something to clean up. (Not has_leftovers: NAT blocks under the firewall lock.)
    assert device in manager.hostapd_manager._instances
    if phase == "nat":
        assert device in manager.captive_portals and device in manager.dhcp_server.list_active()
    began = time.monotonic()
    released = client.delete(url, headers=headers)
    assert released.status_code == 200
    assert time.monotonic() - began < 3   # released while blocked, not after the step timed out
    job.thread.join(5)
    assert not job.thread.is_alive()
    assert manager.active == {}
    stop.assert_called_with(device)
    assert not manager.has_leftovers(device)   # hostapd, dnsmasq, portal, NAT and host guard
    assert not manager.host_guard.has(device)
    assert manager.isolation_manager.get_active_subnets() == []
    assert not manager.nat_manager.has_pending_network(device)
    assert manager.captive_portals == {}
    assert manager.start_jobs == {}
    assert _state(client, headers, url).json()["detail"]["reason"] == "reservation_released"
    again = client.post(RESERVE, headers=headers, json={"duration_seconds": 300, "interface": device})
    assert again.status_code == 200 and again.json()["interface"] == device


# --------------------------------------------------------------------------- unit-test-10


def test_release_during_the_pause_between_two_starts_returns_at_once(api, monkeypatch, context):
    """unit-test-10: radio failure, release during the 5 s pause: no second start, no quarantine."""
    client, headers, url, script, manager = api
    monkeypatch.setattr(network, "CREATE_RETRY_DELAYS", (5, 10))
    pauses: list[float] = []
    pausing = threading.Event()
    real_pause = network._pause

    def pause(cancel, seconds):
        pauses.append(seconds)
        pausing.set()
        return real_pause(cancel, seconds)   # cancel.wait: the release must wake it

    monkeypatch.setattr(network, "_pause", pause)
    script["outcome"] = "radio"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    job = next(iter(manager.start_jobs.values()))
    assert pausing.wait(5)
    began = time.monotonic()
    assert client.delete(url, headers=headers).status_code == 200
    assert time.monotonic() - began < 1
    assert job.done.is_set()
    assert pauses == [5]
    assert script["calls"] == 1   # no second start
    reservations = context.reservations
    assert reservations.recovery_snapshot() == {}   # no quarantine
    manager.recovery.schedule.assert_not_called()
    assert _state(client, headers, url).json()["detail"]["reason"] == "reservation_released"
    assert manager.start_jobs == {}


# --------------------------------------------------------------------------- unit-test-11 (b)


def test_start_failed_does_not_pass_to_the_next_reservation_after_an_expiry(api, context):
    """unit-test-11 (b): start_failed, then expiry and cleanup (not a release), then a new reservation."""
    client, headers, url, script, manager = api
    script["outcome"] = "stage"
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    _wait_until(lambda: _state(client, headers, url).json()["runtime_state"] == "start_failed")
    reservations = context.reservations
    rid = url.rsplit("/", 1)[1]
    old = reservations.get(rid)
    old.expires_at = time.time() - 1
    reservations.expire()   # the background sweep
    assert reservations.ended_reason(rid) == "reservation_expired"
    assert manager.start_jobs == {}   # gone at the expiry, not at the next call (REV-11 point 3)
    new = client.post(RESERVE, headers=headers, json={"duration_seconds": 300})
    assert new.status_code == 200 and new.json()["interface"] == old.device_id
    status = client.get("/api/v2/status", headers=headers).json()
    entry = next(a for a in status["antennas"] if a["interface"] == old.device_id)
    assert "runtime_state" not in entry
    state = _state(client, headers, f"{RESERVE}/{new.json()['reservation_id']}")
    assert state.status_code == 200
    assert (state.json()["runtime_state"], state.json()["error"]) == (None, None)
    assert manager.start_jobs == {}


# --------------------------------------------------------------------------- unit-test-12


def test_reservation_expiring_during_the_start(real_start, monkeypatch, context):
    """unit-test-12: the reservation expires while the start runs; the sweep then frees everything."""
    client, headers, url, manager, _stop = real_start
    instances = manager.hostapd_manager._instances
    entered, finish = threading.Event(), threading.Event()

    def slow_hostapd(*, net_id, **_kwargs):
        instances[net_id] = Mock()
        entered.set()
        finish.wait(5)

    monkeypatch.setattr(manager.hostapd_manager, "start", slow_hostapd)
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    assert entered.wait(5)
    job = next(iter(manager.start_jobs.values()))
    device = job.reservation.device_id
    job.reservation.expires_at = time.time() - 1
    gone = _state(client, headers, url)
    assert (gone.status_code, gone.json()["detail"]["reason"]) == (404, "reservation_expired")
    taken = client.post(RESERVE, headers=headers, json={"duration_seconds": 300})
    assert (taken.status_code, taken.json()["detail"]["code"]) == (409, 1005)
    finish.set()
    job.thread.join(5)
    assert not job.thread.is_alive()
    context.reservations.expire()
    assert device not in manager.active
    assert device not in instances
    assert not manager.has_leftovers(device)
    assert manager.start_jobs == {}
    free = client.post(RESERVE, headers=headers, json={"duration_seconds": 300})
    assert free.status_code == 200 and free.json()["interface"] == device


def test_create_when_the_channel_list_cannot_be_read_is_not_a_500(api, monkeypatch, context):
    """An antenna that disappears just before the create: `iw` fails, the route must not answer 500.

    Found by the USB e2e test on 2026-11-26 with an empty channel cache: the start
    is accepted (202) and the server decides with its own retries.
    """
    from wilab.network.commands import CommandError

    client, headers, url, _script, _manager = api
    monkeypatch.setattr(
        context.channels, "validate_network",
        Mock(side_effect=CommandError("Command 'iw' failed with code 1: ", returncode=1)),
    )
    created = client.post(f"{url}/network", headers=headers, json=BODY)
    assert created.status_code == 202, created.text


def test_start_whose_channels_cannot_be_read_is_a_radio_fault_when_the_antenna_is_gone(monkeypatch):
    from wilab.config import load_config
    from wilab.models import NetworkCreateRequest
    from wilab.network.commands import CommandError
    from wilab.wifi import manager as manager_module
    from wilab.wifi.manager import NetworkManager

    mgr = NetworkManager(load_config(), configured_devices())
    monkeypatch.setattr(
        mgr._channel_manager, "validate_network", Mock(side_effect=CommandError("iw failed", returncode=1)),
    )
    present = {"value": True}
    monkeypatch.setattr(manager_module, "interface_present", lambda _iface: present["value"])
    req = NetworkCreateRequest(ssid="x", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
    device = mgr.config.antennas[0].device_id
    for gone in (False, True):
        present["value"] = not gone
        with pytest.raises(StartupFailure, match="Cannot read the channels") as failure:
            mgr.start_network(device, req)
        assert failure.value.radio is gone
        assert failure.value.stage == "interface"


# --------------------------------------------------------------------------- unit-test-2


@pytest.fixture
def stuck_rollback(api, monkeypatch):
    """A start whose rollback fails when it is cancelled: hostapd is left and cannot be stopped."""
    client, headers, url, script, manager = api
    device = manager.config.antennas[0].device_id

    def start_network(dev, req, *args, cancelled=None, **kwargs):
        script["calls"] += 1
        while not script["release"].wait(0.01):
            if cancelled is not None and cancelled():
                manager.hostapd_manager._instances[dev] = Mock()
                raise StartupFailure(
                    "rollback failed: hostapd did not stop", stage="hostapd", kind=FailureKind.CLEANUP_FAILED,
                )
        raise AssertionError("the test cancels the start")

    def hostapd_stop(net_id):
        raise HostapdError("hostapd stuck in the kernel")

    monkeypatch.setattr(manager, "start_network", start_network)
    monkeypatch.setattr(manager.hostapd_manager, "stop", hostapd_stop)
    quarantine = Mock()
    monkeypatch.setattr(manager, "quarantine_radio", quarantine)
    script["release"].clear()
    assert client.post(f"{url}/network", headers=headers, json=BODY).status_code == 202
    _wait_until(lambda: script["calls"])
    yield client, headers, url, manager, device, quarantine
    manager.hostapd_manager._instances.pop(device, None)


def test_release_during_a_start_whose_rollback_fails_is_a_release(stuck_rollback):
    """REV-2: the release never fails, no quarantine; the cleanup goes to the background."""
    client, headers, url, manager, device, quarantine = stuck_rollback
    assert client.delete(url, headers=headers).status_code == 200
    assert _state(client, headers, url).json()["detail"]["reason"] == "reservation_released"
    quarantine.assert_not_called()
    status = client.get("/api/v2/status", headers=headers).json()
    antenna = next(a for a in status["antennas"] if a["interface"] == device)
    assert antenna.get("recovery_state") in (None, "ok")
    assert any(r["code"] == "cleanup_failed" for r in status["degraded_reasons"])
    # Not the client's to repeat any more (REV-9).
    assert not any(r["code"] == "network_stop_incomplete" for r in status["degraded_reasons"])
    assert manager.has_leftovers(device)


def test_stop_during_a_start_whose_rollback_fails_is_1012_and_keeps_the_reservation(stuck_rollback):
    """REV-2: DELETE .../network answers 503 / 1012, the reservation stays valid."""
    client, headers, url, _manager, _device, quarantine = stuck_rollback
    first = client.delete(f"{url}/network", headers=headers)
    if first.status_code == 503 and first.json()["detail"]["code"] == 1006:
        first = _wait_until(lambda: (r := client.delete(f"{url}/network", headers=headers)).status_code != 503
                            or r.json()["detail"]["code"] != 1006 and r)
    assert (first.status_code, first.json()["detail"]["code"]) == (503, 1012)
    assert client.get(url, headers=headers).status_code == 200
    quarantine.assert_not_called()
