"""API-only checks from the tester's plan (fable-todo.md, "Test per il tester").

These tests use only the public API, so they behave the same from the
Wi-Lab machine or from an external one. A few also read `iw` to compare
the API with the radio. Tests for IDs that are not fixed yet are marked
`xfail` (not strict): they report XPASS once the fix lands, and the mark is
then removed.
"""

import http.client
import os
import threading
import time
from urllib.parse import urlsplit

import pytest
from wilab_e2e import Server, WiLab, detail_code


def pending(fable_id: str):
    return pytest.mark.xfail(reason=f"{fable_id} not fixed yet", strict=False)


def _raw_get(path: str) -> int:
    """GET a path exactly as written (no dot-segment normalisation), without auth."""
    url = urlsplit(os.environ.get("WILAB_E2E_URL", "http://localhost:8080"))
    conn = http.client.HTTPConnection(url.hostname or "localhost", url.port or 80, timeout=10)
    try:
        conn.putrequest("GET", path, skip_accept_encoding=True)
        conn.endheaders()
        return conn.getresponse().status
    finally:
        conn.close()


# --------------------------------------------------------------------------- security

@pending("SEC-1")
@pytest.mark.parametrize("path", ["//etc/passwd", "/../config.yaml", "/%2e%2e/config.yaml"])
def test_static_files_never_leave_the_frontend(wilab: WiLab, path: str) -> None:
    assert _raw_get(path) == 404


@pending("SEC-2")
def test_debug_does_not_expose_other_clients_reservation_ids(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    debug = wilab.http.get("/debug")
    assert debug.status_code in (200, 403, 404)
    assert antenna.reservation_id not in debug.text


# --------------------------------------------------------------------------- request contract

@pending("API-10")
def test_unknown_create_field_is_rejected(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    response = wilab.create(antenna, **{"captive-portal": True})
    assert response.status_code == 422, response.text


@pending("API-5")
def test_create_returns_the_network_state(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    response = wilab.create(antenna)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("active") is True and body.get("ssid") == "wilab-e2e", body


def test_actions_without_a_network_share_one_status_code(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    rid = antenna.reservation_id
    profiles = wilab.http.get("/qos/profiles").json()
    first_profile = profiles[0]["id"] if isinstance(profiles, list) and profiles else "none"
    codes = {
        "internet/enable": wilab.http.post(f"/interface/{rid}/internet/enable").status_code,
        "qos/profile": wilab.http.post(
            f"/interface/{rid}/qos/profile", json={"profile_id": first_profile},
        ).status_code,
        "txpower": wilab.http.post(f"/interface/{rid}/txpower", json={"level": 2}).status_code,
    }
    assert set(codes.values()) == {409}, codes  # 409 / 1007 network_not_active (API-2)


# --------------------------------------------------------------------------- network behaviour

# hostapd_cli get_config: key_mgmt, and the cipher field that matters for each mode.
_EXPECTED_SECURITY: dict[str, dict[str, str | None]] = {
    "open": {"key_mgmt": None},
    "wpa1": {"wpa": "1", "key_mgmt": "WPA-PSK", "wpa_pairwise_cipher": "TKIP"},
    "wpa2": {"wpa": "2", "key_mgmt": "WPA-PSK", "rsn_pairwise_cipher": "CCMP"},
    "wpa3": {"wpa": "2", "key_mgmt": "SAE", "rsn_pairwise_cipher": "CCMP"},
    "wpa2-wpa3": {"wpa": "2", "key_mgmt": "WPA-PSK SAE", "rsn_pairwise_cipher": "CCMP"},
}


@pytest.mark.parametrize("encryption", list(_EXPECTED_SECURITY))
def test_every_encryption_starts_as_announced(wilab: WiLab, server: Server, encryption: str) -> None:
    """HAP-10: each encryption starts and hostapd runs exactly that security mode."""
    antenna = wilab.reserve()
    capabilities = wilab.device(antenna.interface).get("capabilities", {})
    if encryption not in capabilities.get("encryptions", []):
        pytest.skip(f"{encryption} not supported on {antenna.interface}")
    password = None if encryption == "open" else "e2e-pass-123"
    response = wilab.create(antenna, encryption=encryption, password=password)
    assert response.status_code == 200, response.text
    config = server.hostapd_config(antenna.interface)
    for key, value in _EXPECTED_SECURITY[encryption].items():
        assert config.get(key) == value, (key, config)


def test_wpa_is_refused(wilab: WiLab) -> None:
    """HAP-10: `wpa` used to create WPA2 silently; now 422 with the way out."""
    antenna = wilab.reserve()
    response = wilab.create(antenna, encryption="wpa")
    assert response.status_code == 422
    assert "wpa2" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("band", "channel", "width", "generation"),
    [
        ("5ghz", 36, 20, 4),
        ("5ghz", 36, 40, 4),
        ("5ghz", 36, 80, 5),
        ("5ghz", 36, 80, 6),
        ("2.4ghz", 6, 20, 6),
    ],
)
def test_channel_width_and_generation_reach_the_radio(
    wilab: WiLab, server: Server, band: str, channel: int, width: int, generation: int,
) -> None:
    """HAP-11: the radio runs at the requested width; GET network reports it."""
    antenna = wilab.reserve()
    capabilities = wilab.device(antenna.interface).get("capabilities", {})
    if width not in capabilities.get("channel_widths", {}).get(band, []) or (
        generation not in capabilities.get("wifi_generations", {}).get(band, [])
    ):
        pytest.skip(f"{width} MHz / Wi-Fi {generation} not supported on {antenna.interface} {band}")
    response = wilab.create(
        antenna, band=band, channel=channel, channel_width=width, wifi_generation=generation,
    )
    assert response.status_code == 200, response.text
    assert server.iw_channel_width(antenna.interface) == width
    network = wilab.http.get(f"/interface/{antenna.reservation_id}/network").json()
    assert network["radio"]["channel_width"] == {"requested": width, "reported": width}
    assert network["radio"]["wifi_generation"] == generation


def test_24ghz_40mhz_reports_the_width_it_got(wilab: WiLab, server: Server) -> None:
    """HAP-11: 40 MHz on 2.4 GHz is accepted; hostapd may fall back to 20 MHz (20/40 coexistence)."""
    antenna = wilab.reserve()
    response = wilab.create(antenna, channel=1, channel_width=40)
    assert response.status_code == 200, response.text
    network = wilab.http.get(f"/interface/{antenna.reservation_id}/network").json()
    width = network["radio"]["channel_width"]
    assert width["requested"] == 40
    assert width["reported"] in (20, 40)
    assert width["reported"] == server.iw_channel_width(antenna.interface)


def test_network_without_internet_is_not_degraded(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna, internet_enabled=False).status_code == 200
    assert wilab.status()["status"] == "ok"


@pending("BUG-7")
def test_txpower_reports_what_the_radio_applied(wilab: WiLab, server: Server) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    rid = antenna.reservation_id
    for level in (1, 2, 3, 4):
        assert wilab.http.post(f"/interface/{rid}/txpower", json={"level": level}).status_code == 200
        reported = wilab.http.get(f"/interface/{rid}/txpower").json()["tx_power"]["reported_dbm"]
        on_air = server.iw_txpower_dbm(antenna.interface)
        assert reported is not None and on_air is not None
        assert abs(reported - on_air) < 0.5, (level, reported, on_air)


@pending("PERF-6")
def test_txpower_change_is_fast(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    start = time.monotonic()
    response = wilab.http.post(f"/interface/{antenna.reservation_id}/txpower", json={"level": 3})
    assert response.status_code == 200
    assert time.monotonic() - start < 3


def test_status_never_flaps_to_degraded_during_create_delete(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    stop = threading.Event()
    seen: list[str] = []

    def poll() -> None:
        while not stop.is_set():
            seen.append(wilab.status()["status"])

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    try:
        for _ in range(10):
            response = wilab.create(antenna)
            assert response.status_code == 200, (response.status_code, detail_code(response))
            assert wilab.delete_network(antenna) == 200
    finally:
        stop.set()
        poller.join(timeout=5)
    assert "degraded" not in seen, f"{seen.count('degraded')} of {len(seen)} reads were degraded"


# --------------------------------------------------------------------------- RACE-1

def test_polling_during_a_create_gets_an_answer_within_the_busy_limit(wilab: WiLab) -> None:
    """RACE-1: GETs sent during a create answer 200, or 503/1006 with Retry-After, within ~5 s."""
    antenna = wilab.reserve()
    rid = antenna.reservation_id
    results: list[tuple[int, float, str | None, int | None]] = []
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            start = time.monotonic()
            response = wilab.http.get(f"/interface/{rid}/network")
            results.append((
                response.status_code, time.monotonic() - start,
                response.headers.get("Retry-After"), detail_code(response),
            ))

    pollers = [threading.Thread(target=poll, daemon=True) for _ in range(8)]
    for poller in pollers:
        poller.start()
    try:
        for _ in range(3):
            assert wilab.create(antenna).status_code == 200
            status_start = time.monotonic()
            wilab.status()
            assert time.monotonic() - status_start < 3
            assert wilab.delete_network(antenna) == 200
    finally:
        stop.set()
        for poller in pollers:
            poller.join(timeout=10)
    assert results
    for code, elapsed, retry_after, detail in results:
        assert elapsed < 7, (code, elapsed)
        assert code == 200 or (code == 503 and detail == 1006 and retry_after == "2"), (code, detail)
