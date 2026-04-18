"""Tests for QoS (Quality of Service) management."""

import pytest

from wilab.models import QosRequest, QosStatus
from wilab.network.qos import QosManager, _SENTINEL


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------

class TestQosRequestModel:
    """Tests for QosRequest Pydantic model."""

    def test_valid_both_speeds(self):
        req = QosRequest(download_speed_kbit=8000, upload_speed_kbit=3000)
        assert req.download_speed_kbit == 8000
        assert req.upload_speed_kbit == 3000

    def test_valid_download_only(self):
        req = QosRequest(download_speed_kbit=5000)
        assert req.download_speed_kbit == 5000
        assert req.upload_speed_kbit is None

    def test_valid_upload_only(self):
        req = QosRequest(upload_speed_kbit=2000)
        assert req.upload_speed_kbit == 2000
        assert req.download_speed_kbit is None

    def test_null_resets(self):
        req = QosRequest(download_speed_kbit=None, upload_speed_kbit=None)
        assert req.download_speed_kbit is None
        assert req.upload_speed_kbit is None

    def test_min_speed(self):
        req = QosRequest(download_speed_kbit=1)
        assert req.download_speed_kbit == 1

    def test_max_speed(self):
        req = QosRequest(download_speed_kbit=1_000_000)
        assert req.download_speed_kbit == 1_000_000

    def test_speed_below_min(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=0)

    def test_speed_above_max(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=1_000_001)

    def test_negative_speed(self):
        with pytest.raises(Exception):
            QosRequest(download_speed_kbit=-1)


class TestQosStatusModel:
    """Tests for QosStatus response model."""

    def test_inactive(self):
        st = QosStatus(interface="wlan0", active=False)
        assert st.interface == "wlan0"
        assert not st.active
        assert st.download_speed_kbit is None

    def test_active_with_speed(self):
        st = QosStatus(interface="wlan0", active=True, download_speed_kbit=8000)
        assert st.active
        assert st.download_speed_kbit == 8000


# ---------------------------------------------------------------------------
# QosManager unit tests (mocked tc commands)
# ---------------------------------------------------------------------------

class TestQosManagerThrottle:
    """Tests for QosManager bandwidth throttling logic."""

    @pytest.fixture
    def qos(self, monkeypatch):
        """Create a QosManager with mocked tc/ip commands."""
        from wilab.network import qos as qos_mod

        self.tc_calls = []
        self.cmd_calls = []

        def mock_tc(args):
            self.tc_calls.append(args)
            return ""

        def mock_command(cmd, **kwargs):
            self.cmd_calls.append(cmd)
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        return QosManager()

    def test_apply_download_only(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 5000
        assert state.upload_speed_kbit is None
        assert state.active

        # Verify tc was called for HTB setup
        tc_ops = [c[0] for c in self.tc_calls]
        assert "qdisc" in tc_ops
        assert "class" in tc_ops

    def test_apply_upload_only(self, qos):
        qos.apply_qos("wlan0", upload_speed_kbit=2000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.upload_speed_kbit == 2000
        assert state.download_speed_kbit is None

        # IFB device should be allocated
        assert state.ifb_device is not None

    def test_apply_both_directions(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=8000, upload_speed_kbit=3000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.upload_speed_kbit == 3000
        assert state.active

    def test_update_download_speed(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        qos.apply_qos("wlan0", download_speed_kbit=10000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 10000

    def test_omitted_field_keeps_current(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        # Only update download, upload should stay
        qos.apply_qos("wlan0", download_speed_kbit=8000)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit == 8000
        assert state.upload_speed_kbit == 2000

    def test_null_resets_to_unlimited(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.apply_qos("wlan0", download_speed_kbit=None)

        state = qos.get_status("wlan0")
        assert state is not None
        assert state.download_speed_kbit is None
        assert state.upload_speed_kbit == 2000

    def test_clear_all(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.clear_qos("wlan0")

        state = qos.get_status("wlan0")
        assert state is not None
        assert not state.active
        assert state.download_speed_kbit is None
        assert state.upload_speed_kbit is None

    def test_clear_nonexistent_is_noop(self, qos):
        # Should not raise
        qos.clear_qos("wlan99")

    def test_get_status_unknown_interface(self, qos):
        assert qos.get_status("wlan99") is None

    def test_idempotent_apply(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        tc_count_1 = len(self.tc_calls)
        qos.apply_qos("wlan0", download_speed_kbit=5000)
        # Second apply should still issue class change (idempotent)
        assert len(self.tc_calls) > tc_count_1

    def test_reset_both_removes_all(self, qos):
        qos.apply_qos("wlan0", download_speed_kbit=5000, upload_speed_kbit=2000)
        qos.apply_qos("wlan0", download_speed_kbit=None, upload_speed_kbit=None)

        state = qos.get_status("wlan0")
        assert state is not None
        assert not state.active

    def test_ifb_counter_increments(self, qos):
        qos.apply_qos("wlan0", upload_speed_kbit=2000)
        qos.clear_qos("wlan0")
        qos.apply_qos("wlan1", upload_speed_kbit=3000)

        st0 = qos.get_status("wlan1")
        assert st0 is not None
        assert st0.ifb_device == "ifb1"


class TestQosManagerSentinel:
    """Tests for _SENTINEL partial-update logic."""

    def test_resolve_sentinel_keeps_current(self):
        assert QosManager._resolve(_SENTINEL, 5000) == 5000

    def test_resolve_none_resets(self):
        assert QosManager._resolve(None, 5000) is None

    def test_resolve_value_updates(self):
        assert QosManager._resolve(8000, 5000) == 8000

    def test_resolve_sentinel_with_none_current(self):
        assert QosManager._resolve(_SENTINEL, None) is None


# ---------------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ---------------------------------------------------------------------------

class TestQosAPI:
    """Tests for QoS API endpoints."""

    @pytest.fixture
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient
        from wilab.api import create_app
        from wilab.config import load_config
        from wilab.network import qos as qos_mod

        self.tc_calls = []

        def mock_tc(args):
            self.tc_calls.append(args)
            return ""

        def mock_command(cmd, **kwargs):
            return ""

        monkeypatch.setattr(qos_mod, "execute_tc", mock_tc)
        monkeypatch.setattr(qos_mod, "execute_command", mock_command)

        load_config()
        app = create_app()
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, config):
        return {"Authorization": f"Bearer {config.auth_token}"}

    @pytest.fixture
    def reservation_id(self, client, auth_headers, monkeypatch):
        """Create a reservation and start a network, return reservation_id."""
        from wilab.api import dependencies
        from wilab.reservation import ReservationManager
        from wilab.config import load_config

        cfg = load_config()
        rmgr = ReservationManager([n.device_id for n in cfg.networks])
        monkeypatch.setattr(dependencies, '_reservation_manager', rmgr, raising=False)

        # Reserve a device
        resp = client.post(
            "/api/v1/device-reservation",
            headers=auth_headers,
            json={"duration_seconds": 300},
        )
        assert resp.status_code == 200, resp.text
        rid = resp.json()["reservation_id"]

        # Mock DHCP so start_network works without root
        mgr = dependencies._manager
        if mgr is None:
            # Force manager creation via a GET call
            client.get(f"/api/v1/interface/{rid}/network", headers=auth_headers)
            mgr = dependencies._manager
        assert mgr is not None

        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda *a, **kw: {
            'gateway': '192.168.120.1',
            'dhcp_range': '192.168.120.10,192.168.120.250',
            'config_file': '/tmp/mock.conf',
        })
        monkeypatch.setattr(mgr.dhcp_server, 'stop', lambda *a, **kw: None)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'stop', lambda *a, **kw: None)

        # Start a network
        resp = client.post(
            f"/api/v1/interface/{rid}/network",
            headers=auth_headers,
            json={
                "ssid": "QoSTest",
                "channel": 6,
                "encryption": "open",
                "band": "2.4ghz",
                "tx_power_level": 4,
            },
        )
        assert resp.status_code == 200, resp.text
        return rid

    def test_get_qos_no_rules(self, client, auth_headers, reservation_id):
        resp = client.get(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["download_speed_kbit"] is None

    def test_apply_download_speed(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["download_speed_kbit"] == 8000
        assert data["upload_speed_kbit"] is None

    def test_apply_both_speeds(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000, "upload_speed_kbit": 3000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_speed_kbit"] == 8000
        assert data["upload_speed_kbit"] == 3000

    def test_partial_update_preserves_existing(self, client, auth_headers, reservation_id):
        # Set both
        client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000, "upload_speed_kbit": 3000},
        )
        # Update only download
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 12000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_speed_kbit"] == 12000
        assert data["upload_speed_kbit"] == 3000

    def test_null_resets_field(self, client, auth_headers, reservation_id):
        client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000, "upload_speed_kbit": 3000},
        )
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["download_speed_kbit"] is None
        assert data["upload_speed_kbit"] == 3000

    def test_delete_clears_all(self, client, auth_headers, reservation_id):
        client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000},
        )
        resp = client.delete(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # Verify cleared
        resp = client.get(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
        )
        assert resp.json()["active"] is False

    def test_apply_empty_body_returns_422(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_apply_invalid_speed_returns_422(self, client, auth_headers, reservation_id):
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 0},
        )
        assert resp.status_code == 422

    def test_apply_requires_auth(self, client, reservation_id):
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/qos",
            json={"download_speed_kbit": 8000},
        )
        assert resp.status_code == 401

    def test_apply_invalid_reservation(self, client, auth_headers):
        resp = client.post(
            "/api/v1/interface/nonexistent/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000},
        )
        assert resp.status_code == 404

    def test_apply_on_inactive_network(self, client, auth_headers, monkeypatch):
        # Reserve but don't start network
        from wilab.api import dependencies
        from wilab.reservation import ReservationManager
        from wilab.config import load_config

        cfg = load_config()
        rmgr = ReservationManager([n.device_id for n in cfg.networks])
        monkeypatch.setattr(dependencies, '_reservation_manager', rmgr, raising=False)

        resp = client.post(
            "/api/v1/device-reservation",
            headers=auth_headers,
            json={"duration_seconds": 300},
        )
        rid = resp.json()["reservation_id"]

        resp = client.post(
            f"/api/v1/interface/{rid}/qos",
            headers=auth_headers,
            json={"download_speed_kbit": 8000},
        )
        assert resp.status_code == 409
