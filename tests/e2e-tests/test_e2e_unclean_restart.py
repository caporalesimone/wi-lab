"""STAB-4: after an unclean shutdown the next start leaves no stale shaping, address or file.

The service is killed with SIGKILL (only the main process) while a network
runs a degraded QoS profile; systemd restarts it (Restart=always). Needs
WILAB_E2E_RESTART=1: every client of the service loses its reservations.
"""

import time

import httpx
import pytest
from wilab_e2e import Server, WiLab, wait_for


def _api_up(wilab: WiLab, since: float, server: Server) -> bool:
    try:
        return server.service_started_at() > since and wilab.http.get("/status").status_code == 200
    except (httpx.HTTPError, ValueError):
        return False


@pytest.mark.service_restart
def test_unclean_restart_cleans_shaping_addresses_and_runtime_files(wilab: WiLab, server: Server) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    profiles = wilab.http.get("/qos/profiles").json()
    assert isinstance(profiles, list) and profiles, "no QoS profile in the catalogue"
    started = wilab.http.post(
        f"/reservations/{antenna.reservation_id}/qos/profile", json={"profile_id": profiles[0]["id"]},
    )
    assert started.status_code == 200, started.text
    assert wait_for(lambda: "htb" in server.qdiscs(antenna.interface) or "netem" in server.qdiscs(antenna.interface),
                    timeout=15, interval=1)

    before = time.time()
    server.kill_service_main()
    # Restart=always waits RestartSec (10 s) before starting again.
    assert wait_for(lambda: _api_up(wilab, before, server), timeout=90, interval=2), "service did not come back"
    journal = server.journal(before)

    leftovers = server.qdiscs(antenna.interface)
    assert "netem" not in leftovers and "htb" not in leftovers, leftovers
    assert server.wilab_ifbs() == []
    assert server.ipv4_addresses(antenna.interface) == []
    assert "Existing dnsmasq PID file" not in journal

    # The old reservation is gone with the process; a new one gets a working network.
    wilab.reserved.clear()
    again = wilab.reserve(interface=antenna.interface)
    assert wilab.create(again).status_code == 200
