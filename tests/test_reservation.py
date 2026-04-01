"""Tests for device reservation module and API endpoints."""

import time
import pytest
from fastapi.testclient import TestClient

from wilab.reservation import ReservationManager, Reservation, NoDeviceAvailableError
from wilab.api import create_app
from wilab.config import load_config
from wilab.api import dependencies


# ======================================================================
# Unit tests for ReservationManager
# ======================================================================


class TestReservationManagerCreate:
    """Tests for reservation creation."""

    def test_create_reservation_returns_reservation(self):
        mgr = ReservationManager(["dev0", "dev1"])
        r = mgr.create(3600)
        assert isinstance(r, Reservation)
        assert r.device_id == "dev0"
        assert r.duration_seconds == 3600
        assert len(r.reservation_id) == 8  # 4 bytes hex

    def test_create_reservation_assigns_first_available(self):
        mgr = ReservationManager(["dev0", "dev1"])
        r1 = mgr.create(3600)
        r2 = mgr.create(3600)
        assert r1.device_id == "dev0"
        assert r2.device_id == "dev1"

    def test_create_reservation_unique_tokens(self):
        mgr = ReservationManager(["dev0", "dev1"])
        r1 = mgr.create(3600)
        r2 = mgr.create(3600)
        assert r1.reservation_id != r2.reservation_id

    def test_create_reservation_no_device_available(self):
        mgr = ReservationManager(["dev0"])
        mgr.create(3600)
        with pytest.raises(NoDeviceAvailableError, match="No device available"):
            mgr.create(3600)

    def test_no_device_available_has_eta(self):
        mgr = ReservationManager(["dev0"])
        mgr.create(120)
        try:
            mgr.create(3600)
            assert False, "Should have raised"
        except NoDeviceAvailableError as exc:
            assert exc.next_available_in > 0
            assert exc.next_available_at > time.time()

    def test_eta_uses_soonest_expiry(self):
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.create(600)   # expires in 600s
        mgr.create(60)    # expires in 60s — soonest
        try:
            mgr.create(3600)
            assert False, "Should have raised"
        except NoDeviceAvailableError as exc:
            # ETA should be closest to r2's expiry (60s), not r1 (600s)
            assert exc.next_available_in <= 65

    def test_simultaneous_expiries_non_negative(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(1)
        r.expires_at = time.time()  # about to expire
        try:
            mgr.create(3600)
        except NoDeviceAvailableError as exc:
            assert exc.next_available_in >= 0

    def test_create_reservation_sets_expiry(self):
        mgr = ReservationManager(["dev0"])
        before = time.time()
        r = mgr.create(120)
        after = time.time()
        assert before + 120 <= r.expires_at <= after + 120

    def test_create_reservation_expires_in_positive(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        assert 3590 <= r.expires_in <= 3600


class TestReservationManagerGet:
    """Tests for fetching a reservation."""

    def test_get_valid_token(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        fetched = mgr.get(r.reservation_id)
        assert fetched is not None
        assert fetched.reservation_id == r.reservation_id
        assert fetched.device_id == "dev0"

    def test_get_invalid_token(self):
        mgr = ReservationManager(["dev0"])
        assert mgr.get("nonexistent") is None

    def test_get_expired_token_returns_none(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(1)
        # Force expiry
        r.expires_at = time.time() - 1
        assert mgr.get(r.reservation_id) is None


class TestReservationManagerDelete:
    """Tests for releasing a reservation."""

    def test_delete_valid_token(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        assert mgr.delete(r.reservation_id) is True

    def test_delete_invalid_token(self):
        mgr = ReservationManager(["dev0"])
        assert mgr.delete("nonexistent") is False

    def test_delete_frees_device(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        mgr.delete(r.reservation_id)
        # Device should be available again
        r2 = mgr.create(3600)
        assert r2.device_id == "dev0"

    def test_post_release_get_returns_none(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        rid = r.reservation_id
        mgr.delete(rid)
        assert mgr.get(rid) is None


class TestReservationManagerHelpers:
    """Tests for helper methods."""

    def test_device_for_valid(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(3600)
        assert mgr.device_for(r.reservation_id) == "dev0"

    def test_device_for_invalid(self):
        mgr = ReservationManager(["dev0"])
        assert mgr.device_for("bad-token") is None

    def test_all_active(self):
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.create(3600)
        mgr.create(3600)
        active = mgr.all_active()
        assert len(active) == 2

    def test_is_device_reserved(self):
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.create(3600)
        assert mgr.is_device_reserved("dev0") is True
        assert mgr.is_device_reserved("dev1") is False

    def test_expired_reservation_auto_purged(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(1)
        r.expires_at = time.time() - 1  # Force expiry
        assert mgr.is_device_reserved("dev0") is False
        assert len(mgr.all_active()) == 0


# ======================================================================
# API integration tests
# ======================================================================

@pytest.fixture
def client():
    """Create a FastAPI test client with clean reservation state."""
    # Reset singletons
    dependencies._config = None
    dependencies._manager = None
    dependencies._reservation_manager = None
    load_config()
    app = create_app()
    return TestClient(app)


@pytest.fixture
def valid_token():
    cfg = load_config()
    return f"Bearer {cfg.auth_token}"


class TestReservationAPICreate:
    """Tests for POST /api/v1/device-reservation."""

    def test_create_reservation_success(self, client, valid_token):
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reservation_id" in data
        assert "display_name" in data
        assert "interface" in data
        assert "expires_at" in data
        assert "expires_in" in data
        assert data["expires_in"] > 0
        assert "device_id" not in data

    def test_create_reservation_requires_auth(self, client):
        resp = client.post(
            "/api/v1/device-reservation",
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 401

    def test_create_reservation_invalid_duration(self, client, valid_token):
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 0},
        )
        assert resp.status_code == 422

    def test_create_reservation_negative_duration(self, client, valid_token):
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": -10},
        )
        assert resp.status_code == 422

    def test_full_capacity_returns_409_with_eta(self, client, valid_token):
        """All devices reserved returns 409 with next_available_at/in."""
        # Config has 1 device (wls16), reserve it
        client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 120},
        )
        # Try again — should get 409
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 409
        data = resp.json()["detail"]
        assert data["error"] == "No device available"
        assert "next_available_at" in data
        assert "next_available_in" in data
        assert data["next_available_in"] > 0


class TestReservationAPIGet:
    """Tests for GET /api/v1/device-reservation/{reservation_id}."""

    def test_get_reservation_success(self, client, valid_token):
        # Create first
        create_resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]

        resp = client.get(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reservation_id"] == rid
        assert data["expires_in"] > 0
        assert "display_name" in data
        assert "interface" in data

    def test_get_reservation_not_found(self, client, valid_token):
        resp = client.get(
            "/api/v1/device-reservation/nonexistent",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404

    def test_get_reservation_requires_auth(self, client):
        resp = client.get("/api/v1/device-reservation/any-id")
        assert resp.status_code == 401


class TestReservationAPIDelete:
    """Tests for DELETE /api/v1/device-reservation/{reservation_id}."""

    def test_delete_reservation_success(self, client, valid_token):
        create_resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]

        resp = client.delete(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert resp.json() == {"detail": "Reservation released"}

    def test_delete_reservation_not_found(self, client, valid_token):
        resp = client.delete(
            "/api/v1/device-reservation/nonexistent",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404

    def test_delete_reservation_requires_auth(self, client):
        resp = client.delete("/api/v1/device-reservation/any-id")
        assert resp.status_code == 401

    def test_post_release_get_returns_404(self, client, valid_token):
        """After DELETE, GET on same token must return 404."""
        create_resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]
        client.delete(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        resp = client.get(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404


class TestReservationManagerDeleteAll:
    """Tests for ReservationManager.delete_all()."""

    def test_delete_all_returns_count(self):
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.create(3600)
        mgr.create(3600)
        assert mgr.delete_all() == 2

    def test_delete_all_frees_devices(self):
        mgr = ReservationManager(["dev0"])
        mgr.create(3600)
        assert mgr.delete_all() == 1
        # Device should be available again
        r = mgr.create(3600)
        assert r.device_id == "dev0"

    def test_delete_all_empty_returns_zero(self):
        mgr = ReservationManager(["dev0"])
        assert mgr.delete_all() == 0


class TestReservationAPIDeleteAll:
    """Tests for DELETE /api/v1/device-reservation."""

    def test_delete_all_success(self, client, valid_token):
        # Create a reservation first
        client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        resp = client.delete(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["released"] == 1

    def test_delete_all_empty(self, client, valid_token):
        resp = client.delete(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert resp.json()["released"] == 0

    def test_delete_all_requires_auth(self, client):
        resp = client.delete("/api/v1/device-reservation")
        assert resp.status_code == 401

    def test_delete_all_frees_for_new_reservation(self, client, valid_token):
        """After delete-all, a new reservation should succeed."""
        client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        client.delete(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
        )
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200


# ======================================================================
# Unit tests for unlimited reservations
# ======================================================================


class TestUnlimitedReservation:
    """Tests for unlimited (duration_seconds=0) reservations."""

    def test_create_unlimited_reservation(self):
        """Creating with duration_seconds=0 sets expires_at=None."""
        mgr = ReservationManager(["dev0"])
        r = mgr.create(0)
        assert r.expires_at is None
        assert r.duration_seconds == 0

    def test_unlimited_expires_in_is_none(self):
        """Unlimited reservation expires_in returns None."""
        mgr = ReservationManager(["dev0"])
        r = mgr.create(0)
        assert r.expires_in is None

    def test_unlimited_is_not_expired(self):
        """Unlimited reservation is never expired."""
        mgr = ReservationManager(["dev0"])
        r = mgr.create(0)
        assert r.is_expired is False

    def test_unlimited_not_purged(self):
        """Unlimited reservation is not purged by _purge_expired."""
        mgr = ReservationManager(["dev0", "dev1"])
        r_unlimited = mgr.create(0)
        r_timed = mgr.create(1)
        # Force the timed one to expire
        r_timed.expires_at = time.time() - 1
        active = mgr.all_active()
        assert len(active) == 1
        assert active[0].reservation_id == r_unlimited.reservation_id

    def test_soonest_expiry_ignores_unlimited(self):
        """_soonest_expiry excludes unlimited reservations."""
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.create(0)  # unlimited
        r_timed = mgr.create(600)
        with mgr._lock:
            soonest = mgr._soonest_expiry()
        assert abs(soonest - r_timed.expires_at) < 2

    def test_soonest_expiry_all_unlimited(self):
        """_soonest_expiry returns now when all reservations are unlimited."""
        mgr = ReservationManager(["dev0"])
        mgr.create(0)
        before = time.time()
        with mgr._lock:
            soonest = mgr._soonest_expiry()
        assert soonest >= before


# ======================================================================
# Tests for network teardown on reservation release
# ======================================================================


class TestReservationDeleteStopsNetwork:
    """Releasing a reservation must stop any active WiFi network on the device."""

    def _ensure_manager(self, client, valid_token):
        """Ensure NetworkManager singleton is initialized by making a status request."""
        client.get("/api/v1/status", headers={"Authorization": valid_token})
        return dependencies._manager

    def test_delete_reservation_stops_active_network(self, client, valid_token, monkeypatch):
        """DELETE reservation stops the active network on the released device."""
        mgr = self._ensure_manager(client, valid_token)
        # Create reservation
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = resp.json()["reservation_id"]
        device_id = resp.json()["interface"]

        # Simulate an active network on this device
        from wilab.models import NetworkStatus
        mgr.active[device_id] = NetworkStatus(interface=device_id, active=True)

        stopped = []

        def mock_stop(did):
            stopped.append(did)
            # Remove from active dict (mimics real stop_network behaviour)
            mgr.active.pop(did, None)

        monkeypatch.setattr(mgr, "stop_network", mock_stop)

        resp = client.delete(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert stopped == [device_id]

    def test_delete_reservation_no_network_active(self, client, valid_token, monkeypatch):
        """DELETE reservation succeeds even when no network is active (no stop_network call)."""
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = resp.json()["reservation_id"]

        mgr = self._ensure_manager(client, valid_token)
        stopped = []
        monkeypatch.setattr(mgr, "stop_network", lambda did: stopped.append(did))

        resp = client.delete(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert stopped == []

    def test_delete_reservation_stop_network_error_still_releases(self, client, valid_token, monkeypatch):
        """If stop_network raises, the reservation is still released (best-effort)."""
        resp = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = resp.json()["reservation_id"]
        device_id = resp.json()["interface"]

        mgr = self._ensure_manager(client, valid_token)
        from wilab.models import NetworkStatus
        mgr.active[device_id] = NetworkStatus(interface=device_id, active=True)

        def failing_stop(did):
            raise RuntimeError("simulated teardown failure")

        monkeypatch.setattr(mgr, "stop_network", failing_stop)

        resp = client.delete(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert resp.json() == {"detail": "Reservation released"}
        # Reservation should still be gone
        resp = client.get(
            f"/api/v1/device-reservation/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404

    def test_delete_all_stops_all_active_networks(self, client, valid_token, monkeypatch):
        """DELETE all reservations stops active networks on released devices."""
        # Create reservation (test config has 1 device)
        r1 = client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        ).json()

        mgr = self._ensure_manager(client, valid_token)
        from wilab.models import NetworkStatus
        mgr.active[r1["interface"]] = NetworkStatus(interface=r1["interface"], active=True)

        stopped = []

        def mock_stop(did):
            stopped.append(did)
            mgr.active.pop(did, None)

        monkeypatch.setattr(mgr, "stop_network", mock_stop)

        resp = client.delete(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert resp.json()["released"] == 1
        assert stopped == [r1["interface"]]

    def test_delete_all_no_networks_active(self, client, valid_token, monkeypatch):
        """DELETE all reservations succeeds when no networks are active."""
        client.post(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )

        mgr = self._ensure_manager(client, valid_token)
        stopped = []
        monkeypatch.setattr(mgr, "stop_network", lambda did: stopped.append(did))

        resp = client.delete(
            "/api/v1/device-reservation",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert stopped == []
