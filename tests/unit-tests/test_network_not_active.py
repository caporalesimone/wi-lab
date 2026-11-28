"""API-2: every action on a valid reservation without a network answers 409 / 1007.

REV-9: on a half-stopped network (the client's stop did not complete) 409 / 1012.
"""

import pytest
from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.config import load_config


@pytest.fixture
def idle_reservation(app):
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {load_config().auth_token}"}
        rid = client.post(
            "/api/v2/reservations", headers=headers, json={"duration_seconds": 600},
        ).json()["reservation_id"]
        yield client, headers, rid


ACTIONS = [
    ("post", "/access-point/{rid}/internet/enable", None),
    ("post", "/access-point/{rid}/internet/disable", None),
    ("post", "/reservations/{rid}/qos/profile", {"download_speed_kbit": 1000}),
    ("get", "/reservations/{rid}/qos/profile", None),
    ("delete", "/reservations/{rid}/qos/profile", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ACTIONS)
def test_action_without_network_is_409_1007(idle_reservation, method, path, body):
    client, headers, rid = idle_reservation
    kwargs = {"headers": headers, **({"json": body} if body is not None else {})}
    response = getattr(client, method)("/api/v2" + path.format(rid=rid), **kwargs)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == 1007
    assert response.json()["detail"]["reason"] == "access_point_not_active"


@pytest.mark.parametrize(("method", "path", "body"), ACTIONS)
def test_action_on_a_half_stopped_network_is_409_1012(idle_reservation, method, path, body, context):
    """REV-9: after a client stop that did not complete, the network is not acted on."""
    client, headers, rid = idle_reservation
    manager = context.manager
    device = manager.config.antennas[0].device_id
    manager._stop_failed.add(device)
    try:
        kwargs = {"headers": headers, **({"json": body} if body is not None else {})}
        response = getattr(client, method)("/api/v2" + path.format(rid=rid), **kwargs)
    finally:
        manager._stop_failed.discard(device)
    assert response.status_code == 409, response.text
    assert (response.json()["detail"]["code"], response.json()["detail"]["reason"]) == (1012, "stop_incomplete")


def test_unknown_reservation_is_still_404(idle_reservation):
    client, headers, _rid = idle_reservation
    response = client.post("/api/v2/access-point/deadbeef/internet/enable", headers=headers)
    assert response.status_code == 404


def test_openapi_documents_1007():
    paths = create_app().openapi()["paths"]
    for path, method in (
        ("/api/v2/access-point/{reservation_id}/internet/enable", "post"),
        ("/api/v2/reservations/{reservation_id}/qos/profile", "post"),
    ):
        assert "1007" in paths[path][method]["responses"]["409"]["description"], (path, method)
        assert "1012" in paths[path][method]["responses"]["409"]["description"], (path, method)


@pytest.mark.parametrize(("method", "path", "manager_call"), [
    ("post", "/internet/enable", "enable_internet"),
    ("post", "/internet/disable", "disable_internet"),
])
def test_an_internal_error_on_a_valid_reservation_is_never_404(idle_reservation, monkeypatch, method, path, manager_call, context):
    """REV-11 point 2: a 404 on these calls always means the reservation ended."""
    client, headers, rid = idle_reservation
    manager = context.manager

    def broken(*args, **kwargs):
        raise ValueError("Channel unknown for this network")

    monkeypatch.setattr(manager, manager_call, broken)
    response = getattr(client, method)(f"/api/v2/access-point/{rid}{path}", headers=headers)
    assert response.status_code == 500, response.text
