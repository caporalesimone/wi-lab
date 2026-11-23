"""Validation of the network creation request (Fable BUG-1)."""

import pytest
from pydantic import ValidationError

from wilab.models import NetworkCreateRequest

BASE = {"ssid": "TestAP", "channel": 6, "encryption": "open", "band": "2.4ghz", "tx_power_level": 4}


def make(**overrides):
    return NetworkCreateRequest(**{**BASE, **overrides})


@pytest.mark.parametrize("overrides, message", [
    ({"ssid": ""}, "1 to 32 bytes"),
    ({"ssid": "x" * 33}, "1 to 32 bytes"),
    ({"ssid": "è" * 17}, "1 to 32 bytes"),  # 17 chars, 34 bytes
    ({"ssid": "x\ninterface=eth0"}, "control characters"),
    ({"ssid": "x\rinterface=eth0"}, "control characters"),
    ({"ssid": "tab\there"}, "control characters"),
    ({"ssid": "nul\x00"}, "control characters"),
    ({"ssid": "del\x7f"}, "control characters"),
    ({"channel": 99, "band": "5ghz"}, "not a valid WiFi channel for band 5ghz"),
    ({"channel": 36, "band": "2.4ghz"}, "not a valid WiFi channel for band 2.4ghz"),
    ({"encryption": "wpa2"}, "Password required"),
    ({"encryption": "wpa3", "password": "abc"}, "8 to 63 bytes"),
    ({"encryption": "wpa2", "password": "x" * 64}, "8 to 63 bytes"),
    ({"encryption": "wpa2", "password": "è" * 32}, "8 to 63 bytes"),  # 64 bytes
    ({"encryption": "wpa2", "password": "pass\nword123"}, "control characters"),
    ({"encryption": "open", "password": "x\ninterface=eth0"}, "control characters"),
])
def test_invalid_requests_are_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make(**overrides)


@pytest.mark.parametrize("overrides", [
    {"ssid": "a"},
    {"ssid": "x" * 32},
    {"ssid": "Caffè ☕"},
    {"ssid": 'my"net\\'},
    {"ssid": "è" * 16},  # 32 bytes
    {"channel": 36, "band": "5ghz"},
    {"encryption": "wpa2", "password": "x" * 8},
    {"encryption": "wpa2-wpa3", "password": "x" * 63},
    {"encryption": "wpa2", "password": "pässwörd"},
])
def test_valid_requests_are_accepted(overrides):
    req = make(**overrides)
    for key, value in overrides.items():
        assert getattr(req, key) == value
