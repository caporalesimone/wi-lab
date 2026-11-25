"""Create/delete cycles and a long-running network on every antenna (HAP-1 soak)."""

import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from wilab_e2e import Server, WiLab, detail_code

RADIOS = [("2.4ghz", 6), ("5ghz", 36)]


def test_create_delete_cycles_on_all_antennas(wilab: WiLab, server: Server) -> None:
    cycles = int(os.environ.get("WILAB_E2E_CYCLES", "10"))
    start = time.time()
    antennas = [wilab.reserve(interface) for interface in wilab.interfaces()]

    def run(index: int) -> Counter:
        antenna = antennas[index]
        band, channel = RADIOS[index % len(RADIOS)]
        results: Counter = Counter()
        for _ in range(cycles):
            response = wilab.create(antenna, ssid=f"wilab-e2e-{index}", band=band, channel=channel)
            results[(response.status_code, detail_code(response))] += 1
            results[("delete", wilab.delete_network(antenna))] += 1
        return results

    with ThreadPoolExecutor(len(antennas)) as pool:
        per_antenna = list(pool.map(run, range(len(antennas))))

    for antenna, results in zip(antennas, per_antenna, strict=True):
        assert results == Counter({(200, None): cycles, ("delete", 200): cycles}), antenna.display_name
        entry = wilab.device(antenna.interface)
        assert not entry.get("recovery_state"), entry
    journal = server.journal(start)
    assert "quarantin" not in journal.lower()
    assert "Traceback" not in journal


@pytest.mark.slow
def test_network_stays_up_for_15_minutes(wilab: WiLab, server: Server) -> None:
    antenna = wilab.reserve()
    start = time.time()
    response = wilab.create(antenna, ssid="Caffè ☕")
    assert response.status_code == 200, response.text
    anomalies = []
    end = time.monotonic() + 15 * 60
    while time.monotonic() < end:
        status = wilab.status()
        entry = wilab.device(antenna.interface)
        if entry.get("runtime_state") or entry.get("recovery_state") or status["status"] == "degraded":
            anomalies.append((time.strftime("%H:%M:%S"), status["status"], entry))
        time.sleep(10)
    assert anomalies == []
    assert wilab.http.get(f"/reservations/{antenna.reservation_id}/network").status_code == 200
    assert server.iw_info(antenna.interface).get("type") == "AP"
    assert "AP restart" not in server.journal(start)
