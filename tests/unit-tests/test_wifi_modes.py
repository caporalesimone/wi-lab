"""HAP-10 (encryption) and HAP-11 (channel width, Wi-Fi generation)."""

from collections import Counter
from typing import Any
from unittest.mock import Mock

import pytest
from conftest import MOCK_PHY_INFO, network_body
from fastapi.testclient import TestClient
from pydantic import ValidationError

from wilab.api import create_app, dependencies
from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.reservation import ReservationManager
from wilab.wifi.channels import (
    ChannelManager,
    RadioCapabilities,
    channel_layouts,
    parse_phy_capabilities,
)
from wilab.wifi.hostapd import SECURITY_LINES, HostapdManager

BASE = {"ssid": "TestAP", "channel": 6, "password": "testpass123", "band": "2.4ghz", "tx_power_level": 4}


def _request(**overrides) -> NetworkCreateRequest:
    return NetworkCreateRequest(**{"encryption": "wpa2", **BASE, **overrides})


def _config(**overrides: Any) -> str:
    params: dict[str, Any] = {
        "interface": "wlan0", "ssid": "TestAP", "channel": 6, "encryption": "wpa2",
        "password": "testpass123", "hidden": False, "band": "2.4ghz", "country_code": "IT",
    }
    params.update(overrides)
    return HostapdManager()._generate_config(**params)


def _keys(config: str) -> Counter:
    return Counter(line.split("=", 1)[0] for line in config.splitlines() if "=" in line)


# --------------------------------------------------------------------------- capabilities

class TestPhyCapabilities:
    def test_real_mt7921u_reading(self):
        caps = parse_phy_capabilities(MOCK_PHY_INFO)
        assert caps.summary() == {
            "encryptions": ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"],
            "channel_widths": {"2.4ghz": [20, 40], "5ghz": [20, 40, 80]},
            "wifi_generations": {"2.4ghz": [4, 6], "5ghz": [4, 5, 6]},
        }

    def test_without_tkip_there_is_no_wpa1(self):
        caps = parse_phy_capabilities(MOCK_PHY_INFO.replace("* TKIP", "* XXXX"))
        assert "wpa1" not in caps.encryptions()
        with pytest.raises(ValueError, match="wpa1 is not supported on this antenna"):
            caps.check("2.4ghz", "wpa1", 20, 4)

    def test_he_only_counts_for_ap_mode(self):
        # Rename the AP block: HE remains only for managed mode.
        caps = parse_phy_capabilities(MOCK_PHY_INFO.replace("HE Iftypes: AP", "HE Iftypes: mesh point"))
        assert caps.wifi_generations("5ghz") == [4, 5]
        assert caps.wifi_generations("2.4ghz") == [4]

    def test_unknown_radio_offers_only_the_previous_behaviour(self):
        caps = RadioCapabilities()
        assert caps.channel_widths("5ghz") == [20]
        assert caps.wifi_generations("5ghz") == [4]
        assert "wpa1" not in caps.encryptions()

    def test_channel_manager_reads_capabilities_with_channels(self):
        caps = ChannelManager().get_channels("wls16").capabilities
        assert caps.tkip


# --------------------------------------------------------------------------- channel layouts

class TestChannelLayouts:
    @pytest.mark.parametrize(("channel", "center", "above"), [(36, 42, True), (40, 42, False), (44, 42, True), (48, 42, False)])
    def test_5ghz_80mhz_block(self, channel, center, above):
        (layout,) = channel_layouts("5ghz", channel, 80)
        assert layout.channels == (36, 40, 44, 48)
        assert layout.center == center
        assert layout.secondary_above is above

    def test_5ghz_40mhz_pair(self):
        (layout,) = channel_layouts("5ghz", 161, 40)
        assert layout.channels == (157, 161)
        assert layout.center == 159
        assert layout.secondary_above is False

    def test_impossible_5ghz_width(self):
        with pytest.raises(ValueError, match="Channel 181 cannot be used at 80 MHz"):
            channel_layouts("5ghz", 181, 80)

    def test_24ghz_40mhz_both_directions(self):
        assert [layout.secondary_above for layout in channel_layouts("2.4ghz", 6, 40)] == [True, False]
        assert [layout.channels for layout in channel_layouts("2.4ghz", 11, 40)] == [(7, 11)]

    def test_24ghz_has_no_80mhz(self):
        with pytest.raises(ValueError, match="only 20 or 40 MHz"):
            channel_layouts("2.4ghz", 6, 80)


class TestValidateNetwork:
    def test_80mhz_needs_every_channel_of_the_block(self):
        # The mock lists 100 but not 104-112.
        with pytest.raises(ValueError, match="80 MHz on channel 100 is not available"):
            ChannelManager(show_dfs=lambda interface: True).validate_network("wls16", "5ghz", 100, 80, 5, "wpa2")

    def test_165_at_80mhz_needs_169_to_177(self):
        # The mock lists 169 as disabled, as most regulatory domains do.
        with pytest.raises(ValueError, match="80 MHz on channel 165 is not available: Channel 169 is disabled"):
            ChannelManager().validate_network("wls16", "5ghz", 165, 80, 5, "wpa2")

    def test_dfs_channels_inside_a_wide_channel_follow_the_policy(self):
        with pytest.raises(ValueError, match="show_dfs: false"):
            ChannelManager(show_dfs=lambda interface: False).validate_network("wls16", "5ghz", 56, 40, 4, "wpa2")

    def test_24ghz_40mhz_falls_back_to_secondary_below(self):
        # Channel 12 is No IR in the mock: channel 8 uses 4 below it.
        layout = ChannelManager().validate_network("wls16", "2.4ghz", 8, 40, 4, "wpa2")
        assert layout.channels == (4, 8)

    def test_valid_80mhz(self):
        layout = ChannelManager().validate_network("wls16", "5ghz", 149, 80, 6, "wpa3")
        assert layout.center == 155


# --------------------------------------------------------------------------- hostapd.conf

class TestHostapdSecurity:
    @pytest.mark.parametrize("encryption", ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"])
    def test_no_key_is_written_twice(self, encryption):
        config = _config(encryption=encryption, password=None if encryption == "open" else "testpass123")
        assert [key for key, count in _keys(config).items() if count > 1] == []

    @pytest.mark.parametrize("encryption", list(SECURITY_LINES))
    def test_expected_security_lines(self, encryption):
        config = _config(encryption=encryption, password=None if encryption == "open" else "testpass123")
        for line in SECURITY_LINES[encryption]:
            assert line + "\n" in config

    def test_wpa2_wpa3_is_a_real_mixed_mode(self):
        config = _config(encryption="wpa2-wpa3")
        assert "wpa_key_mgmt=WPA-PSK SAE\n" in config
        assert "ieee80211w=1\n" in config
        assert "sae_require_mfp=1\n" in config

    def test_wpa1_is_tkip_without_ht(self):
        config = _config(encryption="wpa1")
        assert "wpa=1\n" in config and "wpa_pairwise=TKIP\n" in config
        assert "ieee80211n=0\n" in config and "ieee80211n=1" not in config
        assert "rsn_pairwise" not in config

    def test_wpa_is_not_written(self):
        from wilab.wifi.hostapd import HostapdError

        with pytest.raises(HostapdError, match="Unsupported encryption"):
            _config(encryption="wpa")


class TestHostapdMode:
    def test_default_is_unchanged_20mhz_80211n(self):
        config = _config()
        assert "ieee80211n=1\n" in config
        for absent in ("ht_capab", "ieee80211ac", "ieee80211ax", "chwidth"):
            assert absent not in config

    def test_24ghz_40mhz(self):
        assert "ht_capab=[HT40+]\n" in _config(channel=1, channel_width=40)
        assert "ht_capab=[HT40-]\n" in _config(channel=11, channel_width=40)

    def test_5ghz_80mhz_wifi5(self):
        config = _config(band="5ghz", channel=40, channel_width=80, wifi_generation=5)
        for line in ("ht_capab=[HT40-]", "ieee80211ac=1", "vht_oper_chwidth=1", "vht_oper_centr_freq_seg0_idx=42"):
            assert line + "\n" in config
        assert "ieee80211ax" not in config

    def test_5ghz_80mhz_wifi6_announces_ac_too(self):
        config = _config(band="5ghz", channel=36, channel_width=80, wifi_generation=6)
        for line in ("ieee80211ac=1", "ieee80211ax=1", "he_oper_chwidth=1", "he_oper_centr_freq_seg0_idx=42"):
            assert line + "\n" in config

    def test_24ghz_wifi6(self):
        config = _config(wifi_generation=6)
        assert "ieee80211ax=1\nhe_oper_chwidth=0\n" in config
        assert "ieee80211ac" not in config


# --------------------------------------------------------------------------- request model

class TestRequestModel:
    def test_defaults_keep_the_previous_behaviour(self):
        req = _request()
        assert (req.channel_width, req.wifi_generation) == (20, 4)

    def test_wpa_is_refused_with_the_way_out(self):
        with pytest.raises(ValidationError, match="'wpa' is no longer accepted: use 'wpa2'"):
            _request(encryption="wpa")

    @pytest.mark.parametrize("extra", [{"channel_width": 40}, {"wifi_generation": 6}])
    def test_wpa1_only_at_20mhz_80211n(self, extra):
        with pytest.raises(ValidationError, match="wpa1 \\(TKIP\\) cannot use 802.11n or newer"):
            _request(encryption="wpa1", **extra)

    def test_wifi5_only_on_5ghz(self):
        with pytest.raises(ValidationError, match="only available on 5ghz"):
            _request(wifi_generation=5)

    def test_80mhz_needs_wifi5_or_6(self):
        with pytest.raises(ValidationError, match="channel_width 80 needs wifi_generation 5 or 6"):
            _request(band="5ghz", channel=36, channel_width=80)

    @pytest.mark.parametrize("value", [{"channel_width": 160}, {"wifi_generation": 7}])
    def test_unknown_values(self, value):
        with pytest.raises(ValidationError):
            _request(**value)


# --------------------------------------------------------------------------- API

@pytest.fixture
def client():
    load_config()
    return TestClient(create_app())


@pytest.fixture
def token():
    return f"Bearer {load_config().auth_token}"


@pytest.fixture
def reservation_id(client, token, monkeypatch):
    cfg = load_config()
    monkeypatch.setattr(
        dependencies, "_reservation_manager", ReservationManager([n.device_id for n in cfg.antennas]),
        raising=False,
    )
    monkeypatch.setattr(dependencies, "_channel_manager", None, raising=False)
    resp = client.post("/api/v1/device-reservation", headers={"Authorization": token}, json={"duration_seconds": 3600})
    assert resp.status_code == 200
    return resp.json()["reservation_id"]


class TestApi:
    def _create(self, client, token, reservation_id, monkeypatch, **body):
        manager = dependencies.get_manager(dependencies.get_config())
        start = Mock()
        monkeypatch.setattr(manager, "start_network", start)
        resp = client.post(
            f"/api/v1/interface/{reservation_id}/network",
            headers={"Authorization": token}, json=network_body(**{"encryption": "wpa2", **BASE, **body}),
        )
        return resp, start

    def test_wpa_returns_422_before_radio_work(self, client, token, reservation_id, monkeypatch):
        resp, start = self._create(client, token, reservation_id, monkeypatch, encryption="wpa")
        assert resp.status_code == 422
        assert "use 'wpa2'" in resp.json()["detail"]["message"]
        start.assert_not_called()

    def test_wpa1_is_accepted_where_supported(self, client, token, reservation_id, monkeypatch):
        resp, start = self._create(client, token, reservation_id, monkeypatch, encryption="wpa1")
        assert resp.status_code == 200, resp.text
        assert start.call_args.args[1].encryption == "wpa1"

    def test_capability_refusal_is_422(self, client, token, reservation_id, monkeypatch):
        no_he = parse_phy_capabilities(MOCK_PHY_INFO.replace("HE Iftypes: AP", "HE Iftypes: mesh point"))
        monkeypatch.setattr("wilab.wifi.channels.parse_phy_capabilities", lambda _output: no_he)
        resp, start = self._create(client, token, reservation_id, monkeypatch, wifi_generation=6)
        assert resp.status_code == 422
        assert "wifi_generation 6 is not supported" in resp.json()["detail"]["message"]
        start.assert_not_called()

    def test_capabilities_are_in_antennas_not_in_status(self, client, token, reservation_id, monkeypatch):
        self._create(client, token, reservation_id, monkeypatch)
        headers = {"Authorization": token}
        networks = client.get("/api/v1/status", headers=headers).json()["networks"]
        assert all("capabilities" not in n for n in networks)
        antenna = client.get(f"/api/v1/antennas/{networks[0]['interface']}", headers=headers).json()
        widths = {g["wifi_generation"]: g["channel_widths"] for g in antenna["bands"]["5ghz"]["wifi_generations"]}
        assert widths[5] == [20, 40, 80]
        assert "wpa1" in antenna["encryptions"]


# --------------------------------------------------------------------------- manager and watchdog

class TestManagerAndWatchdog:
    def test_start_passes_the_mode_to_hostapd_and_reports_it(self, clean_manager, monkeypatch):
        start = Mock()
        monkeypatch.setattr(clean_manager.hostapd_manager, "start", start)
        monkeypatch.setattr(clean_manager.hostapd_manager, "is_running", Mock(return_value=True))
        device = clean_manager.config.antennas[0].device_id
        req = _request(band="5ghz", channel=44, channel_width=80, wifi_generation=6)
        status = clean_manager.start_network(device, req)
        kwargs = start.call_args.kwargs
        assert (kwargs["channel_width"], kwargs["wifi_generation"]) == (80, 6)
        assert kwargs["layout"].center == 42
        assert (status.channel_width, status.wifi_generation) == (80, 6)

    def test_watchdog_restores_with_the_same_mode(self, monkeypatch):
        from wilab.models import NetworkStatus
        from wilab.wifi import watchdog as watchdog_module

        config = dependencies.get_config()
        manager = dependencies.get_manager(config)
        reservations = dependencies.get_reservation_manager(config)
        reservation = reservations.create(0)
        device = reservation.device_id
        monkeypatch.setattr(manager, "release_device", Mock())
        start = Mock()
        monkeypatch.setattr(manager, "start_network", start)
        monkeypatch.setattr(watchdog_module.time, "monotonic", lambda: 1000.0)
        status = NetworkStatus(
            interface=device, active=True, ssid="net", channel=36, band="5ghz", encryption="wpa3",
            password="testpass123", tx_power_level=4, channel_width=80, wifi_generation=5,
        )
        manager.watchdog._restore_ap(reservations, reservation, status, False)
        request = start.call_args.args[1]
        assert (request.channel_width, request.wifi_generation) == (80, 5)
