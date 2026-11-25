"""API-2: every action on a valid reservation without a network answers 409 / 1007."""

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.config import load_config


@pytest.fixture
def idle_reservation():
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {load_config().auth_token}"}
        rid = client.post(
            "/api/v2/reservations", headers=headers, json={"duration_seconds": 600},
        ).json()["reservation_id"]
        yield client, headers, rid


@pytest.mark.parametrize(("method", "path", "body"), [
    ("post", "/internet/enable", None),
    ("post", "/internet/disable", None),
    ("get", "/txpower", None),
    ("post", "/txpower", {"level": 2}),
    ("post", "/qos/profile", {"download_speed_kbit": 1000}),
    ("get", "/qos/profile", None),
    ("delete", "/qos/profile", None),
])
def test_action_without_network_is_409_1007(idle_reservation, method, path, body):
    client, headers, rid = idle_reservation
    kwargs = {"headers": headers, **({"json": body} if body is not None else {})}
    response = getattr(client, method)(f"/api/v2/reservations/{rid}{path}", **kwargs)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == 1007
    assert response.json()["detail"]["reason"] == "network_not_active"


def test_unknown_reservation_is_still_404(idle_reservation):
    client, headers, _rid = idle_reservation
    response = client.post("/api/v2/reservations/deadbeef/internet/enable", headers=headers)
    assert response.status_code == 404


def test_openapi_documents_1007():
    paths = create_app().openapi()["paths"]
    for path, method in (
        ("/api/v2/reservations/{reservation_id}/internet/enable", "post"),
        ("/api/v2/reservations/{reservation_id}/txpower", "get"),
        ("/api/v2/reservations/{reservation_id}/qos/profile", "post"),
    ):
        assert "1007" in paths[path][method]["responses"]["409"]["description"], (path, method)
