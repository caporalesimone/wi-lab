"""REV-11 point 4 and API-6: request bodies take only the JSON types they document."""

import pytest
from conftest import network_body
from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.config import load_config

VALID = {"ssid": "strict", "channel": 6, "encryption": "open", "band": "2.4ghz", "tx_power_level": 4}


@pytest.fixture
def api():
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {load_config().auth_token}"}
        rid = client.post(
            "/api/v2/reservations", headers=headers, json={"duration_seconds": 600},
        ).json()["reservation_id"]
        yield client, headers, rid


@pytest.mark.parametrize("duration", ["600", True, 600.0])
def test_reservation_duration_must_be_an_integer(api, duration):
    client, headers, _rid = api
    response = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": duration})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(("field", "value"), [
    ("channel", "6"), ("channel", True), ("channel", 6.0),
    ("tx_power_level", "4"), ("tx_power_level", True),
    ("hidden", "false"), ("hidden", 0),
    ("internet_enabled", "true"), ("captive_portal", 1),
    ("ssid", 123),
])
def test_create_rejects_values_of_another_type(api, field, value):
    client, headers, rid = api
    body = network_body(**{**VALID, field: value})
    response = client.post(f"/api/v2/access-point/{rid}", headers=headers, json=body)
    assert response.status_code == 422, response.text
