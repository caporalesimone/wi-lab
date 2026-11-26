"""Tests for device reservation module and API endpoints."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import network_body
from fastapi import HTTPException
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.api.dependencies import hold_reservation
from wilab.config import load_config
from wilab.models import NetworkStatus
from wilab.reservation import (
    DeviceRecoveryUnavailable,
    NoDeviceAvailableError,
    Reservation,
    ReservationManager,
    UnknownDeviceError,
)


def test_ten_antenna_concurrent_reservations_are_unique_and_reusable():
    devices = [f"radio-{i}" for i in range(10)]
    manager = ReservationManager(devices)
    barrier = threading.Barrier(12, timeout=5)

    def reserve():
        barrier.wait()
        try:
            return manager.create(120)
        except NoDeviceAvailableError:
            return None

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(reserve) for _ in range(12)]
        results = [future.result(timeout=10) for future in futures]
    allocated = [reservation for reservation in results if reservation is not None]
    assert len(allocated) == 10
    assert {reservation.device_id for reservation in allocated} == set(devices)
    assert len({reservation.reservation_id for reservation in allocated}) == 10
    assert manager.delete(allocated[0].reservation_id)
    assert manager.create(120).device_id == allocated[0].device_id


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

    def test_eta_of_an_owner_about_to_expire_is_never_negative(self):
        mgr = ReservationManager(["dev0"])
        r = mgr.create(60)
        r.expires_at = time.time() + 0.5  # about to expire, still the owner
        with pytest.raises(NoDeviceAvailableError) as exc:
            mgr.create(3600)
        assert exc.value.next_available_in == 0
        # A release that is already late (failed cleanup) is clamped, not negative.
        assert NoDeviceAvailableError(time.time() - 5).next_available_in == 0

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


class TestReservationManagerGivenDevice:
    """create(duration, device_id): reserve one given antenna, never another."""

    def test_reserves_the_given_device_even_if_not_first(self):
        mgr = ReservationManager(["dev0", "dev1"])
        assert mgr.create(3600, "dev1").device_id == "dev1"
        assert mgr.create(3600).device_id == "dev0"

    def test_unknown_device_is_refused(self):
        mgr = ReservationManager(["dev0"])
        with pytest.raises(UnknownDeviceError):
            mgr.create(3600, "wlan9")

    def test_taken_device_reports_its_expiry_and_never_falls_back(self):
        mgr = ReservationManager(["dev0", "dev1"])
        owner = mgr.create(3600, "dev0")
        with pytest.raises(NoDeviceAvailableError) as exc:
            mgr.create(3600, "dev0")
        assert exc.value.next_available_at == owner.expires_at
        assert not mgr.is_device_reserved("dev1")

    def test_unlimited_owner_has_no_expiry(self):
        mgr = ReservationManager(["dev0"])
        mgr.create(0, "dev0")
        with pytest.raises(NoDeviceAvailableError) as exc:
            mgr.create(3600, "dev0")
        assert exc.value.next_available_at is None

    def test_expired_owner_is_cleaned_up_first(self):
        cleanup = Mock()
        mgr = ReservationManager(["dev0"], cleanup=cleanup)
        owner = mgr.create(3600, "dev0")
        owner.expires_at = time.time() - 1
        again = mgr.create(3600, "dev0")
        cleanup.assert_called_once_with("dev0")
        assert again.reservation_id != owner.reservation_id
        assert mgr.get(owner.reservation_id) is None

    def test_failed_cleanup_of_the_expired_owner_answers_when_to_retry(self):
        """C: a device held by a failing cleanup is 'reserved' until the next background attempt."""
        mgr = ReservationManager(
            ["dev0"], cleanup=Mock(side_effect=RuntimeError("stuck")), cleanup_wait=lambda _: 15.0,
        )
        mgr.create(3600, "dev0").expires_at = time.time() - 1
        with pytest.raises(NoDeviceAvailableError) as exc:
            mgr.create(3600, "dev0")
        assert 14 <= exc.value.next_available_in <= 15

    @pytest.mark.parametrize("recovering", [True, False])
    def test_quarantined_device_is_refused(self, recovering):
        mgr = ReservationManager(["dev0", "dev1"])
        mgr.quarantine(mgr.create(3600, "dev0"), recovering=recovering)
        with pytest.raises(DeviceRecoveryUnavailable) as exc:
            mgr.create(3600, "dev0")
        assert exc.value.recovering is recovering


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


class TestReservationLifecycleConcurrency:
    def test_expired_device_is_not_reassigned_before_cleanup_finishes(self):
        started = threading.Event()
        finish = threading.Event()

        def cleanup(device_id):
            started.set()
            assert finish.wait(timeout=5)

        mgr = ReservationManager(["dev0"], cleanup=cleanup)
        old = mgr.create(60)
        old.expires_at = time.time() - 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(mgr.create, 60)
            assert started.wait(timeout=5)
            assert not future.done()
            finish.set()
            new = future.result(timeout=5)
        assert new.device_id == old.device_id
        assert mgr.get(old.reservation_id) is None

    def test_failed_expiry_cleanup_blocks_reassignment_until_retry(self):
        failed = True

        def cleanup(device_id):
            if failed:
                raise RuntimeError("cleanup failed")

        mgr = ReservationManager(["dev0"], cleanup=cleanup, cleanup_wait=lambda _: 5.0)
        old = mgr.create(60)
        old.expires_at = time.time() - 1
        with pytest.raises(NoDeviceAvailableError) as exc:  # C: 409 / 1005, not 503 / 1004
            mgr.create(60)
        assert 4 <= exc.value.next_available_in <= 5
        failed = False
        assert mgr.create(60).device_id == "dev0"

    def test_failed_cleanup_does_not_block_another_free_device(self):
        def cleanup(device_id):
            raise RuntimeError("cleanup failed")

        mgr = ReservationManager(["dev0", "dev1"], cleanup=cleanup)
        old = mgr.create(60)
        old.expires_at = time.time() - 1
        assert mgr.create(60).device_id == "dev1"
        with pytest.raises(NoDeviceAvailableError):
            mgr.create(60)

    def test_slow_cleanup_does_not_hold_reservation_store(self):
        started, finish = threading.Event(), threading.Event()

        def cleanup(device_id: str) -> None:
            if device_id == "dev0":
                started.set()
                assert finish.wait(timeout=5)

        mgr = ReservationManager(["dev0", "dev1"], cleanup=cleanup)
        old = mgr.create(60)
        with ThreadPoolExecutor(max_workers=2) as pool:
            release = pool.submit(mgr.delete, old.reservation_id)
            try:
                assert started.wait(timeout=2)
                other = pool.submit(mgr.create, 60).result(timeout=2)
                assert other.device_id == "dev1"
                assert mgr.snapshot() == {"dev0": old, "dev1": other}
                with pytest.raises(NoDeviceAvailableError):
                    mgr.create(60)
            finally:
                finish.set()
            assert release.result(timeout=2)
        assert mgr.create(60).device_id == "dev0"

    def test_bulk_release_keeps_device_when_cleanup_fails(self):
        def cleanup(device_id):
            if device_id == "dev1":
                raise RuntimeError("cleanup failed")

        mgr = ReservationManager(["dev0", "dev1"], cleanup=cleanup)
        first = mgr.create(60)
        second = mgr.create(60)
        assert mgr.delete_all() == 2  # C: both released for the clients
        assert mgr.get(first.reservation_id) is None
        assert mgr.get(second.reservation_id) is None
        assert mgr.create(60).device_id == "dev0"
        with pytest.raises(NoDeviceAvailableError):  # dev1 stays held until its cleanup succeeds
            mgr.create(60)

    def test_release_waits_for_in_flight_operation(self):
        operation_started = threading.Event()
        finish = threading.Event()
        cleanup_started = threading.Event()
        mgr = ReservationManager(["dev0"], cleanup=lambda _: cleanup_started.set())
        reservation = mgr.create(60)

        def operate():
            with mgr.hold(reservation.reservation_id) as current:
                assert current is reservation
                operation_started.set()
                assert finish.wait(timeout=5)

        with ThreadPoolExecutor(max_workers=2) as pool:
            operation = pool.submit(operate)
            assert operation_started.wait(timeout=5)
            release = pool.submit(mgr.delete, reservation.reservation_id)
            assert not cleanup_started.wait(timeout=0.1)
            finish.set()
            operation.result(timeout=5)
            assert release.result(timeout=5)
        assert cleanup_started.is_set()

    def test_first_concurrent_requests_share_one_manager(self, monkeypatch):
        entered = threading.Event()
        resume = threading.Event()
        second_started = threading.Event()
        original = ReservationManager
        created = []
        config = SimpleNamespace(antennas=[
            SimpleNamespace(device_id="dev0"), SimpleNamespace(device_id="dev1")
        ])
        network = SimpleNamespace(
            device_lock=lambda _: threading.RLock(), release_device=lambda _: None,
            cleanup_due=lambda _: True, cleanup_wait=lambda _: 0.0, cancel_start=lambda _: False,
            watchdog=SimpleNamespace(start=lambda _: None),
            recovery=SimpleNamespace(start_reprobe=lambda _: None),
        )
        monkeypatch.setattr(dependencies, "get_manager", lambda _: network)

        def construct(*args, **kwargs):
            created.append(1)
            entered.set()
            assert resume.wait(timeout=5)
            return original(*args, **kwargs)

        monkeypatch.setattr(dependencies, "ReservationManager", construct)

        def second_request():
            second_started.set()
            return dependencies.get_reservation_manager(config)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(dependencies.get_reservation_manager, config)
            assert entered.wait(timeout=5)
            second = pool.submit(second_request)
            assert second_started.wait(timeout=5)
            resume.set()
            first_manager = first.result(timeout=5)
            second_manager = second.result(timeout=5)
        assert first_manager is second_manager
        assert len(created) == 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservations = list(pool.map(lambda manager: manager.create(60), [first_manager, second_manager]))
        assert {reservation.device_id for reservation in reservations} == {"dev0", "dev1"}

    def test_stale_reservation_cannot_operate_on_reassigned_device(self):
        mgr = ReservationManager(["dev0"])
        old = mgr.create(60)
        assert mgr.delete(old.reservation_id)
        assert mgr.create(60).device_id == old.device_id
        with pytest.raises(HTTPException) as exc, hold_reservation(mgr, old):
            pytest.fail("stale reservation was accepted")
        assert exc.value.status_code == 404

    def test_expiry_snapshot_does_not_stop_replacement_network(self, clean_manager, monkeypatch):
        from wilab.models import NetworkStatus

        old = NetworkStatus(interface="wls16", active=True)
        object.__setattr__(old, "_expires_at_timestamp", time.time() - 1)
        new = NetworkStatus(interface="wls16", active=True)
        clean_manager.active["wls16"] = new
        stopped = []
        monkeypatch.setattr(clean_manager, "stop_network", stopped.append)
        clean_manager._expire_network("wls16", old, time.time())
        assert stopped == []

    def test_network_cleanup_stops_qos_profile_before_release(self, clean_manager, monkeypatch):
        clean_manager.active["wls16"] = NetworkStatus(interface="wls16", active=True)
        clean_manager.qos_manager = Mock()
        clean_manager.qos_profile_manager = Mock()
        monkeypatch.setattr(clean_manager.hostapd_manager, "stop", lambda _: None)
        clean_manager.release_device("wls16")
        clean_manager.qos_profile_manager.stop_profile.assert_called_once_with(
            "wls16", clean_manager.qos_manager
        )
        assert "wls16" not in clean_manager.active


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


@pytest.mark.parametrize("operation", ["start_network", "expired_cleanup"])
def test_slow_lifecycle_operation_does_not_block_event_loop(operation, valid_token, monkeypatch):
    started = threading.Event()
    finish = threading.Event()

    with TestClient(create_app()) as client:
        headers = {"Authorization": valid_token}
        body = {"duration_seconds": 3600}
        response = client.post("/api/v2/reservations", headers=headers, json=body)
        assert response.status_code == 200
        reservation_id = response.json()["reservation_id"]
        manager = dependencies._manager
        reservation_manager = dependencies._reservation_manager
        assert manager is not None
        assert reservation_manager is not None
        assert client.get("/openapi.json").status_code == 200

        if operation == "start_network":
            def slow_start(*args, **kwargs):
                started.set()
                assert finish.wait(timeout=10)

            monkeypatch.setattr(manager, "start_network", slow_start)
            path = f"/api/v2/reservations/{reservation_id}/network"
            payload = network_body(
                ssid="test", channel=1, password="testpassword",
                encryption="wpa2", band="2.4ghz", tx_power_level=4,
            )
        else:
            reservation = reservation_manager.get(reservation_id)
            assert reservation is not None
            manager.active[reservation.device_id] = NetworkStatus(
                interface=reservation.device_id, active=True
            )
            reservation.expires_at = time.time() - 1

            def slow_stop(device_id):
                started.set()
                assert finish.wait(timeout=10)
                manager.active.pop(device_id)

            monkeypatch.setattr(manager, "stop_network", slow_stop)
            path = "/api/v2/reservations"
            payload = body

        with ThreadPoolExecutor(max_workers=2) as pool:
            operation_future = pool.submit(client.post, path, headers=headers, json=payload)
            try:
                assert started.wait(timeout=5)
                probe_future = pool.submit(client.get, "/openapi.json")
                assert probe_future.result(timeout=2).status_code == 200
            finally:
                finish.set()
            assert operation_future.result(timeout=5).status_code == 200


def test_slow_ap_start_does_not_block_other_radio_or_status(valid_token, monkeypatch):
    from wilab.config import NetworkEntry

    cfg = dependencies.get_config()
    monkeypatch.setattr(cfg, "antennas", [
        *cfg.antennas, NetworkEntry(interface="wlan1", display_name="Second radio"),
    ])
    headers = {"Authorization": valid_token}
    reserve = "/api/v2/reservations"
    payload = {
        "ssid": "test", "channel": 1, "encryption": "open", "band": "2.4ghz",
        "tx_power_level": 4, "internet_enabled": False,
    }
    entered, finish = threading.Event(), threading.Event()
    with TestClient(create_app()) as client, ThreadPoolExecutor(max_workers=4) as pool:
        mgr = dependencies.get_manager(cfg)
        first_device = cfg.antennas[0].device_id

        def start_ap(*, net_id: str, **kwargs) -> None:
            if net_id == first_device:
                entered.set()
                assert finish.wait(timeout=10)

        monkeypatch.setattr(mgr.hostapd_manager, "start", start_ap)
        monkeypatch.setattr(mgr.dhcp_server, "start", lambda **kwargs: None)
        first = client.post(reserve, headers=headers, json={"duration_seconds": 60}).json()
        first_id = first["reservation_id"]

        def create(rid: str):
            return client.post(f"/api/v2/reservations/{rid}/network", headers=headers, json=network_body(**payload))

        slow = pool.submit(create, first_id)
        try:
            assert entered.wait(timeout=5)
            release = pool.submit(client.delete, f"{reserve}/{first_id}", headers=headers)
            second = pool.submit(
                client.post, reserve, headers=headers, json={"duration_seconds": 60},
            ).result(timeout=2)
            assert second.status_code == 200 and second.json()["interface"] == "wlan1"
            rid = second.json()["reservation_id"]
            assert pool.submit(create, rid).result(timeout=2).status_code == 200
            status = pool.submit(client.get, "/api/v2/status", headers=headers).result(timeout=2)
            assert status.status_code == 200 and status.json()["active_networks"] == 1
            assert all(n["reservation"] for n in status.json()["antennas"])
            assert [n["network_active"] for n in status.json()["antennas"]].count(True) == 1
            assert not release.done()
        finally:
            finish.set()
        assert slow.result(timeout=3).status_code == 200
        assert release.result(timeout=3).status_code == 200


class TestReservationAPICreate:
    """Tests for POST /api/v2/reservations."""

    def test_create_reservation_success(self, client, valid_token):
        started = time.time()
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reservation_id" in data
        assert "display_name" in data
        assert "interface" in data
        assert data["expires_at"].endswith("Z")
        expiry = datetime.fromisoformat(data["expires_at"]).timestamp()
        assert started + 3600 <= expiry <= time.time() + 3600
        assert "expires_in" in data
        assert data["expires_in"] > 0
        assert "device_id" not in data

    def test_create_reservation_requires_auth(self, client):
        resp = client.post(
            "/api/v2/reservations",
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 401

    def test_create_reservation_invalid_duration(self, client, valid_token):
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 0},
        )
        assert resp.status_code == 422

    def test_create_reservation_negative_duration(self, client, valid_token):
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": -10},
        )
        assert resp.status_code == 422

    def test_full_capacity_returns_409_with_eta(self, client, valid_token):
        """All devices reserved returns 409 with next_available_at/in."""
        # Config has 1 device (wls16), reserve it
        first = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 120},
        )
        assert first.status_code == 200
        # Try again — should get 409
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 409
        data = resp.json()["detail"]
        assert data["code"] == 1005
        assert data["message"] == "No device available"
        assert data["next_available_at"].endswith("Z")
        assert data["next_available_at"] == first.json()["expires_at"]
        assert "next_available_in" in data
        assert data["next_available_in"] > 0


class TestReservationAPIGivenInterface:
    """POST /reservations with the optional `interface`."""

    def _reserve(self, client, token, **body):
        return client.post(
            "/api/v2/reservations", headers={"Authorization": token},
            json={"duration_seconds": 3600, **body},
        )

    def test_given_interface_is_reserved(self, client, valid_token):
        interfaces = [n.interface for n in dependencies.get_config().antennas]
        last = interfaces[-1]
        resp = self._reserve(client, valid_token, interface=last)
        assert resp.status_code == 200, resp.text
        assert resp.json()["interface"] == last

    def test_taken_interface_is_409_1005(self, client, valid_token):
        first = self._reserve(client, valid_token).json()
        resp = self._reserve(client, valid_token, interface=first["interface"])
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == 1005
        assert detail["next_available_at"] == first["expires_at"]

    def test_unknown_interface_is_422_with_its_path(self, client, valid_token):
        resp = self._reserve(client, valid_token, interface="wlan9")
        assert resp.status_code == 422
        assert resp.json()["detail"]["message"].startswith("interface: wlan9 ")

    def test_null_interface_reserves_the_first_free(self, client, valid_token):
        resp = self._reserve(client, valid_token, interface=None)
        assert resp.status_code == 200


class TestReservationAPIGet:
    """Tests for GET /api/v2/reservations/{reservation_id}."""

    def test_get_reservation_success(self, client, valid_token):
        # Create first
        create_resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]

        resp = client.get(
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reservation_id"] == rid
        assert data["expires_at"] == create_resp.json()["expires_at"]
        assert data["expires_in"] > 0
        assert "display_name" in data
        assert "interface" in data

    def test_get_reservation_not_found(self, client, valid_token):
        resp = client.get(
            "/api/v2/reservations/nonexistent",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404

    def test_get_reservation_requires_auth(self, client):
        resp = client.get("/api/v2/reservations/any-id")
        assert resp.status_code == 401


class TestReservationAPIDelete:
    """Tests for DELETE /api/v2/reservations/{reservation_id}."""

    def test_delete_reservation_success(self, client, valid_token):
        create_resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]

        resp = client.delete(
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert resp.json() == {"detail": "Reservation released"}

    def test_delete_reservation_not_found(self, client, valid_token):
        resp = client.delete(
            "/api/v2/reservations/nonexistent",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404

    def test_delete_reservation_requires_auth(self, client):
        resp = client.delete("/api/v2/reservations/any-id")
        assert resp.status_code == 401

    def test_post_release_get_returns_404(self, client, valid_token):
        """After DELETE, GET on same token must return 404."""
        create_resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = create_resp.json()["reservation_id"]
        client.delete(
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        resp = client.get(
            f"/api/v2/reservations/{rid}",
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
    """Tests for DELETE /api/v2/reservations/all (password-protected)."""

    URL = "/api/v2/reservations/all"

    @pytest.fixture(autouse=True)
    def _password(self, client):
        dependencies.get_config().protected_commands_password = "qwerty-test"

    def _reserve(self, client, valid_token):
        resp = client.post(
            "/api/v2/reservations", headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200
        return resp.json()["reservation_id"]

    def test_releases_all_with_the_configured_password_and_frees_devices(self, client, valid_token):
        rid = self._reserve(client, valid_token)
        headers = {"Authorization": valid_token, "X-Confirm-Password": "qwerty-test"}
        resp = client.delete(self.URL, headers=headers)
        assert resp.status_code == 200 and resp.json()["released"] == 1
        assert client.get(f"/api/v2/reservations/{rid}", headers={"Authorization": valid_token}).status_code == 404
        assert client.delete(self.URL, headers=headers).json()["released"] == 0
        self._reserve(client, valid_token)

    @pytest.mark.parametrize("password", [None, "", "wrong", "qwerty-test "])
    def test_missing_or_wrong_password_releases_nothing(self, client, valid_token, password):
        rid = self._reserve(client, valid_token)
        headers = {"Authorization": valid_token}
        if password is not None:
            headers["X-Confirm-Password"] = password
        resp = client.delete(self.URL, headers=headers)
        assert resp.status_code == 403
        assert "X-Confirm-Password" in resp.json()["detail"]["message"]
        assert client.get(f"/api/v2/reservations/{rid}", headers={"Authorization": valid_token}).status_code == 200

    def test_disabled_without_a_configured_password(self, client, valid_token):
        from wilab.config import AppConfig
        blank = AppConfig(auth_token="t", dhcp_base_network="192.168.120.0/24", protected_commands_password="  ")
        assert blank.protected_commands_password is None
        dependencies.get_config().protected_commands_password = None
        self._reserve(client, valid_token)
        resp = client.delete(self.URL, headers={"Authorization": valid_token, "X-Confirm-Password": "anything"})
        assert resp.status_code == 403 and "not configured" in resp.json()["detail"]["message"]

    def test_requires_auth_before_the_password(self, client):
        assert client.delete(self.URL, headers={"X-Confirm-Password": "qwerty-test"}).status_code == 401

    @pytest.mark.parametrize("path", ["/api/v2/reservations", "/api/v2/reservations/"])
    def test_collection_delete_no_longer_releases_anything(self, client, valid_token, path):
        rid = self._reserve(client, valid_token)
        headers = {"Authorization": valid_token, "X-Confirm-Password": "qwerty-test"}
        assert client.delete(path, headers=headers).status_code == 405
        assert client.get(f"/api/v2/reservations/{rid}", headers={"Authorization": valid_token}).status_code == 200


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
        """Unlimited holds have no scheduled release."""
        mgr = ReservationManager(["dev0"])
        mgr.create(0)
        with mgr._lock:
            soonest = mgr._soonest_expiry()
        assert soonest is None

    def test_api_unlimited_contention_has_null_eta(self, client, valid_token, monkeypatch):
        config = dependencies.get_config()
        monkeypatch.setattr(config, "allow_unlimited_reservation", True)
        headers = {"Authorization": valid_token}
        assert client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 0}).status_code == 200
        response = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 120})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == 1005
        assert detail["next_available_at"] is None and detail["next_available_in"] is None


# ======================================================================
# Tests for network teardown on reservation release
# ======================================================================


class TestReservationDeleteStopsNetwork:
    """Releasing a reservation must stop any active WiFi network on the device."""

    def _ensure_manager(self, client, valid_token):
        """Ensure NetworkManager singleton is initialized by making a status request."""
        client.get("/api/v2/status", headers={"Authorization": valid_token})
        return dependencies._manager

    def test_delete_reservation_stops_active_network(self, client, valid_token, monkeypatch):
        """DELETE reservation stops the active network on the released device."""
        mgr = self._ensure_manager(client, valid_token)
        # Create reservation
        resp = client.post(
            "/api/v2/reservations",
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
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert stopped == [device_id]

    def test_delete_reservation_no_network_active(self, client, valid_token, monkeypatch):
        """DELETE reservation succeeds even when no network is active (no stop_network call)."""
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        rid = resp.json()["reservation_id"]

        mgr = self._ensure_manager(client, valid_token)
        stopped = []
        monkeypatch.setattr(mgr, "stop_network", lambda did: stopped.append(did))

        resp = client.delete(
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        assert stopped == []

    def test_expired_network_is_stopped_before_device_is_reassigned(self, client, valid_token, monkeypatch):
        from wilab.models import NetworkStatus

        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        reservation = dependencies._reservation_manager.get(resp.json()["reservation_id"])
        mgr = self._ensure_manager(client, valid_token)
        device_id = reservation.device_id
        mgr.active[device_id] = NetworkStatus(interface=device_id, active=True)
        reservation.expires_at = time.time() - 1
        stopped = []

        def stop(did):
            stopped.append(did)
            mgr.active.pop(did)

        monkeypatch.setattr(mgr, "stop_network", stop)
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200
        assert resp.json()["interface"] == device_id
        assert stopped == [device_id]

    def test_expired_cleanup_failure_returns_409_and_allows_retry(self, client, valid_token, monkeypatch):
        from wilab.models import NetworkStatus

        headers = {"Authorization": valid_token}
        body = {"duration_seconds": 3600}
        response = client.post("/api/v2/reservations", headers=headers, json=body)
        reservation = dependencies._reservation_manager.get(response.json()["reservation_id"])
        manager = self._ensure_manager(client, valid_token)
        device_id = reservation.device_id
        manager.active[device_id] = NetworkStatus(interface=device_id, active=True)
        reservation.expires_at = time.time() - 1

        def fail(did):
            raise RuntimeError("cleanup failed")

        monkeypatch.setattr(manager, "stop_network", fail)
        response = client.post("/api/v2/reservations", headers=headers, json=body)
        assert response.status_code == 409  # C: held by the cleanup, try again later
        assert response.json()["detail"]["code"] == 1005
        assert response.json()["detail"]["next_available_in"] is not None
        manager._cleanup_retry_at.clear()  # the backoff is over

        monkeypatch.setattr(manager, "stop_network", lambda did: manager.active.pop(did))
        response = client.post("/api/v2/reservations", headers=headers, json=body)
        assert response.status_code == 200
        assert response.json()["interface"] == device_id

    def test_release_with_a_failed_teardown_answers_200_and_cleans_up_later(self, client, valid_token, monkeypatch):
        """C: the release never fails; the antenna stays held until the background cleanup works."""
        resp = client.post(
            "/api/v2/reservations",
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
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 200
        resp = client.get(
            f"/api/v2/reservations/{rid}",
            headers={"Authorization": valid_token},
        )
        assert resp.status_code == 404
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 409  # still held by the failed cleanup
        assert resp.json()["detail"]["code"] == 1005
        status = client.get("/api/v2/status", headers={"Authorization": valid_token}).json()
        assert status["status"] == "degraded"
        assert {"code": "cleanup_failed", "interface": device_id} in [
            {k: r[k] for k in ("code", "interface")} for r in status["degraded_reasons"]
        ]

        def successful_stop(did):
            mgr.active.pop(did)

        monkeypatch.setattr(mgr, "stop_network", successful_stop)
        mgr._cleanup_retry_at.clear()  # the backoff is over
        dependencies._reservation_manager.expire()  # the background sweep
        resp = client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )
        assert resp.status_code == 200
        assert resp.json()["interface"] == device_id

    def test_delete_all_stops_all_active_networks(self, client, valid_token, monkeypatch):
        """DELETE all reservations stops active networks on released devices."""
        # Create reservation (test config has 1 device)
        r1 = client.post(
            "/api/v2/reservations",
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

        dependencies.get_config().protected_commands_password = "qwerty-test"
        resp = client.delete(
            "/api/v2/reservations/all",
            headers={"Authorization": valid_token, "X-Confirm-Password": "qwerty-test"},
        )
        assert resp.status_code == 200
        assert resp.json()["released"] == 1
        assert stopped == [r1["interface"]]

    def test_delete_all_no_networks_active(self, client, valid_token, monkeypatch):
        """DELETE all reservations succeeds when no networks are active."""
        client.post(
            "/api/v2/reservations",
            headers={"Authorization": valid_token},
            json={"duration_seconds": 3600},
        )

        mgr = self._ensure_manager(client, valid_token)
        stopped = []
        monkeypatch.setattr(mgr, "stop_network", lambda did: stopped.append(did))

        dependencies.get_config().protected_commands_password = "qwerty-test"
        resp = client.delete(
            "/api/v2/reservations/all",
            headers={"Authorization": valid_token, "X-Confirm-Password": "qwerty-test"},
        )
        assert resp.status_code == 200
        assert stopped == []


class TestGoneReasons:
    """Every call with an ended ID answers 404 with a stable detail.reason (contract)."""

    def test_manager_remembers_why_an_id_ended(self):
        from wilab.reservation import EXPIRED, INVALIDATED, NOT_FOUND, RELEASED
        mgr = ReservationManager(["dev0", "dev1", "dev2"])
        released, expired, invalidated = mgr.create(60), mgr.create(60), mgr.create(60)
        mgr.delete(released.reservation_id)
        expired.expires_at = time.time() - 1
        mgr.expire()
        mgr.quarantine(invalidated, recovering=False)
        assert mgr.ended_reason(released.reservation_id) == RELEASED
        assert mgr.ended_reason(expired.reservation_id) == EXPIRED
        assert mgr.ended_reason(invalidated.reservation_id) == INVALIDATED
        assert mgr.ended_reason("deadbeef") == NOT_FOUND

    def test_reasons_are_forgotten_after_an_hour(self, monkeypatch):
        from wilab import reservation as module
        mgr = ReservationManager(["dev0"])
        rid = mgr.create(60).reservation_id
        mgr.delete(rid)
        monkeypatch.setattr(module, "ENDED_TTL", -1.0)
        assert mgr.ended_reason(rid) == module.NOT_FOUND

    def test_release_with_failed_cleanup_is_released_not_expired(self):
        mgr = ReservationManager(["dev0"], cleanup=Mock(side_effect=RuntimeError("stuck")))
        rid = mgr.create(60).reservation_id
        assert mgr.delete(rid)
        assert mgr.ended_reason(rid) == "reservation_released"

    @pytest.mark.parametrize(("method", "suffix"), [
        ("get", ""), ("delete", ""), ("get", "/network"), ("post", "/network"),
        ("delete", "/network"), ("post", "/internet/enable"), ("get", "/txpower"),
    ])
    def test_every_endpoint_with_an_id_answers_the_reason(self, client, valid_token, method, suffix):
        headers = {"Authorization": valid_token}
        rid = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 60}).json()[
            "reservation_id"]
        assert client.delete(f"/api/v2/reservations/{rid}", headers=headers).status_code == 200
        kwargs = {"json": network_body(ssid="x", channel=6, encryption="open", band="2.4ghz",
                                       tx_power_level=4)} if (method, suffix) == ("post", "/network") else {}
        resp = client.request(method, f"/api/v2/reservations/{rid}{suffix}", headers=headers, **kwargs)
        assert resp.status_code == 404
        assert resp.json()["detail"]["reason"] == "reservation_released"
        unknown = client.request(method, f"/api/v2/reservations/deadbeef{suffix}", headers=headers, **kwargs)
        assert unknown.json()["detail"]["reason"] == "reservation_not_found"

    def test_openapi_documents_the_reasons_on_every_id_path(self, client):
        spec = client.get("/openapi.json").json()
        for path, item in spec["paths"].items():
            if "{reservation_id}" in path:
                for operation in item.values():
                    examples = operation["responses"]["404"]["content"]["application/json"]["examples"]
                    assert set(examples) == {
                        "reservation_released", "reservation_expired",
                        "reservation_invalidated", "reservation_not_found",
                    }, path
