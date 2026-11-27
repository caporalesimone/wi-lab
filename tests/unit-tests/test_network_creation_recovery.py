import json
from unittest.mock import Mock

import pytest
from conftest import active_network, create_network, network_body, registry_of
from fastapi.testclient import TestClient

from wilab.wifi.hostapd import Probe
from wilab.api import create_app
from wilab.api.routes import network
from wilab.models import NetworkStatus
from wilab.network.commands import CommandError
from wilab.network.dhcp import DhcpServerError
from wilab.reservation import ReservationManager
from wilab.wifi import recovery
from wilab.wifi.failures import FailureKind
from wilab.wifi.manager import StartupFailure

RESERVE = "/api/v2/reservations"
PAYLOAD = {
    "ssid": "recovery-test", "channel": 1, "band": "2.4ghz",
    "encryption": "open", "tx_power_level": 4,
}


@pytest.mark.parametrize("authorized_port", [None, "2-1"])
def test_one_create_retries_radio_failures_then_quarantines(monkeypatch, caplog, authorized_port, context, app):
    """A: the server pauses 5 s and 10 s and starts again itself; the client sends one create."""
    config = context.config
    radio = context.devices.all()[0]
    monkeypatch.setattr(radio, "usb_port", authorized_port)
    manager = context.manager
    start = Mock(side_effect=StartupFailure("radio timeout", kind=FailureKind.TRANSIENT_RADIO))
    schedule = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager.recovery, "schedule", schedule)
    pauses = []
    monkeypatch.setattr(network, "_pause", lambda _cancel, seconds: pauses.append(seconds) or False)
    headers = {"Authorization": f"Bearer {config.auth_token}"}

    with TestClient(app) as client:
        reservation = client.post(RESERVE, headers=headers, json={"duration_seconds": 300})
        assert reservation.status_code == 200
        rid = reservation.json()["reservation_id"]
        create = f"/api/v2/reservations/{rid}/network"

        accepted, terminal = create_network(client, headers, create, network_body(**PAYLOAD))
        assert accepted.status_code == 202
        assert pauses == [5, 10]
        assert terminal.status_code == 404  # API-4: a client state, not a server error
        assert terminal.json()["detail"]["reason"] == "reservation_invalidated"
        assert client.post(create, headers=headers, json=network_body(**PAYLOAD)).status_code == 404
        assert [c.kwargs["allow_internal_retry"] for c in start.call_args_list] == [True, False, False]

        blocked = client.post(RESERVE, headers=headers, json={"duration_seconds": 300})
        assert blocked.status_code == 503
        assert blocked.json()["detail"]["code"] == (1002 if authorized_port else 1003)
        assert blocked.json()["detail"]["message"]
        assert "reservation_invalidated" not in blocked.json()["detail"]  # a field of the old create
        assert blocked.headers.get("Retry-After") == ("10" if authorized_port else None)
        messages = [record.getMessage() for record in caplog.records if record.name == "wilab.api.errors"]
        assert messages == [   # the start ran in the job: no failed request for it
            f"API failure operation=create_reservation http_status=503 detail_code={1002 if authorized_port else 1003}",
        ]
        overall = client.get("/api/v2/status", headers=headers).json()
        # A quarantined adapter makes the service degraded even with no active network.
        assert (overall["status"]["health"], overall["active_networks"]) == ("degraded", 0)
        state = overall["antennas"][0]
        assert state["recovery_state"] == ("recovering" if authorized_port else "unavailable")

        if authorized_port is None:
            schedule.assert_not_called()
        else:
            reservations = context.reservations
            schedule.assert_called_once_with(reservations, radio.device_id, authorized_port, "2.4ghz", 1)
            reservations.finish_recovery(radio.device_id, recovered=True)
            assert client.post(RESERVE, headers=headers, json={"duration_seconds": 300}).status_code == 200


def test_radio_failure_recovered_by_a_later_start_answers_200(monkeypatch, context, app):
    """A: the second start succeeds after the 5 s pause; the client never sees an error."""
    config = context.config
    manager = context.manager
    calls = []

    def start(*args, **kwargs):
        calls.append(kwargs["allow_internal_retry"])
        if len(calls) == 1:
            raise StartupFailure("radio timeout", kind=FailureKind.TRANSIENT_RADIO)
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager, "get_status", lambda device: NetworkStatus(interface=device, active=True))
    pauses = []
    monkeypatch.setattr(network, "_pause", lambda _cancel, seconds: pauses.append(seconds) or False)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        rid = client.post(RESERVE, headers=headers, json={"duration_seconds": 300}).json()["reservation_id"]
        _, result = create_network(client, headers, f"{RESERVE}/{rid}/network", network_body(**PAYLOAD))
    assert result.status_code == 200 and result.json()["active"] is True
    assert (calls, pauses) == ([True, False], [5])


def test_reservation_too_short_for_another_start_is_released_without_quarantine(monkeypatch, context, app):
    """A: no time left for the next start -> 404 reservation_expired, antenna free again, no quarantine."""
    config = context.config
    manager = context.manager
    start = Mock(side_effect=StartupFailure("radio timeout", kind=FailureKind.TRANSIENT_RADIO))
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager.recovery, "schedule", Mock())
    pauses = []
    monkeypatch.setattr(network, "_pause", lambda _cancel, seconds: pauses.append(seconds) or False)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        reserved = client.post(RESERVE, headers=headers, json={"duration_seconds": 300}).json()
        monkeypatch.setattr(network, "START_MARGIN", 400)   # the next start would not fit
        _, result = create_network(
            client, headers, f"{RESERVE}/{reserved['reservation_id']}/network", network_body(**PAYLOAD),
        )
        assert result.status_code == 404
        assert result.json()["detail"]["reason"] == "reservation_expired"
        assert (start.call_count, pauses) == (1, [])
        reservations = context.reservations
        assert reservations.recovery_snapshot() == {}
        assert reserved["interface"] not in reservations.snapshot()


@pytest.mark.parametrize("verified_after", [2, None])
def test_usb_recovery_is_bounded_and_only_verified_radio_is_released(monkeypatch, verified_after, context):
    manager = context.manager
    radio = manager.config.antennas[0].device_id
    reservations = ReservationManager(registry_of(radio))
    reservations.quarantine(reservations.create(60), recovering=True)
    monkeypatch.setattr(recovery, "_require_idle", Mock())
    monkeypatch.setattr(recovery, "_quiesce", Mock())
    monkeypatch.setattr(recovery, "_usb_target", Mock(return_value=("002/003", "test-mac")))
    reset = Mock()
    monkeypatch.setattr(recovery, "execute_command", reset)
    wait = Mock(return_value=False)
    monkeypatch.setattr(manager.recovery._stopping, "wait", wait)
    if verified_after:
        verify = Mock(return_value=True)
    else:
        verify = Mock(side_effect=CommandError("not ready"))
    monkeypatch.setattr(manager.recovery, "_verify", verify)
    probe = Mock(side_effect=[CommandError("DHCP probe failed"), None]) if verified_after else Mock()
    monkeypatch.setattr(manager, "probe_recovered_radio", probe)

    manager.recovery._recover(reservations, radio, "2-1", "2.4ghz", 1)

    expected = verified_after or 10
    assert reset.call_count == expected
    assert reset.call_args.args[0] == ["usbreset", "002/003"]
    assert [c.args for c in wait.call_args_list] == [(60,)] * (expected - 1)
    assert reservations.recovery_snapshot() == ({} if verified_after else {radio: False})
    if verified_after:
        assert [c.args for c in probe.call_args_list] == [(radio, "2.4ghz", 1)] * 2
    else:
        probe.assert_not_called()


def test_usb_recovery_refuses_unsafe_target(monkeypatch, context):
    manager = context.manager
    radio = manager.config.antennas[0].device_id
    reservations = ReservationManager(registry_of(radio))
    reservations.quarantine(reservations.create(60), recovering=True)
    monkeypatch.setattr(recovery, "_require_idle", Mock())
    monkeypatch.setattr(recovery, "_quiesce", Mock())
    monkeypatch.setattr(recovery, "_usb_target", Mock(side_effect=CommandError("wrong USB port")))
    monkeypatch.setattr(manager.recovery._stopping, "wait", Mock(return_value=False))
    reset = Mock()
    monkeypatch.setattr(recovery, "execute_command", reset)

    manager.recovery._recover(reservations, radio, "2-1", "2.4ghz", 1)

    reset.assert_not_called()
    assert reservations.recovery_snapshot() == {radio: False}


class _HostLink:
    """Fake ip/usbreset layer where the re-enumerated link comes up again."""

    def __init__(self, radio: str, upstream: bool = False) -> None:
        self.radio, self.up, self.upstream = radio, True, upstream
        self.commands: list[list[str]] = []

    def run(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[:2] == ["ip", "-j"] and cmd[3:5] == ["route", "show"]:
            return json.dumps([{"dev": self.radio}] if self.upstream and cmd[2] == "-4" else [])
        if cmd[:4] == ["ip", "-j", "link", "show"]:
            return json.dumps([{"flags": ["BROADCAST", "UP"] if self.up else ["BROADCAST"]}])
        if cmd[:3] == ["ip", "link", "set"]:
            self.up = cmd[-1] == "up"
        if cmd[0] == "usbreset":
            self.up = True  # the re-enumerated device is managed and raised again
        return ""


@pytest.mark.parametrize("upstream", [False, True])
def test_usb_recovery_takes_back_a_radio_raised_by_host_managers(monkeypatch, upstream, context):
    manager = context.manager
    radio = manager.config.antennas[0].device_id
    reservations = ReservationManager(registry_of(radio))
    reservations.quarantine(reservations.create(60), recovering=True)
    host = _HostLink(radio, upstream=upstream)
    monkeypatch.setattr(recovery, "execute_command", host.run)
    monkeypatch.setattr(recovery, "execute_iw", lambda args: "type managed")
    monkeypatch.setattr(recovery, "_usb_target", Mock(return_value=("002/003", "test-mac")))
    monkeypatch.setattr(manager.recovery._stopping, "wait", Mock(return_value=False))
    monkeypatch.setattr(manager, "release_device", Mock())
    probe = Mock()
    monkeypatch.setattr(manager, "probe_recovered_radio", probe)

    manager.recovery._recover(reservations, radio, "2-1", "2.4ghz", 1)

    resets = [c for c in host.commands if c[0] == "usbreset"]
    if upstream:
        assert not resets and not any(c[:3] == ["ip", "link", "set"] for c in host.commands)
        assert reservations.recovery_snapshot() == {radio: False}
    else:
        assert len(resets) == 1 and not host.up
        assert ["ip", "link", "set", "dev", radio, "down"] in host.commands
        probe.assert_called_once()
        assert reservations.recovery_snapshot() == {}


def test_api_viewers_share_recovery_guidance_and_examples():
    with TestClient(create_app()) as client:
        for url in ("/docs", "/redoc"):
            viewer = client.get(url)
            assert viewer.status_code == 200 and "/openapi.json" in viewer.text
        schema = client.get("/openapi.json").json()
    overview = schema["info"]["description"]
    assert "1001" not in overview  # radio failures are retried by the server (A)
    assert "never release the ID" in overview and "poll `GET .../network`" in overview
    assert schema["tags"][0]["name"] == "System"
    paths = schema["paths"]
    create = paths["/api/v2/reservations/{reservation_id}/network"]["post"]["responses"]
    reserve = paths[RESERVE]["post"]["responses"]
    assert "headers" not in create["409"]
    # Asynchronous create: 202 starting; failures are read with GET .../network.
    assert create["202"]["content"]["application/json"]["example"]["runtime_state"] == "starting"
    assert "1013" not in str(create.get("500", {}))
    # Its only 503 is 1006 for the same body on a running network (REV-11), never recovery codes.
    assert {e["value"]["detail"]["code"] for e in create["503"]["content"]["application/json"]["examples"].values()} == {1006}
    assert {e["value"]["detail"]["code"] for e in create["409"]["content"]["application/json"]["examples"].values()} == {
        1008, 1009, 1012,
    }
    assert reserve["503"]["content"]["application/json"]["examples"]["device_recovering"]["value"]["detail"]["code"] == 1002
    status_examples = paths["/api/v2/status"]["get"]["responses"]["200"]["content"]["application/json"]["examples"]
    assert {name: e["value"]["status"] for name, e in status_examples.items()} == {
        "all_free": {"health": "good", "free_antennas": 2},
        "one_reserved": {"health": "good", "free_antennas": 1},
        "degraded_quarantine": {"health": "degraded", "free_antennas": 0},
    }
    status = status_examples["degraded_quarantine"]["value"]
    assert status["antennas"][0]["recovery_state"] == "unavailable"
    assert status["antennas"][0].get("reservation") is None  # OpenAPI drops null example values
    assert status["antennas"][1]["runtime_state"] == "restoring_ap"
    content = paths["/api/v2/reservations/{reservation_id}/network"]["get"]["responses"]["200"]["content"]["application/json"]
    assert "example" not in content
    assert content["examples"]["restoring_dhcp"]["value"]["runtime_state"] == "restoring_dhcp"


def test_framework_and_unexpected_api_errors_have_codes(monkeypatch, caplog, context, app):
    config = context.config
    headers = {"Authorization": f"Bearer {config.auth_token}"}

    with TestClient(app, raise_server_exceptions=False) as client:
        for method, path, status in (
            ("GET", "/api/v2/status", 401),
            ("GET", "/api/v2/unknown-path", 404),
            ("PUT", "/api/v2/status", 405),
        ):
            response = client.request(method, path)
            assert response.status_code == status
            assert response.json()["detail"]["code"] == status
        monkeypatch.setattr(
            context.reservations, "snapshot",
            Mock(side_effect=RuntimeError("internal detail must not be sent")),
        )
        response = client.get("/api/v2/status", headers=headers)
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == 500
        assert "internal detail must not be sent" not in response.text
        assert [record.getMessage() for record in caplog.records if record.name == "wilab.api.errors"] == [
            "API failure operation=system_status http_status=500 detail_code=500",
        ]


@pytest.mark.parametrize("cancel", [None, "release", "expiry"])
def test_watchdog_restores_original_network_or_cleans_up_on_cancellation(monkeypatch, cancel, context):
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(60)
    device = reservation.device_id
    deadline = reservation.expires_at
    status = active_network(
        interface=device, ssid="original", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4, internet_enabled=True,
    )
    release = Mock()
    monkeypatch.setattr(manager, "release_device", release)

    def start(target, request, expires_at, *, allow_internal_retry, cancelled):
        assert target == device
        assert request.ssid == "original" and request.internet_enabled is True
        assert expires_at == deadline and allow_internal_retry  # WD-2: same retries as a create
        assert not cancelled()  # REV-6: a release during the restore cancels it
        if cancel == "release":
            reservation.release_requests += 1
        if cancel == "expiry":
            reservation.expires_at = 0
        assert cancelled() is bool(cancel)

    restart = Mock(side_effect=start)
    monkeypatch.setattr(manager, "start_network", restart)
    manager.watchdog._restore_ap(reservations, reservation, status, False)
    restart.assert_called_once()
    assert release.call_count == (2 if cancel else 1)
    if not cancel:
        assert reservations.get(reservation.reservation_id) is reservation


def test_watchdog_dhcp_failure_does_not_restart_ap_or_schedule_usb(monkeypatch, context):
    config = context.config
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(60)
    device = reservation.device_id
    status = active_network(interface=device, subnet="192.0.2.0/24")
    stop = Mock()
    start = Mock(side_effect=DhcpServerError("daemon failed"))
    restart_ap = Mock()
    monkeypatch.setattr(manager.dhcp_server, "stop", stop)
    monkeypatch.setattr(manager.dhcp_server, "start", start)
    monkeypatch.setattr(manager, "start_network", restart_ap)

    manager.watchdog._restore_dhcp(reservations, reservation, status)
    assert [call.args for call in stop.call_args_list] == [(device,), (device,)]
    # A DHCP-only repair keeps the clients' leases (NET-7).
    assert all(call.kwargs == {"keep_leases": True} for call in stop.call_args_list)
    start.assert_called_once_with(device, device, status.subnet, config.dns_server)
    restart_ap.assert_not_called()
    assert reservations.get(reservation.reservation_id) is reservation
    assert not reservations.recovery_snapshot()
    assert manager.watchdog.state(reservation) == "dhcp_failed"


def test_runtime_recovery_status_is_reported_without_reading_radio(monkeypatch, context, app):
    config = context.config
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(60)
    monkeypatch.setitem(manager.watchdog.states, reservation.device_id, (reservation, "restoring_ap"))
    radio_status = Mock(side_effect=AssertionError("Should not query the recovering radio"))
    monkeypatch.setattr(manager, "get_status", radio_status)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v2/reservations/{reservation.reservation_id}/network"

    with TestClient(app) as client:
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and not response.json()["active"]
        assert response.json()["runtime_state"] == "restoring_ap"
        expiry = response.json()["reservation"]["expires_at"]
        assert expiry.endswith("Z")
        reserved = client.get(f"/api/v2/reservations/{reservation.reservation_id}", headers=headers)
        assert reserved.status_code == 200 and reserved.json()["expires_at"] == expiry
        create = client.post(path, headers=headers, json=network_body(**PAYLOAD))
        assert create.status_code == 409 and "Retry-After" not in create.headers
        assert create.json()["detail"]["code"] == 1009  # restoration_in_progress
        system = client.get("/api/v2/status", headers=headers).json()
        assert system["status"]["health"] == "degraded"
        assert system["antennas"][0]["runtime_state"] == "restoring_ap"
    radio_status.assert_not_called()


@pytest.mark.parametrize("ap_alive,checks", [(False, 1), (True, 3)])
def test_watchdog_waits_for_confirmed_ap_failure(monkeypatch, ap_alive, checks, context):
    manager = context.manager
    reservations = context.reservations
    reservation = reservations.create(60)
    device = reservation.device_id
    status = active_network(interface=device)
    monkeypatch.setitem(manager.active, device, status)
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=ap_alive))
    enabled = Mock(return_value=Probe(False))
    monkeypatch.setattr(manager.hostapd_manager, "probe", enabled)
    readiness_at_restart = []
    restore = Mock(side_effect=lambda *_: readiness_at_restart.append(enabled.call_count))
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(manager.watchdog, "_pause", Mock(side_effect=[False] * checks + [True]))

    manager.watchdog._watch(reservations, device)
    restore.assert_called_once_with(reservations, reservation, status, False)
    assert readiness_at_restart == [checks if ap_alive else 0]


def test_recovery_probe_checks_ap_and_dhcp_and_tears_down_on_failure(monkeypatch, context):
    manager = context.manager
    device = manager.config.antennas[0].device_id
    ap = Mock()
    dhcp = Mock()
    teardown = Mock()
    monkeypatch.setattr(manager.hostapd_manager, "start", ap)
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", Mock(return_value=True))
    monkeypatch.setattr(manager.dhcp_server, "start", dhcp)
    monkeypatch.setattr(manager.dhcp_server, "is_running", Mock(return_value=False))
    monkeypatch.setattr(manager, "release_device", teardown)
    monkeypatch.setattr("wilab.wifi.manager.execute_ip", Mock())

    with pytest.raises(CommandError, match="not ready"):
        manager.probe_recovered_radio(device, "2.4ghz", 1)

    assert ap.call_args.kwargs["hidden"] and ap.call_args.kwargs["encryption"] == "wpa2"
    assert dhcp.call_args.kwargs["probe"] is True
    teardown.assert_called_once_with(device)
    assert device not in manager.active
