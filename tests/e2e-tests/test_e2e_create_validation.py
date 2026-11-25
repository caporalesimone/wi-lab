"""BUG-1 and HAP-1 on the real service: request validation and SSIDs with escapes.

Each accepted create is checked on the air interface with `iw dev <if> info`.
"""

import pytest
from wilab_e2e import Server, WiLab, detail_code


# iw prints non-printable and non-ASCII SSID bytes as \xNN escapes.
def _iw_ssid(ssid: str) -> str:
    out = []
    for byte in ssid.encode("utf-8"):
        char = chr(byte)
        out.append(char if 0x20 <= byte < 0x7F and char != "\\" else f"\\x{byte:02x}")
    return "".join(out)


REJECTED = [
    pytest.param({"ssid": "a" * 33}, id="ssid-33-bytes"),
    pytest.param({"ssid": "a" * 80}, id="ssid-80-bytes"),
    pytest.param({"ssid": "è" * 17}, id="ssid-34-utf8-bytes"),
    pytest.param({"ssid": "x\ninterface=eth0"}, id="ssid-newline"),
    pytest.param({"ssid": "x\rabc"}, id="ssid-cr"),
    pytest.param({"ssid": "x\tabc"}, id="ssid-tab"),
    pytest.param({"password": "abc"}, id="wpa2-password-short"),
    pytest.param({"password": "p" * 64}, id="wpa2-password-64"),
    pytest.param({"password": None}, id="wpa2-no-password"),
    pytest.param({"channel": 36}, id="channel-36-on-2.4ghz"),
]

ACCEPTED = [
    pytest.param({"ssid": "b" * 32}, id="ssid-32-bytes"),
    pytest.param({"ssid": "è" * 16}, id="ssid-32-utf8-bytes"),
    pytest.param({"password": "p" * 8}, id="wpa2-password-8"),
    pytest.param({"password": "p" * 63}, id="wpa2-password-63"),
    pytest.param({"ssid": "Caffè ☕"}, id="hap1-non-ascii-2.4ghz"),
    pytest.param({"ssid": "Caffè ☕", "band": "5ghz", "channel": 36}, id="hap1-non-ascii-5ghz"),
    pytest.param({"ssid": 'my"net\\'}, id="hap1-quote-backslash"),
    pytest.param({"ssid": "Caffè ☕", "hidden": True}, id="hap1-hidden-non-ascii"),
]


@pytest.mark.parametrize("overrides", REJECTED)
def test_invalid_create_is_rejected_before_hostapd(wilab: WiLab, server: Server, overrides: dict) -> None:
    antenna = wilab.reserve()
    response = wilab.create(antenna, **overrides)
    assert response.status_code == 422, response.text
    assert detail_code(response) == 422
    assert server.iw_info(antenna.interface).get("type") != "AP"


@pytest.mark.parametrize("overrides", ACCEPTED)
def test_valid_create_starts_first_time_with_correct_ssid(
    wilab: WiLab, server: Server, overrides: dict,
) -> None:
    antenna = wilab.reserve()
    response = wilab.create(antenna, **overrides)
    # 200 on the first attempt: no radio failure from an SSID comparison (HAP-1).
    assert response.status_code == 200, response.text
    info = server.iw_info(antenna.interface)
    assert info.get("type") == "AP"
    assert info.get("ssid") == _iw_ssid(overrides.get("ssid", "wilab-e2e"))
    assert wilab.delete_network(antenna) == 200
