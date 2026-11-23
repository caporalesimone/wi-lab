"""Watchdog on the real service: AP restores after hostapd dies (WD-1, WD-2)."""

import time

from wilab_e2e import Antenna, Server, WiLab, wait_for


def _kill_only_hostapd(server: Server) -> None:
    pids = server.pids("hostapd")
    # The fixture guarantees no other reservation, so the test's AP is the only one.
    assert len(pids) == 1, f"expected one hostapd, found {pids}"
    server.kill(pids[0])


def _restored(wilab: WiLab, antenna: Antenna) -> bool:
    response = wilab.http.get(f"/interface/{antenna.reservation_id}/network")
    body = response.json()
    return response.status_code == 200 and body.get("active") is True and not body.get("runtime_state")


def test_ap_is_restored_after_each_hostapd_crash(wilab: WiLab, server: Server) -> None:
    """WD-1: a second hostapd crash is restored too, with no quarantine."""
    antenna = wilab.reserve()
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
    assert wilab.http.get(f"/device-reservation/{antenna.reservation_id}").status_code == 200


def _network(wilab: WiLab, antenna: Antenna) -> dict:
    return wilab.http.get(f"/interface/{antenna.reservation_id}/network").json()


def test_failed_restore_is_reported_and_retried(wilab: WiLab, server: Server) -> None:
    """WD-2: a restore that fails for a non-radio reason shows restore_failed and is retried."""
    antenna = wilab.reserve()
    start = time.time()
    assert wilab.create(antenna).status_code == 200
    with server.hold_dhcp_port(antenna.interface):
        _kill_only_hostapd(server)
        # Restore fails on dnsmasq: reported, not silent, and not a quarantine.
        assert wait_for(
            lambda: _network(wilab, antenna).get("runtime_state") == "restore_failed", timeout=45, interval=2,
        )
        assert _network(wilab, antenna)["active"] is False
        assert wilab.status()["status"] == "degraded"
        assert not wilab.device(antenna.interface).get("recovery_state")
    # Port free again: the next retry (15 s, then 30 s) brings the network back.
    assert wait_for(lambda: _restored(wilab, antenna), timeout=90, interval=3)
    journal = server.journal(start)
    assert "next attempt in" in journal
    assert "restored after" in journal
    assert "quarantin" not in journal.lower()


def test_delete_stops_the_retries_and_keeps_the_reservation(wilab: WiLab, server: Server) -> None:
    """WD-2: DELETE .../network gives up a network the watchdog could not restore."""
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    with server.hold_dhcp_port(antenna.interface):
        _kill_only_hostapd(server)
        assert wait_for(
            lambda: _network(wilab, antenna).get("runtime_state") == "restore_failed", timeout=45, interval=2,
        )
        assert wilab.delete_network(antenna) == 200
        assert _network(wilab, antenna).get("runtime_state") is None
    time.sleep(35)  # past two retry delays: nothing may come back
    assert _network(wilab, antenna)["active"] is False
    assert wilab.http.get(f"/device-reservation/{antenna.reservation_id}").status_code == 200
    assert wilab.create(antenna).status_code == 200
