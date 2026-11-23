"""Watchdog on the real service: AP restores after hostapd dies (WD-1)."""

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
