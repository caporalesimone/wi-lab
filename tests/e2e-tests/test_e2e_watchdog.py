"""Watchdog on the real service: AP restores after hostapd dies (WD-1, WD-2, PERF-4),
DHCP repair after dnsmasq dies (WD-3), the `restarts` counters of
GET .../network (e2e-test-6) and a create sent during a repair (e2e-test-7).

The watchdog budgets (3 AP restores and 3 DHCP restarts per hour per antenna)
live in the running service. Each test reserves an antenna that still has the
budget it needs, read from the journal, and skips when none has.
"""

import time

from wilab_e2e import (
    Antenna,
    Server,
    WiLab,
    detail_code,
    parse_utc,
    reserve_with_budget,
    wait_for,
)


def _kill_only_hostapd(server: Server) -> None:
    pids = server.pids("hostapd")
    # The fixture guarantees no other reservation, so the test's AP is the only one.
    assert len(pids) == 1, f"expected one hostapd, found {pids}"
    server.kill(pids[0])


def _restored(wilab: WiLab, antenna: Antenna) -> bool:
    response = wilab.http.get(f"/reservations/{antenna.reservation_id}/network")
    body = response.json()
    return response.status_code == 200 and body.get("active") is True and not body.get("runtime_state")


def test_ap_is_restored_after_each_hostapd_crash(wilab: WiLab, server: Server) -> None:
    """WD-1: a second hostapd crash is restored too, with no quarantine."""
    antenna = reserve_with_budget(wilab, server, ap=2)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    for crash in range(2):
        _kill_only_hostapd(server)
        # The watchdog ticks every 5 s; the restore takes about 1 s.
        assert wait_for(lambda: _restored(wilab, antenna), timeout=45, interval=2), f"crash {crash + 1}"
        assert server.iw_info(antenna.interface).get("type") == "AP"
        assert not wilab.device(antenna.interface).get("recovery_state")
        time.sleep(10)
    journal = server.journal(start)
    assert "quarantin" not in journal.lower()
    assert wilab.http.get(f"/reservations/{antenna.reservation_id}").status_code == 200


def test_hostapd_segfault_wakes_the_watchdog_and_the_control_connection_follows(
    wilab: WiLab, server: Server,
) -> None:
    """PERF-4: `kill -SEGV` of hostapd with the network up (47 segfaults in the 2-hour run).

    The control connection notices within about 3 s (a PING to a socket nobody
    reads), wakes the watchdog instead of leaving it to its 5 s tick, and the
    restore starts a new hostapd with its own connection. Nothing is
    quarantined, the counters say why, and the old connection is gone.
    """
    antenna = reserve_with_budget(wilab, server, ap=1)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    time.sleep(3)   # the monitor of the new AP is connected
    pids = server.pids("hostapd")
    assert len(pids) == 1, f"expected one hostapd, found {pids}"
    killed = time.monotonic()
    server.kill(pids[0], "SEGV")

    def restored_by_a_new_hostapd() -> bool:
        now = server.pids("hostapd")
        return len(now) == 1 and now[0] != pids[0] and _restored(wilab, antenna)

    assert wait_for(restored_by_a_new_hostapd, timeout=45, interval=0.5)
    seconds = time.monotonic() - killed
    print(f"\nhostapd SIGSEGV -> network restored in {seconds:.1f} s")
    body = _network(wilab, antenna)
    assert (body["restarts"]["ap"], body["restarts"]["last_reason"]) == (1, "hostapd_not_running"), body
    time.sleep(6)   # one more tick on the restored network: still healthy, no second restore
    assert _network(wilab, antenna)["restarts"]["ap"] == 1
    journal = server.journal(start)
    assert journal.count(f"Restoring AP on {antenna.interface} (") == 1
    assert "quarantin" not in journal.lower()
    # The monitor of the dead hostapd saw it before the restore closed that monitor.
    assert f"Control connection to hostapd on {antenna.interface} lost" in journal
    assert seconds < 15, f"restore took {seconds:.1f} s"


def _network(wilab: WiLab, antenna: Antenna) -> dict:
    return wilab.http.get(f"/reservations/{antenna.reservation_id}/network").json()


def test_failed_restore_is_reported_and_retried(wilab: WiLab, server: Server) -> None:
    """WD-2: a restore that fails for a non-radio reason shows restore_failed and is retried."""
    antenna = reserve_with_budget(wilab, server, ap=1)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    _kill_only_hostapd(server)
    with server.hold_dhcp_port(antenna.interface):   # taken when the watchdog stops dnsmasq
        # Restore fails on dnsmasq: reported, not silent, and not a quarantine.
        assert wait_for(
            lambda: _network(wilab, antenna).get("runtime_state") == "restore_failed", timeout=45, interval=2,
        )
        assert _network(wilab, antenna)["active"] is False
        assert wilab.status()["service"]["health"] == "degraded"
        assert not wilab.device(antenna.interface).get("recovery_state")
    # Port free again: the next retry (15 s, then 30 s) brings the network back.
    assert wait_for(lambda: _restored(wilab, antenna), timeout=90, interval=3)
    journal = server.journal(start)
    assert "next attempt in" in journal
    assert "restored after" in journal
    assert "quarantin" not in journal.lower()


def test_delete_stops_the_retries_and_keeps_the_reservation(wilab: WiLab, server: Server) -> None:
    """WD-2: DELETE .../network gives up a network the watchdog could not restore."""
    antenna = reserve_with_budget(wilab, server, ap=1)
    assert wilab.create(antenna).status_code == 200
    _kill_only_hostapd(server)
    with server.hold_dhcp_port(antenna.interface):   # taken when the watchdog stops dnsmasq
        assert wait_for(
            lambda: _network(wilab, antenna).get("runtime_state") == "restore_failed", timeout=45, interval=2,
        )
        assert wilab.delete_network(antenna) == 200
        assert _network(wilab, antenna).get("runtime_state") is None
    time.sleep(35)  # past two retry delays: nothing may come back
    assert _network(wilab, antenna)["active"] is False
    assert wilab.http.get(f"/reservations/{antenna.reservation_id}").status_code == 200
    assert wilab.create(antenna).status_code == 200


def _kill_only_dnsmasq(server: Server, antenna: Antenna) -> int:
    pids = server.dnsmasq_pids(antenna.interface)
    assert len(pids) == 1, f"expected one dnsmasq for {antenna.interface}, found {pids}"
    server.kill(pids[0])
    return pids[0]


def _dhcp_back(server: Server, antenna: Antenna, old_pid: int) -> bool:
    pids = server.dnsmasq_pids(antenna.interface)
    return len(pids) == 1 and pids[0] != old_pid


def test_dnsmasq_is_restarted_after_each_crash(wilab: WiLab, server: Server) -> None:
    """WD-3: a second dnsmasq crash is repaired too, with the AP kept up."""
    antenna = reserve_with_budget(wilab, server, dhcp=2)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    for crash in range(2):
        old = _kill_only_dnsmasq(server, antenna)
        assert wait_for(lambda old=old: _dhcp_back(server, antenna, old), timeout=30, interval=1), (
            f"crash {crash + 1}"
        )
        assert wait_for(lambda: _restored(wilab, antenna), timeout=15, interval=1)
        time.sleep(6)  # at least one more watchdog tick
        assert _network(wilab, antenna).get("runtime_state") is None
    journal = server.journal(start)
    assert journal.count(f"Restarting DHCP on {antenna.interface} (") == 2
    assert f"Restoring AP on {antenna.interface}" not in journal  # DHCP alone was enough
    assert "quarantin" not in journal.lower()


def test_failed_dhcp_restart_restores_the_whole_network(wilab: WiLab, server: Server) -> None:
    """WD-3: when dnsmasq cannot restart alone, the watchdog restores the network."""
    antenna = reserve_with_budget(wilab, server, ap=1, dhcp=1)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    _kill_only_dnsmasq(server, antenna)
    with server.hold_dhcp_port(antenna.interface):   # taken before the watchdog restarts dnsmasq
        # DHCP restart fails -> network restore -> fails on DHCP too -> restore_failed (WD-2).
        assert wait_for(
            lambda: _network(wilab, antenna).get("runtime_state") == "restore_failed", timeout=45, interval=2,
        )
    assert wait_for(lambda: _restored(wilab, antenna), timeout=90, interval=3)
    assert len(server.dnsmasq_pids(antenna.interface)) == 1
    journal = server.journal(start)
    assert "cannot be repaired alone; restarting the network" in journal
    assert "quarantin" not in journal.lower()


# --------------------------------------------------------------------------- restarts and creates during a repair

_NO_RESTARTS = {"ap": 0, "dhcp": 0, "last_at": None, "last_reason": None}


def _restarts(wilab: WiLab, antenna: Antenna) -> dict | None:
    """`restarts` of GET .../network; None while the device is busy (503 / 1006)."""
    response = wilab.network(antenna)
    return response.json()["restarts"] if response.status_code == 200 else None


def _within(stamp: str | None, start: float) -> bool:
    return stamp is not None and start - 1 <= parse_utc(stamp) <= time.time() + 1


def test_restarts_count_each_watchdog_repair(wilab: WiLab, server: Server) -> None:
    """e2e-test-6: `restarts` counts one AP restore and one DHCP restart, per reservation.

    The counters belong to the reservation: a stop and a new create keep them,
    a new reservation starts from zero.
    """
    antenna = reserve_with_budget(wilab, server, ap=1, dhcp=1)
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    assert _restarts(wilab, antenna) == _NO_RESTARTS

    _kill_only_hostapd(server)
    assert wait_for(lambda: (_restarts(wilab, antenna) or {}).get("ap") == 1, timeout=45, interval=2)
    assert wait_for(lambda: _restored(wilab, antenna), timeout=30, interval=2)
    after_ap = _restarts(wilab, antenna)
    assert after_ap is not None
    assert (after_ap["ap"], after_ap["dhcp"], after_ap["last_reason"]) == (1, 0, "hostapd_not_running"), after_ap
    assert _within(after_ap["last_at"], start), after_ap

    dhcp_start = time.time()
    old = _kill_only_dnsmasq(server, antenna)
    assert wait_for(lambda: _dhcp_back(server, antenna, old), timeout=30, interval=1)
    assert wait_for(lambda: _restored(wilab, antenna), timeout=15, interval=1)
    after_dhcp = _restarts(wilab, antenna)
    assert after_dhcp is not None
    assert (after_dhcp["ap"], after_dhcp["dhcp"], after_dhcp["last_reason"]) == (1, 1, "dnsmasq_not_running"), (
        after_dhcp
    )
    assert _within(after_dhcp["last_at"], dhcp_start), after_dhcp

    # A stop and a new create on the same reservation keep the counters.
    assert wilab.delete_network(antenna) == 200
    assert wilab.create(antenna).status_code == 200
    assert _restarts(wilab, antenna) == after_dhcp

    # A new reservation on the same antenna starts from zero.
    wilab.release(antenna)
    fresh = wilab.reserve(antenna.interface)
    assert _restarts(wilab, fresh) == _NO_RESTARTS


def test_create_during_a_repair_answers_1009_and_never_starts_a_second_ap(
    wilab: WiLab, server: Server,
) -> None:
    """e2e-test-7: a create with other settings sent while the watchdog restores the AP.

    Every answer is a refusal (`409 / 1009` during the repair, `409 / 1008`
    before the watchdog notices or after it is done, `503 / 1006` while the
    device is held): never a `202`, never a second hostapd. Once repaired, the
    network's own body answers `200` at once.
    """
    antenna = reserve_with_budget(wilab, server, ap=1)
    assert wilab.create(antenna).status_code == 200
    _kill_only_hostapd(server)

    answers: list[tuple[int, int | None]] = []
    states: list[str | None] = []
    most_hostapd = 0
    repaired = False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        response = wilab.post_network(antenna, ssid="wilab-e2e-other")
        answers.append((response.status_code, detail_code(response)))
        most_hostapd = max(most_hostapd, len(server.pids("hostapd")))
        network = wilab.network(antenna)
        if network.status_code == 200:
            states.append(network.json().get("runtime_state"))
            seen_repair = (409, 1009) in answers or "restoring_ap" in states
            if seen_repair and network.json().get("active") is True and states[-1] is None:
                repaired = True
                break
        time.sleep(0.2)

    assert repaired, f"no repair seen or not repaired in 60 s: answers {set(answers)}, states {set(states)}"
    assert set(answers) <= {(409, 1009), (409, 1008), (503, 1006)}, answers
    assert most_hostapd <= 1
    assert len(server.pids("hostapd")) == 1
    assert server.iw_info(antenna.interface).get("ssid") == "wilab-e2e"
    assert wilab.post_network(antenna).status_code == 200   # the network's own body
