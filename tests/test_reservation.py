"""Tests for device reservation module and API endpoints."""

import time
import pytest
from fastapi.testclient import TestClient

from wilab.reservation import ReservationManager, Reservation
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
        assert len(r.reservation_id) == 32  # 16 bytes hex

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
        with pytest.raises(ValueError, match="No device available"):
            mgr.create(3600)

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
        assert "device_id" in data
        assert "expires_at" in data
        assert "expires_in" in data
        assert data["expires_in"] > 0

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
