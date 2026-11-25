"""Sectioned network API (API-8, ARCH-3): create body, GET .../network response, Swagger groups."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wilab.api import create_app
from wilab.models import NetworkCreateBody, NetworkResponse, NetworkStatus, NetworkTxPower

CREATE = "/api/v1/interface/{reservation_id}/network"


@pytest.fixture(scope="module")
def spec():
    return TestClient(create_app()).get("/openapi.json").json()


def _body(**sections):
    body = {
        "radio": {"band": "2.4ghz", "channel": 6, "tx_power_level": 4},
        "wifi": {"ssid": "net", "security": {"encryption": "wpa2", "password": "testpass123"}},
    }
    body.update(sections)
    return body


class TestCreateBody:
    def test_only_radio_and_wifi_are_required(self):
        req = NetworkCreateBody(**_body()).to_request()
        assert (req.channel_width, req.wifi_generation, req.hidden) == (20, 4, False)
        assert req.internet_enabled is None and req.captive_portal is False

    def test_sections_map_to_the_settings(self):
        req = NetworkCreateBody(**_body(
            radio={"band": "5ghz", "channel": 36, "channel_width": 80, "wifi_generation": 6, "tx_power_level": 2},
            internet={"enabled": False}, captive_portal={"enabled": True},
        )).to_request()
        assert (req.band, req.channel, req.channel_width, req.wifi_generation) == ("5ghz", 36, 80, 6)
        assert (req.internet_enabled, req.captive_portal, req.tx_power_level) == (False, True, 2)

    def test_errors_name_the_field_in_the_body(self):
        with pytest.raises(ValidationError, match="wifi.security.encryption: 'wpa' is no longer accepted"):
            NetworkCreateBody(**_body(wifi={"ssid": "n", "security": {"encryption": "wpa", "password": "testpass123"}}))
        with pytest.raises(ValidationError, match="wifi.security.password: .*8 to 63 bytes|requires a password"):
            NetworkCreateBody(**_body(wifi={"ssid": "n", "security": {"encryption": "wpa2", "password": "short"}}))

    def test_flat_body_is_refused(self):
        with pytest.raises(ValidationError):
            NetworkCreateBody(ssid="n", channel=6, band="2.4ghz", encryption="open", tx_power_level=4)


class TestResponse:
    def test_inactive_network_has_only_the_reservation(self):
        view = NetworkResponse.from_status(NetworkStatus(interface="wlan0", active=False, expires_in=10))
        data = view.model_dump()
        assert data["reservation"] == {"expires_at": None, "expires_in": 10}
        assert all(data[key] is None for key in ("radio", "wifi", "ip", "internet", "captive_portal", "clients"))

    def test_active_network_sections(self):
        st = NetworkStatus(
            interface="wlan0", active=True, ssid="net", channel=36, band="5ghz", encryption="wpa3",
            password="testpass123", hidden=True, subnet="192.168.120.0/24", internet_enabled=True,
            channel_width=80, reported_channel_width=40, wifi_generation=5,
            tx_power=NetworkTxPower(requested_level=3),
            dhcp={"interface": "wlan0", "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
                  "config_file": "/tmp/x.conf", "dhcp_range": "192.168.120.10,192.168.120.250"},
            clients=[],
        )
        data = NetworkResponse.from_status(st, dns_server="9.9.9.9").model_dump()
        assert data["radio"]["channel_width"] == {"requested": 80, "reported": 40}
        assert data["wifi"]["security"] == {"encryption": "wpa3", "password": "testpass123"}
        assert data["ip"] == {
            "subnet": "192.168.120.0/24", "gateway": "192.168.120.1",
            "dhcp_range": {"start": "192.168.120.10", "end": "192.168.120.250"}, "dns_server": "9.9.9.9",
        }
        assert "config_file" not in str(data)


class TestSwagger:
    def test_create_examples_are_valid_bodies_with_every_optional_field(self, spec):
        examples = spec["paths"]["/api/v1/interface/{reservation_id}/network"]["post"]["requestBody"][
            "content"]["application/json"]["examples"]
        assert examples
        for name, example in examples.items():
            value = example["value"]
            NetworkCreateBody(**value)
            assert set(value) == {"radio", "wifi", "internet", "captive_portal"}, name
            assert {"channel_width", "wifi_generation"} <= set(value["radio"]), name
            assert "hidden" in value["wifi"], name

    def test_get_examples_match_the_response_model(self, spec):
        examples = spec["paths"]["/api/v1/interface/{reservation_id}/network"]["get"]["responses"]["200"][
            "content"]["application/json"]["examples"]
        for example in examples.values():
            NetworkResponse(**example["value"])

    @pytest.mark.parametrize(("method", "path"), [
        ("delete", "/api/v1/device-reservation/all"),
        ("get", "/api/v1/debug"),
    ])
    def test_maintenance_operations_are_only_under_maintenance(self, spec, method, path):
        assert spec["paths"][path][method]["tags"] == ["Maintenance"]

    def test_release_all_still_wins_over_a_reservation_id(self, spec):
        paths = list(spec["paths"])
        assert paths.index("/api/v1/device-reservation/all") < paths.index("/api/v1/device-reservation/{reservation_id}")
