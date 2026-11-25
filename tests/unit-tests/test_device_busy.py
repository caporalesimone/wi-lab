"""RACE-1: requests never wait without limit for an adapter held by another operation."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app, dependencies
from wilab.config import load_config
from wilab.reservation import DeviceBusyError, ReservationManager


def test_hold_with_timeout_raises_when_the_device_is_busy():
    mgr = ReservationManager(["wlan0"])
    reservation = mgr.create(60)
    holder_ready, release = threading.Event(), threading.Event()

    def holder():
        with mgr.hold(reservation.reservation_id):
            holder_ready.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert holder_ready.wait(5)
        start = time.monotonic()
        with pytest.raises(DeviceBusyError), mgr.hold(reservation.reservation_id, timeout=0.2):
            pass
        assert time.monotonic() - start < 1
    finally:
        release.set()
        thread.join()
    with mgr.hold(reservation.reservation_id, timeout=0.2) as held:
        assert held is reservation


@pytest.fixture
def valid_token() -> str:
    return f"Bearer {load_config().auth_token}"


@pytest.fixture
def busy_adapter(valid_token, monkeypatch):
    """A reserved adapter whose device lock another thread holds until released."""
    monkeypatch.setattr(dependencies, "DEVICE_BUSY_TIMEOUT", 0.3)
    with TestClient(create_app()) as client:
        headers = {"Authorization": valid_token}
        reservation = client.post(
            "/api/v2/reservations", headers=headers, json={"duration_seconds": 3600},
        ).json()
        manager = dependencies.get_manager(dependencies.get_config())
        held, release = threading.Event(), threading.Event()

        def holder():
            device = dependencies.get_reservation_manager().device_for(reservation["reservation_id"])
            with manager.device_lock(device):
                held.set()
                release.wait(10)

        thread = threading.Thread(target=holder)
        thread.start()
        assert held.wait(5)
        try:
            yield client, headers, reservation["reservation_id"]
        finally:
            release.set()
            thread.join()


@pytest.mark.parametrize(("method", "path", "body"), [
    ("get", "/network", None),
    ("delete", "/network", None),
    ("post", "/internet/enable", None),
    ("get", "/txpower", None),
    ("post", "/txpower", {"level": 2}),
    ("get", "/qos/profile", None),
])
def test_busy_adapter_answers_503_1006_with_retry_after(busy_adapter, method, path, body):
    client, headers, rid = busy_adapter
    start = time.monotonic()
    kwargs = {"headers": headers, **({"json": body} if body is not None else {})}
    response = getattr(client, method)(f"/api/v2/reservations/{rid}{path}", **kwargs)
    assert time.monotonic() - start < 2
    assert response.status_code == 503, response.text
    assert response.headers["Retry-After"] == "2"
    assert response.json()["detail"]["code"] == 1006
    assert response.json()["detail"]["reason"] == "device_busy"


def test_many_waiting_requests_do_not_block_status(busy_adapter):
    client, headers, rid = busy_adapter
    with ThreadPoolExecutor(max_workers=45) as pool:
        polls = [
            pool.submit(client.get, f"/api/v2/reservations/{rid}/network", headers=headers) for _ in range(45)
        ]
        start = time.monotonic()
        assert client.get("/api/v2/status", headers=headers).status_code == 200
        assert time.monotonic() - start < 5
        assert {p.result(timeout=10).status_code for p in polls} == {503}


def test_openapi_documents_device_busy():
    schema = create_app().openapi()
    response = schema["paths"]["/api/v2/reservations/{reservation_id}/network"]["get"]["responses"]["503"]
    assert "1006" in response["description"]
    assert response["headers"]["Retry-After"]["example"] == 2
    assert "device_busy" in response["content"]["application/json"]["examples"]
    create = schema["paths"]["/api/v2/reservations/{reservation_id}/network"]["post"]["responses"]["503"]
    assert "1006" not in create.get("description", "")  # a create waits for the adapter
