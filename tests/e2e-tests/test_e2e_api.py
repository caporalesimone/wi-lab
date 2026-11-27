"""API-only checks from the tester's plan (Fable-Notes.md, 5.4 "Test per il tester").

These tests use mostly the public API. A few also read `iw` to compare
the API with the radio, or the host (`hostapd_cli`, `iptables -S`, `ip`)
to check what a network left behind; those need the Wi-Lab machine. Tests for IDs that are not fixed yet are marked
`xfail` (not strict): they report XPASS once the fix lands, and the mark is
then removed.
"""

import http.client
import os
import threading
import time
import uuid
from urllib.parse import urlsplit

import pytest
from wilab_e2e import Server, WiLab, detail_code, network_body, parse_utc


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

@pytest.mark.parametrize("path", ["//etc/passwd", "/../config.yaml", "/%2e%2e/config.yaml"])
def test_static_files_never_leave_the_frontend(wilab: WiLab, path: str) -> None:
    assert _raw_get(path) == 404


def test_debug_is_removed(wilab: WiLab) -> None:
    """SEC-2 / API-1: no endpoint lists other clients' reservation IDs."""
    antenna = wilab.reserve()
    assert wilab.http.get("/debug").status_code == 404
    assert antenna.reservation_id not in wilab.http.get("/status").text
    assert antenna.reservation_id not in wilab.http.get("/monitoring").text


# --------------------------------------------------------------------------- request contract

def test_unknown_create_field_is_rejected(wilab: WiLab) -> None:
    """API-10: a typo is refused with the field path."""
    antenna = wilab.reserve()
    response = wilab.create(antenna, **{"captive-portal": True})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["message"].startswith("captive-portal: ")


def test_create_returns_the_network_state(wilab: WiLab) -> None:
    """API-5: the polling of a create ends with the network as GET .../network reports it."""
    antenna = wilab.reserve()
    response = wilab.create(antenna)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("active") is True and body["wifi"]["ssid"] == "wilab-e2e", body


def test_create_is_asynchronous_and_idempotent(wilab: WiLab) -> None:
    """The create answers 202 at once, the polling ends with the network, the same body is 200."""
    antenna = wilab.reserve()
    url = f"/reservations/{antenna.reservation_id}/network"
    body = network_body(ssid="wilab-async", channel=6, band="2.4ghz", encryption="open", tx_power_level=2)
    started = time.monotonic()
    accepted = wilab.http.post(url, json=body)
    assert accepted.status_code == 202, accepted.text
    assert time.monotonic() - started < 3
    assert accepted.json()["runtime_state"] == "starting"
    assert set(accepted.json()) == set(wilab.http.get(url).json())  # the schema of GET
    deadline = time.monotonic() + 120
    while (state := wilab.http.get(url).json())["runtime_state"] == "starting":
        assert time.monotonic() < deadline
        time.sleep(1)
    assert state["active"] is True and state["runtime_state"] is None, state
    again = wilab.http.post(url, json=body)
    assert again.status_code == 200 and again.json()["active"] is True


def test_release_during_a_start_answers_at_once(wilab: WiLab, server: Server) -> None:
    """A Suite Teardown never waits for a long start: the release cancels it.

    e2e-test-3: the cancelled start leaves nothing (hostapd, dnsmasq, Wi-Lab
    rules, IPv4 address), so a reserve and a create on the same antenna work
    at once. Reads the host with `pgrep`, `ip` and `iptables -S` (root).
    """
    antenna = wilab.reserve()
    rid = antenna.reservation_id
    body = network_body(ssid="wilab-cancel", channel=6, band="2.4ghz", encryption="open", tx_power_level=2)
    assert wilab.http.post(f"/reservations/{rid}/network", json=body).status_code == 202
    started = time.monotonic()
    assert wilab.http.delete(f"/reservations/{rid}").status_code == 200
    assert time.monotonic() - started < 15
    wilab.reserved.remove(rid)
    gone = wilab.http.get(f"/reservations/{rid}/network")
    assert (gone.status_code, gone.json()["detail"]["reason"]) == (404, "reservation_released")

    assert server.pids("hostapd") == []   # the fixture keeps every other antenna idle
    assert server.dnsmasq_pids(antenna.interface) == []
    assert server.wilab_rules(antenna.interface) == []
    assert server.ipv4_addresses(antenna.interface) == []
    again = wilab.reserve(antenna.interface)
    response = wilab.create(again)
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- reservations

def test_reserve_a_given_antenna(wilab: WiLab) -> None:
    """e2e-test-4: reserve with `interface` gets that antenna, or says why not."""
    interfaces = wilab.interfaces()
    wanted = interfaces[-1]   # not the one a reserve without `interface` would pick
    first = wilab.http.post("/reservations", json={"duration_seconds": 3600, "interface": wanted})
    assert first.status_code == 200, first.text
    reservation = first.json()
    wilab.reserved.append(reservation["reservation_id"])
    assert reservation["interface"] == wanted

    taken = wilab.http.post("/reservations", json={"duration_seconds": 3600, "interface": wanted})
    assert (taken.status_code, detail_code(taken)) == (409, 1005), taken.text
    detail = taken.json()["detail"]
    assert detail["next_available_at"] == reservation["expires_at"], (detail, reservation)
    assert 0 < detail["next_available_in"] <= 3600

    for other in interfaces:
        if other != wanted:
            assert wilab.reserve(other).interface == other

    unknown = wilab.http.post("/reservations", json={"duration_seconds": 3600, "interface": "wilab-none0"})
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["detail"]["message"].startswith("interface: "), unknown.text


def test_released_and_unknown_ids_answer_404_with_the_reason(wilab: WiLab) -> None:
    """e2e-test-5: a released ID and an ID that never existed, on every call with an ID."""
    antenna = wilab.reserve()
    assert wilab.http.delete(f"/reservations/{antenna.reservation_id}").status_code == 200
    wilab.reserved.remove(antenna.reservation_id)
    answers = wilab.gone_answers(antenna.reservation_id)
    assert set(answers.values()) == {(404, "reservation_released")}, answers

    answers = wilab.gone_answers(str(uuid.uuid4()))
    assert set(answers.values()) == {(404, "reservation_not_found")}, answers


def test_expired_id_answers_404_with_the_reason(wilab: WiLab) -> None:
    """e2e-test-5: a reservation of `min_seconds` (60 s by default) left to expire. Takes about 65 s.

    The `reservation_invalidated` case is checked in test_e2e_device_loss.py,
    where an antenna is quarantined.
    """
    duration = wilab.status()["reservation_policy"]["min_seconds"]
    if duration > 90:
        pytest.skip(f"min_timeout is {duration} s; this test needs a reservation of 90 s at most")
    antenna = wilab.reserve(duration=duration)
    expires_at = parse_utc(wilab.http.get(f"/reservations/{antenna.reservation_id}").json()["expires_at"])
    time.sleep(max(0.0, expires_at - time.time()) + 1)
    wilab.reserved.remove(antenna.reservation_id)
    answers = wilab.gone_answers(antenna.reservation_id)
    assert set(answers.values()) == {(404, "reservation_expired")}, answers


def test_actions_without_a_network_share_one_status_code(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    rid = antenna.reservation_id
    profiles = wilab.http.get("/qos/profiles").json()
    first_profile = profiles[0]["id"] if isinstance(profiles, list) and profiles else "none"
    codes = {
        "internet/enable": wilab.http.post(f"/reservations/{rid}/internet/enable").status_code,
        "qos/profile": wilab.http.post(
            f"/reservations/{rid}/qos/profile", json={"profile_id": first_profile},
        ).status_code,
        "txpower": wilab.http.post(f"/reservations/{rid}/txpower", json={"tx_power_level": 2}).status_code,
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
    if encryption not in wilab.antenna(antenna.interface)["encryptions"]:
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
    if not wilab.offers(antenna.interface, band, channel, width, generation):
        pytest.skip(f"{width} MHz / Wi-Fi {generation} not supported on {antenna.interface} {band}")
    response = wilab.create(
        antenna, band=band, channel=channel, channel_width=width, wifi_generation=generation,
    )
    assert response.status_code == 200, response.text
    assert server.iw_channel_width(antenna.interface) == width
    network = wilab.http.get(f"/reservations/{antenna.reservation_id}/network").json()
    assert network["radio"]["channel_width"] == {"requested": width, "reported": width}
    assert network["radio"]["wifi_generation"] == generation


def test_24ghz_40mhz_reports_the_width_it_got(wilab: WiLab, server: Server) -> None:
    """HAP-11: 40 MHz on 2.4 GHz is accepted; hostapd may fall back to 20 MHz (20/40 coexistence)."""
    antenna = wilab.reserve()
    response = wilab.create(antenna, channel=1, channel_width=40)
    assert response.status_code == 200, response.text
    network = wilab.http.get(f"/reservations/{antenna.reservation_id}/network").json()
    width = network["radio"]["channel_width"]
    assert width["requested"] == 40
    assert width["reported"] in (20, 40)
    assert width["reported"] == server.iw_channel_width(antenna.interface)


def test_network_without_internet_is_not_degraded(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna, internet_enabled=False).status_code == 200
    assert wilab.status()["service"]["health"] == "good"


@pending("BUG-7")
def test_txpower_reports_what_the_radio_applied(wilab: WiLab, server: Server) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    rid = antenna.reservation_id
    for level in (1, 2, 3, 4):
        assert wilab.http.post(f"/reservations/{rid}/txpower", json={"tx_power_level": level}).status_code == 200
        reported = wilab.http.get(f"/reservations/{rid}/txpower").json()["tx_power"]["reported_dbm"]
        on_air = server.iw_txpower_dbm(antenna.interface)
        assert reported is not None and on_air is not None
        assert abs(reported - on_air) < 0.5, (level, reported, on_air)


@pending("PERF-6")
def test_txpower_change_is_fast(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    assert wilab.create(antenna).status_code == 200
    start = time.monotonic()
    response = wilab.http.post(f"/reservations/{antenna.reservation_id}/txpower", json={"tx_power_level": 3})
    assert response.status_code == 200
    assert time.monotonic() - start < 3


def test_status_never_flaps_to_degraded_during_create_delete(wilab: WiLab) -> None:
    antenna = wilab.reserve()
    stop = threading.Event()
    seen: list[str] = []

    def poll() -> None:
        while not stop.is_set():
            seen.append(wilab.status()["service"]["health"])

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
            response = wilab.http.get(f"/reservations/{rid}/network")
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


def test_every_antenna_lists_options_without_a_reservation(wilab: WiLab) -> None:
    """Antennas API: readable with the token only, for every managed antenna."""
    assert wilab.http.get("/antennas").status_code == 404   # the list is antennas[] of /status
    for entry in wilab.status()["antennas"]:
        details = wilab.antenna(entry["interface"])
        assert details["bands"]["2.4ghz"]["channels"] or details["bands"]["5ghz"]["channels"]
        for options in details["bands"].values():
            assert all(c["frequency_mhz"] < 5925 for c in options["channels"])   # no 6 GHz
