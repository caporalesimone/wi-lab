"""The life of a network around its start and its end, on the real service.

A create that fails on a non-radio step (`start_failed`), a stop sent during a
start, and a reservation that expires with its network running. Each test
checks what is left on the host: hostapd, the radio mode (`iw`) and the
firewall rules Wi-Lab names after the interface.
"""

import time

import pytest
from wilab_e2e import (
    Antenna,
    Server,
    WiLab,
    detail_code,
    gone_reason,
    parse_utc,
    wait_for,
)


def _nothing_left(wilab: WiLab, server: Server, antenna: Antenna) -> None:
    """No AP, no hostapd and no Wi-Lab rule for the antenna (the fixture keeps the service idle)."""
    assert server.pids("hostapd") == []
    assert server.iw_info(antenna.interface).get("type") != "AP"
    assert server.wilab_rules(antenna.interface) == []


def test_non_radio_failure_ends_in_start_failed(wilab: WiLab, server: Server) -> None:
    """e2e-test-1: dnsmasq cannot bind UDP 67, so the start fails on DHCP and rolls back.

    The polling ends in `runtime_state: start_failed` with `error` 1013 / stage
    `dhcp`; the reservation stays valid, nothing is left on the host, `/status`
    is not degraded, `DELETE .../network` clears the error and a new create works.
    """
    antenna = wilab.reserve()
    # No network yet on this antenna, so the port is free and taken at once.
    with server.hold_dhcp_port(antenna.interface):
        accepted = wilab.post_network(antenna)
        assert accepted.status_code == 202, accepted.text
        response = wilab.wait_start(antenna, timeout=120)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["runtime_state"] == "start_failed", state
        assert state["active"] is False
        error = state["error"]
        assert (error["code"], error["reason"], error["stage"]) == (1013, "startup_failed", "dhcp"), error
        assert error["message"]

        assert wilab.http.get(f"/reservations/{antenna.reservation_id}").status_code == 200
        _nothing_left(wilab, server, antenna)
        status = wilab.status()
        assert status["status"]["health"] != "degraded", status["status"]["degraded_reasons"]
        assert wilab.device(antenna.interface).get("runtime_state") == "start_failed"

        assert wilab.delete_network(antenna) == 200
        cleared = wilab.network(antenna).json()
        assert cleared["runtime_state"] is None and cleared["error"] is None, cleared
    response = wilab.create(antenna)
    assert response.status_code == 200, response.text


def _stop(wilab: WiLab, antenna: Antenna) -> list[tuple[int, int | None]]:
    """DELETE .../network, repeated after `503 / 1006` as the API says; every answer."""
    answers: list[tuple[int, int | None]] = []
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = wilab.http.delete(f"/reservations/{antenna.reservation_id}/network")
        answers.append((response.status_code, detail_code(response)))
        if (response.status_code, detail_code(response)) != (503, 1006):
            break
        time.sleep(float(response.headers.get("Retry-After", "2")))
    return answers


def test_stop_during_a_start_cancels_it_and_keeps_the_reservation(wilab: WiLab, server: Server) -> None:
    """e2e-test-2: `DELETE .../network` while the start runs.

    On a DFS channel, when the antenna offers one, the start waits about 60 s
    for the radar check, so the stop surely lands inside it. Expected: `200`,
    or `503 / 1006` and then `200`; the reservation stays, the network is not
    active with no `runtime_state`, no AP and no rule is left, and the next
    create works.
    """
    antenna = wilab.reserve()
    dfs = wilab.offers(antenna.interface, "5ghz", 52, 20, 4)
    radio = {"band": "5ghz", "channel": 52} if dfs else {"band": "2.4ghz", "channel": 6}
    accepted = wilab.post_network(antenna, ssid="wilab-e2e-stop", **radio)
    assert accepted.status_code == 202, accepted.text
    if dfs:
        time.sleep(3)   # well inside the radar check
        assert wilab.network(antenna).json()["runtime_state"] == "starting"

    answers = _stop(wilab, antenna)
    assert answers[-1] == (200, None), answers
    assert set(answers[:-1]) <= {(503, 1006)}, answers

    assert wilab.http.get(f"/reservations/{antenna.reservation_id}").status_code == 200
    network = wilab.network(antenna).json()
    assert network["active"] is False and network["runtime_state"] is None, network
    _nothing_left(wilab, server, antenna)
    response = wilab.create(antenna)
    assert response.status_code == 200, response.text


def test_expiry_stops_the_network(wilab: WiLab, server: Server) -> None:
    """e2e-test-9: a 60 s reservation expires with its network running.

    Within about 10 s of the expiry `GET .../network` answers `404
    reservation_expired`, the radio is no longer an AP, no rule is left and
    `/status` shows the antenna free with no network. Takes about 75 s.
    """
    duration = wilab.status()["reservation_policy"]["min_seconds"]
    if duration > 90:
        pytest.skip(f"min_timeout is {duration} s; this test needs a reservation of 90 s at most")
    antenna = wilab.reserve(duration=duration)
    expires_at = parse_utc(wilab.http.get(f"/reservations/{antenna.reservation_id}").json()["expires_at"])
    assert wilab.create(antenna).status_code == 200
    assert server.iw_info(antenna.interface).get("type") == "AP"

    time.sleep(max(0.0, expires_at - time.time()))
    wilab.reserved.remove(antenna.reservation_id)   # nothing to release after the expiry

    def ended() -> bool:
        entry = wilab.device(antenna.interface)
        return (
            gone_reason(wilab.network(antenna)) == "reservation_expired"
            and entry["reservation"] is None and entry["network_active"] is False
            and server.iw_info(antenna.interface).get("type") != "AP"
        )

    assert wait_for(ended, timeout=12, interval=1), wilab.device(antenna.interface)
    assert server.pids("hostapd") == []
    assert server.wilab_rules(antenna.interface) == []


def test_stop_of_a_frozen_hostapd(wilab: WiLab, server: Server) -> None:
    """e2e-test-8: `SIGSTOP` to hostapd, then `DELETE .../network`.

    SIGKILL ends a stopped process, so the stop usually completes (`200`); a
    process stuck in the kernel answers `503 / 1012` instead. Both are allowed,
    each with its contract: the answer comes within about 17 s; with `1012` the
    network shows `stop_failed`, a create answers `409 / 1012`, and after
    `SIGCONT` the repeated DELETE answers `200`. Either way nothing is left.
    """
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    pids = server.pids("hostapd")
    assert len(pids) == 1, pids
    server.kill(pids[0], "STOP")
    try:
        began = time.monotonic()
        stopped = wilab.http.delete(f"/reservations/{antenna.reservation_id}/network", timeout=40)
        seconds = time.monotonic() - began
        print(f"\nDELETE with hostapd stopped: {stopped.status_code} in {seconds:.1f} s")
        assert seconds < 20, seconds
        if stopped.status_code == 503:
            assert detail_code(stopped) == 1012, stopped.text
            assert stopped.headers.get("Retry-After") == "5"
            assert wilab.network(antenna).json()["runtime_state"] == "stop_failed"
            again = wilab.post_network(antenna)
            assert (again.status_code, detail_code(again)) == (409, 1012), again.text
            server.kill(pids[0], "CONT")
            assert wait_for(lambda: wilab.delete_network(antenna) == 200, timeout=30, interval=5)
        else:
            assert stopped.status_code == 200, stopped.text
    finally:
        if pids[0] in server.pids("hostapd"):
            server.kill(pids[0], "CONT")
    assert wait_for(lambda: server.pids("hostapd") == [], timeout=15, interval=1)
    _nothing_left(wilab, server, antenna)
    # The antenna works at once for the next network.
    assert wilab.create(antenna).status_code == 200
