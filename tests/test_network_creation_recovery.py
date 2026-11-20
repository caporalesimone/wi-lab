import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.api.routes import network
from wilab.models import NetworkStatus
from wilab.network.commands import CommandError
from wilab.network.dhcp import DhcpServerError
from wilab.reservation import ReservationManager
from wilab.wifi import recovery
from wilab.wifi.manager import StartupFailure

RESERVE = "/api/v1/device-reservation"
PAYLOAD = {
    "ssid": "recovery-test", "channel": 1, "band": "2.4ghz",
    "encryption": "open", "tx_power_level": 4,
}


@pytest.mark.parametrize("authorized_port", [None, "2-1"])
def test_three_attempts_keep_id_until_terminal_failure(monkeypatch, caplog, authorized_port):
    config = dependencies.get_config()
    radio = config.networks[0]
    monkeypatch.setattr(radio, "usb_recovery_port", authorized_port)
    manager = dependencies.get_manager(config)
    start = Mock(side_effect=StartupFailure("radio timeout", radio=True))
    schedule = Mock()
    monkeypatch.setattr(manager, "start_network", start)
    monkeypatch.setattr(manager.recovery, "schedule", schedule)
    now = 100
    monkeypatch.setattr(network, "monotonic", lambda: now)
    headers = {"Authorization": f"Bearer {config.auth_token}"}

    with TestClient(create_app()) as client:
        reservation = client.post(RESERVE, headers=headers, json={"duration_seconds": 60})
        assert reservation.status_code == 200
        rid = reservation.json()["reservation_id"]
        create = f"/api/v1/interface/{rid}/network"

        for expected_attempt, delay in enumerate((5, 10), start=1):
            result = client.post(create, headers=headers, json=PAYLOAD)
            assert (result.status_code, result.headers["Retry-After"]) == (409, str(delay))
            assert result.json()["detail"] == {
                "code": 1001, "reason": "retry_later", "reservation_invalidated": False,
            }
            assert client.get(f"{RESERVE}/{rid}", headers=headers).status_code == 200
            now += 1
            early = client.post(create, headers=headers, json=PAYLOAD)
            assert early.headers["Retry-After"] == str(delay - 1)
            assert start.call_count == expected_attempt
            now += delay - 1

        terminal = client.post(create, headers=headers, json=PAYLOAD)
        assert terminal.status_code == 500
        assert "Retry-After" not in terminal.headers
        assert terminal.json()["detail"]["code"] == 1003
        assert terminal.json()["detail"]["reservation_invalidated"] is True
        assert client.post(create, headers=headers, json=PAYLOAD).status_code == 404
        assert [c.kwargs["allow_internal_retry"] for c in start.call_args_list] == [True, False, False]

        blocked = client.post(RESERVE, headers=headers, json={"duration_seconds": 60})
        assert blocked.status_code == 503
        assert blocked.json()["detail"]["code"] == (1002 if authorized_port else 1003)
        assert blocked.json()["detail"]["reservation_invalidated"] is False
        assert blocked.headers.get("Retry-After") == ("10" if authorized_port else None)
        messages = [record.getMessage() for record in caplog.records if record.name == "wilab.api.errors"]
        assert messages == [
            "API failure operation=start_network http_status=500 detail_code=1003",
            f"API failure operation=create_reservation http_status=503 detail_code={1002 if authorized_port else 1003}",
        ]
        state = client.get("/api/v1/status", headers=headers).json()["networks"][0]
        assert state["recovery_state"] == ("recovering" if authorized_port else "unavailable")

        if authorized_port is None:
            schedule.assert_not_called()
        else:
            reservations = dependencies.get_reservation_manager(config)
            schedule.assert_called_once_with(reservations, radio.device_id, authorized_port, "2.4ghz", 1)
            reservations.finish_recovery(radio.device_id, recovered=True)
            assert client.post(RESERVE, headers=headers, json={"duration_seconds": 60}).status_code == 200


@pytest.mark.parametrize("verified_after", [2, None])
def test_usb_recovery_is_bounded_and_only_verified_radio_is_released(monkeypatch, verified_after):
    manager = dependencies.get_manager(dependencies.get_config())
    radio = manager.config.networks[0].device_id
    reservations = ReservationManager([radio])
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


def test_usb_recovery_refuses_unsafe_target(monkeypatch):
    manager = dependencies.get_manager(dependencies.get_config())
    radio = manager.config.networks[0].device_id
    reservations = ReservationManager([radio])
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
    """Fake ip/nmcli/usbreset layer where a host network manager re-raises the link."""

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
def test_usb_recovery_takes_back_a_radio_raised_by_host_managers(monkeypatch, upstream):
    manager = dependencies.get_manager(dependencies.get_config())
    radio = manager.config.networks[0].device_id
    reservations = ReservationManager([radio])
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
        assert not resets and not any(c[0] == "nmcli" or c[:3] == ["ip", "link", "set"] for c in host.commands)
        assert reservations.recovery_snapshot() == {radio: False}
    else:
        assert len(resets) == 1 and not host.up
        assert ["nmcli", "device", "set", radio, "managed", "no"] in host.commands
        probe.assert_called_once()
        assert reservations.recovery_snapshot() == {}


def test_api_viewers_share_recovery_guidance_and_examples():
    with TestClient(create_app()) as client:
        for url in ("/docs", "/redoc"):
            viewer = client.get(url)
            assert viewer.status_code == 200 and "/openapi.json" in viewer.text
        schema = client.get("/openapi.json").json()
    overview = schema["info"]["description"]
    assert "same ID and body after `Retry-After`" in overview
    assert "Do not retry creation or release it" in overview
    assert schema["tags"][0]["name"] == "System"
    paths = schema["paths"]
    create = paths["/api/v1/interface/{reservation_id}/network"]["post"]["responses"]
    reserve = paths[RESERVE]["post"]["responses"]
    assert "Retry-After" in create["409"]["headers"]
    assert "headers" not in create["500"]
    failure_content = create["500"]["content"]["application/json"]
    failures = failure_content["examples"]
    assert failures["device_unavailable"]["value"]["detail"]["code"] == 1003
    assert failures["device_unavailable"]["value"]["detail"]["reservation_invalidated"] is True
    assert failures["startup_failure"]["value"]["detail"]["code"] == 500
    generic_detail, terminal_detail = failure_content["schema"]["properties"]["detail"]["oneOf"]
    assert generic_detail["properties"]["code"]["enum"] == [500]
    assert terminal_detail["properties"]["code"]["enum"] == [1003]
    assert "discard the reservation ID" in failures["device_unavailable"]["summary"]
    assert create["409"]["content"]["application/json"]["examples"]["retry_later"]["value"]["detail"]["code"] == 1001
    assert reserve["503"]["content"]["application/json"]["examples"]["device_recovering"]["value"]["detail"]["code"] == 1002
    status = paths["/api/v1/status"]["get"]["responses"]["200"]["content"]["application/json"]["example"]
    assert status["networks"][0]["recovery_state"] == "recovering"
    assert not status["networks"][0]["reserved"]
    assert status["networks"][1]["runtime_state"] == "restoring_ap"
    content = paths["/api/v1/interface/{reservation_id}/network"]["get"]["responses"]["200"]["content"]["application/json"]
    assert "example" not in content
    assert content["examples"]["restoring_dhcp"]["value"]["runtime_state"] == "restoring_dhcp"


def test_framework_and_unexpected_api_errors_have_codes(monkeypatch, caplog):
    app = create_app()
    config = dependencies.get_config()
    headers = {"Authorization": f"Bearer {config.auth_token}"}

    with TestClient(app, raise_server_exceptions=False) as client:
        for method, path, status in (
            ("GET", "/api/v1/status", 401),
            ("GET", "/api/v1/unknown-path", 404),
            ("PUT", "/api/v1/status", 405),
        ):
            response = client.request(method, path)
            assert response.status_code == status
            assert response.json()["detail"]["code"] == status
        monkeypatch.setattr(
            dependencies.get_reservation_manager(config), "snapshot",
            Mock(side_effect=RuntimeError("internal detail must not be sent")),
        )
        response = client.get("/api/v1/status", headers=headers)
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == 500
        assert "internal detail must not be sent" not in response.text
        assert [record.getMessage() for record in caplog.records if record.name == "wilab.api.errors"] == [
            "API failure operation=system_status http_status=500 detail_code=500",
        ]


@pytest.mark.parametrize("cancel", [None, "release", "expiry"])
def test_watchdog_restores_original_network_or_cleans_up_on_cancellation(monkeypatch, cancel):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    device = reservation.device_id
    deadline = reservation.expires_at
    status = NetworkStatus(
        interface=device, active=True, ssid="original", channel=1, band="2.4ghz",
        encryption="open", tx_power_level=4, internet_enabled=True,
    )
    release = Mock()
    monkeypatch.setattr(manager, "release_device", release)

    def start(target, request, expires_at, *, allow_internal_retry):
        assert target == device
        assert request.ssid == "original" and request.internet_enabled is True
        assert expires_at == deadline and not allow_internal_retry
        if cancel == "release":
            reservation.release_requests += 1
        if cancel == "expiry":
            reservation.expires_at = 0

    restart = Mock(side_effect=start)
    monkeypatch.setattr(manager, "start_network", restart)
    manager.watchdog._restore_ap(reservations, reservation, status, False)
    restart.assert_called_once()
    assert release.call_count == (2 if cancel else 1)
    if not cancel:
        assert reservations.get(reservation.reservation_id) is reservation


def test_watchdog_dhcp_failure_does_not_restart_ap_or_schedule_usb(monkeypatch):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    device = reservation.device_id
    status = NetworkStatus(interface=device, active=True, subnet="192.0.2.0/24")
    stop = Mock()
    start = Mock(side_effect=DhcpServerError("daemon failed"))
    restart_ap = Mock()
    monkeypatch.setattr(manager.dhcp_server, "stop", stop)
    monkeypatch.setattr(manager.dhcp_server, "start", start)
    monkeypatch.setattr(manager, "start_network", restart_ap)

    manager.watchdog._restore_dhcp(reservations, reservation, status)
    assert [call.args for call in stop.call_args_list] == [(device,), (device,)]
    start.assert_called_once_with(device, device, status.subnet, config.dns_server)
    restart_ap.assert_not_called()
    assert reservations.get(reservation.reservation_id) is reservation
    assert not reservations.recovery_snapshot()
    assert manager.watchdog.state(reservation) == "dhcp_failed"


def test_runtime_recovery_status_is_reported_without_reading_radio(monkeypatch):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    monkeypatch.setitem(manager.watchdog.states, reservation.device_id, (reservation, "restoring_ap"))
    radio_status = Mock(side_effect=AssertionError("Should not query the recovering radio"))
    monkeypatch.setattr(manager, "get_status", radio_status)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    path = f"/api/v1/interface/{reservation.reservation_id}/network"

    with TestClient(create_app()) as client:
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and not response.json()["active"]
        assert response.json()["runtime_state"] == "restoring_ap"
        expiry = response.json()["expires_at"]
        assert expiry.endswith("Z")
        reserved = client.get(f"/api/v1/device-reservation/{reservation.reservation_id}", headers=headers)
        assert reserved.status_code == 200 and reserved.json()["expires_at"] == expiry
        create = client.post(path, headers=headers, json=PAYLOAD)
        assert create.status_code == 409 and "Retry-After" not in create.headers
        system = client.get("/api/v1/status", headers=headers).json()
        assert system["status"] == "degraded"
        assert system["networks"][0]["runtime_state"] == "restoring_ap"
    radio_status.assert_not_called()


@pytest.mark.parametrize("ap_alive,checks", [(False, 1), (True, 3)])
def test_watchdog_waits_for_confirmed_ap_failure(monkeypatch, ap_alive, checks):
    config = dependencies.get_config()
    manager = dependencies.get_manager(config)
    reservations = dependencies.get_reservation_manager(config)
    reservation = reservations.create(60)
    device = reservation.device_id
    status = NetworkStatus(interface=device, active=True)
    monkeypatch.setitem(manager.active, device, status)
    monkeypatch.setattr(manager.hostapd_manager, "is_running", Mock(return_value=ap_alive))
    enabled = Mock(return_value=False)
    monkeypatch.setattr(manager.hostapd_manager, "is_enabled", enabled)
    readiness_at_restart = []
    restore = Mock(side_effect=lambda *_: readiness_at_restart.append(enabled.call_count))
    monkeypatch.setattr(manager.watchdog, "_restore_ap", restore)
    monkeypatch.setattr(manager.watchdog.stopping, "wait", Mock(side_effect=[False] * checks + [True]))

    manager.watchdog._watch(reservations, device)
    restore.assert_called_once_with(reservations, reservation, status, False)
    assert readiness_at_restart == [checks if ap_alive else 0]


def test_recovery_probe_checks_ap_and_dhcp_and_tears_down_on_failure(monkeypatch):
    manager = dependencies.get_manager(dependencies.get_config())
    device = manager.config.networks[0].device_id
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
