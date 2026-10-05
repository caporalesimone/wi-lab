"""Error paths and edge behaviour of the API layer that the main suites do not exercise.

Everything the real hardware would do is replaced: these tests are about how the API
translates failures (409/404/500), authenticates, degrades its health report and serves the
web frontend.
"""

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.config import load_config
from wilab.models import NetworkStatus
from wilab.wifi.channels import ChannelManager
from wilab.wifi.manager import NetworkManager, TxPowerMismatchError

API = "/api/v1"


@pytest.fixture
def client():
    dependencies._config = None
    dependencies._manager = None
    dependencies._reservation_manager = None
    load_config()
    return TestClient(create_app())


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {load_config().auth_token}"}


@pytest.fixture
def rid(client, auth):
    resp = client.post(
        f"{API}/device-reservation", headers=auth,
        json={"duration_seconds": 3600, "required_capabilities": ["2.4ghz"]},
    )
    assert resp.status_code == 200
    return resp.json()["reservation_id"]


def raising(exc):
    def _raise(*args, **kwargs):
        raise exc
    return _raise


NETWORK_BODY = {
    "ssid": "T", "channel": 6, "band": "2.4ghz", "encryption": "open",
    "internet_enabled": False, "tx_power_level": 4,
}


class TestStartNetworkErrors:
    def post(self, client, auth, rid):
        return client.post(f"{API}/interface/{rid}/network", headers=auth, json=NETWORK_BODY)

    def test_a_network_that_is_already_active_is_409(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(
            NetworkManager, "start_network",
            raising(ValueError("Network on wls17 is already active")),
        )
        resp = self.post(client, auth, rid)
        assert resp.status_code == 409
        assert "already active" in resp.json()["detail"]

    def test_an_unknown_device_is_404(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(
            NetworkManager, "start_network", raising(ValueError("Unknown device_id wls99"))
        )
        assert self.post(client, auth, rid).status_code == 404

    def test_any_other_start_failure_is_500(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(
            NetworkManager, "start_network", raising(ValueError("hostapd exited"))
        )
        resp = self.post(client, auth, rid)
        assert resp.status_code == 500
        assert "hostapd exited" in resp.json()["detail"]


class TestRuntimeErrorMapping:
    def test_enabling_internet_reports_a_runtime_failure_as_500(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(
            NetworkManager, "enable_internet", raising(RuntimeError("iptables failed"))
        )
        resp = client.post(f"{API}/interface/{rid}/internet/enable", headers=auth)
        assert resp.status_code == 500 and "iptables failed" in resp.json()["detail"]

    def test_channel_listing_failure_is_500(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(ChannelManager, "get_channels", raising(RuntimeError("iw not found")))
        resp = client.get(f"{API}/interface/{rid}/network/available-channels", headers=auth)
        assert resp.status_code == 500

    def test_tx_power_of_an_unknown_device_is_404_for_get_and_post(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(NetworkManager, "get_tx_power_info", raising(ValueError("unknown")))
        monkeypatch.setattr(NetworkManager, "set_tx_power_level", raising(ValueError("unknown")))
        assert client.get(f"{API}/interface/{rid}/txpower", headers=auth).status_code == 404
        resp = client.post(f"{API}/interface/{rid}/txpower", headers=auth, json={"level": 2})
        assert resp.status_code == 404

    def test_tx_power_not_applied_by_the_hardware_is_422(self, client, auth, rid, monkeypatch):
        monkeypatch.setattr(
            NetworkManager, "set_tx_power_level",
            raising(TxPowerMismatchError("requested 2, hardware reports 4")),
        )
        resp = client.post(f"{API}/interface/{rid}/txpower", headers=auth, json={"level": 2})
        assert resp.status_code == 422


class TestAuthentication:
    def test_a_non_bearer_scheme_is_refused(self, client):
        resp = client.get(f"{API}/status", headers={"Authorization": "Basic dXNlcjpwdw=="})
        assert resp.status_code == 401

    def test_a_wrong_token_is_refused(self, client):
        resp = client.get(f"{API}/status", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_no_authorization_header_is_refused(self, client):
        assert client.get(f"{API}/status").status_code == 401


class TestBulkRelease:
    def test_releasing_everything_survives_a_network_that_will_not_stop(self, client, auth, rid, monkeypatch):
        """Best effort: a failing stop is logged, the reservations are released anyway."""
        mgr = dependencies.get_manager(dependencies.get_config())
        device = client.get(f"{API}/device-reservation/{rid}", headers=auth).json()["interface"]
        mgr.active[device] = NetworkStatus(interface=device, active=True)
        monkeypatch.setattr(mgr, "stop_network", raising(RuntimeError("cannot stop")))

        resp = client.delete(f"{API}/device-reservation", headers=auth)
        assert resp.status_code == 200 and resp.json()["released"] == 1
        assert client.get(f"{API}/device-reservation/{rid}", headers=auth).status_code == 404

    def test_releasing_one_reservation_survives_a_network_that_will_not_stop(self, client, auth, rid, monkeypatch):
        mgr = dependencies.get_manager(dependencies.get_config())
        device = client.get(f"{API}/device-reservation/{rid}", headers=auth).json()["interface"]
        mgr.active[device] = NetworkStatus(interface=device, active=True)
        monkeypatch.setattr(mgr, "stop_network", raising(RuntimeError("cannot stop")))
        assert client.delete(f"{API}/device-reservation/{rid}", headers=auth).status_code == 200


class TestDegradedHealth:
    @pytest.fixture
    def broken_checks(self, client, auth, monkeypatch):
        from wilab.api.routes import status as status_module

        mgr = dependencies.get_manager(dependencies.get_config())
        monkeypatch.setattr(mgr.dhcp_server, "status", lambda: {"running": True, "instances": []})
        monkeypatch.setattr(mgr.nat_manager, "status", raising(RuntimeError("iptables unavailable")))
        monkeypatch.setattr(mgr.nat_manager, "get_upstream_interface", raising(RuntimeError("no route")))
        monkeypatch.setattr(status_module, "execute_command", lambda *a, **k: "")
        return mgr

    def test_status_reports_failing_checks_instead_of_crashing(self, client, auth, broken_checks):
        resp = client.get(f"{API}/status", headers=auth)
        assert resp.status_code == 200
        checks = resp.json()["checks"]
        assert checks["iptables_nat"]["configured"] is False
        assert "iptables unavailable" in checks["iptables_nat"]["error"]
        assert checks["upstream_interface"]["reachable"] is False

    def test_status_is_standby_when_nothing_is_active(self, client, auth, broken_checks):
        assert client.get(f"{API}/status", headers=auth).json()["status"] == "standby"

    def test_status_is_degraded_when_a_network_is_active_and_a_check_fails(self, client, auth, broken_checks):
        broken_checks.active["wls17"] = NetworkStatus(interface="wls17", active=True)
        assert client.get(f"{API}/status", headers=auth).json()["status"] == "degraded"


class TestFrontendServing:
    """The API also serves the built web frontend; in CI there is no build, so fake one."""

    @pytest.fixture
    def web(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html>INDEX</html>")
        (tmp_path / "main.js").write_text("console.log('app')")
        monkeypatch.setattr("wilab.api._candidate_frontend_paths", lambda: [tmp_path])
        dependencies._config = None
        dependencies._manager = None
        load_config()
        return TestClient(create_app())

    def test_the_root_serves_the_index(self, web):
        resp = web.get("/")
        assert resp.status_code == 200 and "INDEX" in resp.text

    def test_a_static_file_is_served_as_is(self, web):
        resp = web.get("/main.js")
        assert resp.status_code == 200 and "console.log" in resp.text

    def test_an_unknown_route_falls_back_to_the_index_for_the_single_page_app(self, web):
        resp = web.get("/some/client/side/route")
        assert resp.status_code == 200 and "INDEX" in resp.text

    def test_the_documentation_is_not_shadowed_by_the_frontend(self, web):
        assert "swagger" in web.get("/docs").text.lower()
        assert web.get("/openapi.json").json()["info"]["title"] == "Wi-Lab"

    def test_an_unknown_api_path_is_a_404_not_the_index_and_not_null(self, web):
        resp = web.get(f"{API}/no-such-endpoint")
        assert "INDEX" not in resp.text
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}

    def test_a_frontend_build_without_an_index_says_so(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wilab.api._candidate_frontend_paths", lambda: [tmp_path])
        dependencies._config = None
        dependencies._manager = None
        load_config()
        client = TestClient(create_app())
        assert "not found" in client.get("/").json()["error"].lower()
        assert "not found" in client.get("/anything").json()["error"].lower()
