"""Tests for WiFi channel manager and available-channels API endpoint."""

from unittest.mock import Mock

import pytest
from conftest import configured_devices, create_network, network_body
from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.config import load_config
from wilab.reservation import ReservationManager
from wilab.wifi.channels import (
    VALID_CHANNELS_5GHZ,
    ChannelManager,
    FieldError,
    is_valid_channel_for_band,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(app):
    """Create a FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def valid_token():
    cfg = load_config()
    return f"Bearer {cfg.auth_token}"


@pytest.fixture
def reservation_id(client, valid_token, monkeypatch, context):
    """Create a reservation and return the reservation_id token."""
    cfg = load_config()
    rmgr = ReservationManager(configured_devices(cfg))
    monkeypatch.setattr(context, 'reservations', rmgr)

    resp = client.post(
        '/api/v2/reservations',
        headers={'Authorization': valid_token},
        json={'duration_seconds': 3600},
    )
    assert resp.status_code == 200
    return resp.json()['reservation_id']


# ---------------------------------------------------------------------------
# Unit tests – ChannelManager
# ---------------------------------------------------------------------------

class TestChannelManagerParsing:
    """Test iw phy channels output parsing logic."""

    def test_dfs_policy_handles_inline_and_separate_radar_flags(self):
        output = """        * 5260 MHz [52] (radar detection)
        * 5280 MHz [56]
          Radar detection
          DFS state: available
        * 5745 MHz [149]
          Maximum TX power: 23.0 dBm"""
        channels = ChannelManager._parse_iw_phy_output(output, show_dfs_channels=False)
        assert [(ch.channel, ch.disabled, ch.max_power_dbm) for ch in channels] == [
            (52, True, 0.0),
            (56, True, 0.0),
            (149, False, 23.0),
        ]

    def test_parse_active_channel(self):
        output = """        * 2412 MHz [1] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+"""
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 1
        assert ch.frequency_mhz == 2412
        assert ch.max_power_dbm == 20.0
        assert ch.disabled is False

    def test_parse_disabled_channel(self):
        output = "        * 2484 MHz [14] (disabled)"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 14
        assert ch.frequency_mhz == 2484
        assert ch.max_power_dbm == 0.0
        assert ch.disabled is True

    def test_parse_no_ir_channel(self):
        output = """        * 2467 MHz [12] 
          Maximum TX power: 20.0 dBm
          No IR
          Channel widths: 20MHz HT40-"""
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 12
        assert ch.frequency_mhz == 2467
        assert ch.max_power_dbm == 0.0
        assert ch.disabled is True

    def test_parse_channel_with_radar_when_dfs_is_allowed(self):
        output = """        * 5260 MHz [52] 
          Maximum TX power: 20.0 dBm
          Radar detection
          Channel widths: 20MHz HT40- HT40+ VHT80
          DFS state: usable (for 1000 sec)
          DFS CAC time: 60000 ms"""
        channels = ChannelManager._parse_iw_phy_output(output, show_dfs_channels=True)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 52
        assert ch.frequency_mhz == 5260
        assert ch.max_power_dbm == 20.0
        assert ch.disabled is False

    def test_parse_integer_frequency(self):
        """iw uses integer MHz in channels output."""
        output = """        * 2437 MHz [6] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40- HT40+"""
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        assert channels[0].channel == 6
        assert channels[0].frequency_mhz == 2437

    def test_parse_mixed_output(self):
        output = """\
Band 1:
        * 2412 MHz [1] 
          Maximum TX power: 20.0 dBm
          Channel widths: 20MHz HT40+
        * 2467 MHz [12] 
          Maximum TX power: 20.0 dBm
          No IR
          Channel widths: 20MHz HT40-
        * 2484 MHz [14] (disabled)
Band 2:
        * 5180 MHz [36] 
          Maximum TX power: 23.0 dBm
          Channel widths: 20MHz HT40+ VHT80
        * 5845 MHz [169] (disabled)
"""
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 5
        active = [c for c in channels if not c.disabled]
        disabled = [c for c in channels if c.disabled]
        assert len(active) == 2
        assert len(disabled) == 3  # ch 12 (No IR) + ch 14 + ch 169

    def test_parse_empty_output(self):
        channels = ChannelManager._parse_iw_phy_output("")
        assert channels == []

    def test_parse_no_channel_lines(self):
        output = "Some random text\nwithout channel information\n"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert channels == []


class TestChannelManagerResolve:
    """Test channel resolution with mocked iw (via conftest autouse mock)."""

    def test_get_channels_returns_both_bands(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        assert info.interface == "wls16"
        assert len(info.channels_24ghz) > 0
        assert len(info.channels_5ghz) > 0

    def test_24ghz_channels_are_correct(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        channels = {ch.channel for ch in info.channels_24ghz}
        # Mock data has channels 1-14
        assert 1 in channels
        assert 13 in channels
        assert 14 in channels

    def test_5ghz_channels_are_correct(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        channels = {ch.channel for ch in info.channels_5ghz}
        assert 36 in channels
        assert 165 in channels

    def test_6ghz_channels_are_not_listed(self):
        """Wi-Fi 6E antennas report 6 GHz too: 6695 MHz is also numbered 149."""
        info = ChannelManager().get_channels("wls16")
        assert all(5000 <= ch.frequency_mhz < 5925 for ch in info.channels_5ghz)
        assert [ch.frequency_mhz for ch in info.channels_5ghz if ch.channel == 149] == [5745]
        assert 1 not in {ch.channel for ch in info.channels_5ghz}

    @pytest.mark.parametrize(("band", "channel", "width", "generation", "field"), [
        ("2.4ghz", 14, 20, 4, "channel"),          # disabled by the regulatory domain
        ("5ghz", 165, 80, 5, "channel_width"),     # 169, inside the 80 MHz block, is disabled
        ("2.4ghz", 6, 80, 6, "channel_width"),     # 80 MHz does not exist on 2.4 GHz
    ])
    def test_antenna_checks_name_the_refused_field(self, band, channel, width, generation, field):
        with pytest.raises(FieldError) as exc:
            ChannelManager().validate_network("wls16", band, channel, width, generation, "wpa2")
        assert exc.value.field == field

    def test_disabled_channel_has_zero_power(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        ch14 = next(c for c in info.channels_24ghz if c.channel == 14)
        assert ch14.disabled is True
        assert ch14.max_power_dbm == 0.0

    def test_no_ir_channel_is_disabled(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        ch12 = next(c for c in info.channels_24ghz if c.channel == 12)
        assert ch12.disabled is True
        assert ch12.max_power_dbm == 0.0

    def test_cache_returns_same_object(self):
        mgr = ChannelManager()
        first = mgr.get_channels("wls16")
        second = mgr.get_channels("wls16")
        assert first is second

    def test_invalidate_single_interface(self):
        mgr = ChannelManager()
        mgr.get_channels("wls16")
        mgr.invalidate("wls16")
        # After invalidation, a fresh query should return a new object
        new = mgr.get_channels("wls16")
        assert new.interface == "wls16"

    def test_invalidate_all(self):
        mgr = ChannelManager()
        mgr.get_channels("wls16")
        mgr.invalidate()
        new = mgr.get_channels("wls16")
        assert new.interface == "wls16"


# ---------------------------------------------------------------------------
# API tests – GET /api/v2/antennas/{interface}
# ---------------------------------------------------------------------------

def _set_show_dfs_channels(context, value: bool) -> None:
    for device in context.devices.all():
        device.show_dfs_channels = value
    context.channels.invalidate()


class TestAntennasAPI:
    """Antennas: the managed radios and the options of a create on each."""

    def test_requires_auth(self, client):
        assert client.get('/api/v2/antennas/wls16').status_code == 401

    def test_the_list_is_in_status_only(self, client, valid_token):
        """GET /antennas repeated antennas[] of GET /status (removed 2026-11-27)."""
        headers = {'Authorization': valid_token}
        assert client.get('/api/v2/antennas', headers=headers).status_code == 404
        listed = client.get('/api/v2/status', headers=headers).json()["antennas"]
        assert {"display_name": "bench-antenna-1", "interface": "wls16"} in [
            {k: a[k] for k in ("display_name", "interface")} for a in listed
        ]

    def test_unknown_antenna_returns_404(self, client, valid_token):
        resp = client.get('/api/v2/antennas/wlan99', headers={'Authorization': valid_token})
        assert resp.status_code == 404

    def test_details(self, client, valid_token, monkeypatch):
        from wilab.api.routes import antennas
        from wilab.wifi.discovery import DeviceInfo
        monkeypatch.setattr(antennas, "detect_device", lambda i: DeviceInfo("usb", "2-1", "mt7921u"))
        data = client.get('/api/v2/antennas/wls16', headers={'Authorization': valid_token}).json()
        assert data["interface"] == "wls16"
        assert data["device"] == {"bus": "usb", "address": "2-1", "driver": "mt7921u"}
        assert data["encryptions"] == ["open", "wpa1", "wpa2", "wpa3", "wpa2-wpa3"]
        assert data["bands"]["5ghz"]["wifi_generations"] == [
            {"wifi_generation": 4, "channel_widths": [20, 40]},
            {"wifi_generation": 5, "channel_widths": [20, 40, 80]},
            {"wifi_generation": 6, "channel_widths": [20, 40, 80]},
        ]
        channels = {c["channel"]: c for c in data["bands"]["5ghz"]["channels"]}
        assert channels[36] == {"channel": 36, "frequency_mhz": 5180, "max_power_dbm": 23.0,
                                "dfs": False, "channel_widths": [20, 40, 80]}
        assert channels[165]["channel_widths"] == [20]          # 169 is disabled
        assert 169 not in channels                               # disabled channels are not listed
        assert all(c["frequency_mhz"] < 5925 for c in channels.values())   # no 6 GHz
        assert 14 not in {c["channel"] for c in data["bands"]["2.4ghz"]["channels"]}

    def test_device_is_null_when_sysfs_does_not_show_it(self, client, valid_token, monkeypatch):
        from wilab.api.routes import antennas
        monkeypatch.setattr(antennas, "detect_device", lambda i: None)
        data = client.get('/api/v2/antennas/wls16', headers={'Authorization': valid_token}).json()
        assert data["device"] is None

    def test_every_listed_choice_is_accepted_by_the_create_check(self, client, valid_token, context):
        """The lists and the create use the same rules: no combination is refused."""
        _set_show_dfs_channels(context, True)
        data = client.get('/api/v2/antennas/wls16', headers={'Authorization': valid_token}).json()
        mgr = context.channels
        checked = 0
        for band, options in data["bands"].items():
            for generation in options["wifi_generations"]:
                for width in generation["channel_widths"]:
                    for channel in options["channels"]:
                        if width in channel["channel_widths"]:
                            mgr.validate_network(
                                "wls16", band, channel["channel"], width, generation["wifi_generation"], "wpa2",
                            )
                            checked += 1
        assert checked > 50


# ---------------------------------------------------------------------------
# Tests – lifespan channel cache warm-up
# ---------------------------------------------------------------------------

class TestLifespanChannelCacheWarmup:
    """Verify that antennas added by discovery get their channel cache warmed."""

    def test_cache_populated_when_discovery_adds_an_antenna(self, monkeypatch):
        import time

        from wilab.api import context as context_module
        from wilab.wifi import discovery
        from wilab.wifi.discovery import DiscoveredRadio

        monkeypatch.setattr(context_module, "_initial_devices", lambda config: [])
        monkeypatch.setattr(discovery, "discover_radios", lambda **kwargs: [
            DiscoveredRadio("wls16", "phy0", None),
        ])
        app = create_app()   # no configured antenna: discovery adds wls16
        with TestClient(app):
            deadline = time.monotonic() + 5
            while "wls16" not in app.state.context.channels._cache:
                assert time.monotonic() < deadline, "channel cache was not warmed"
                time.sleep(0.01)

    def test_warmup_tolerates_failure(self, monkeypatch):
        """If iw fails for one interface the app should still start."""
        from wilab.wifi import channels as ch_mod

        original_execute_iw = ch_mod.execute_iw

        def failing_execute_iw(args):
            # Fail only for interface info lookup (first call per interface)
            if len(args) >= 2 and args[1] == "info" and not args[0].startswith("phy"):
                raise RuntimeError("simulated iw failure")
            return original_execute_iw(args)

        monkeypatch.setattr(ch_mod, "execute_iw", failing_execute_iw)

        app = create_app()
        # App should start without raising despite iw failures
        with TestClient(app):
            pass


# ---------------------------------------------------------------------------
# Tests – is_valid_channel_for_band (static validation)
# ---------------------------------------------------------------------------

class TestIsValidChannelForBand:
    """Test the hardware-independent static channel validation."""

    def test_valid_24ghz_channels(self):
        for ch in range(1, 15):
            assert is_valid_channel_for_band(ch, "2.4ghz") is True

    def test_invalid_24ghz_channel_zero(self):
        assert is_valid_channel_for_band(0, "2.4ghz") is False

    def test_invalid_24ghz_channel_15(self):
        assert is_valid_channel_for_band(15, "2.4ghz") is False

    def test_valid_5ghz_unii1(self):
        for ch in (36, 40, 44, 48):
            assert is_valid_channel_for_band(ch, "5ghz") is True

    def test_valid_5ghz_unii2(self):
        for ch in (52, 56, 60, 64):
            assert is_valid_channel_for_band(ch, "5ghz") is True

    def test_valid_5ghz_unii2_extended(self):
        for ch in (100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144):
            assert is_valid_channel_for_band(ch, "5ghz") is True

    def test_valid_5ghz_unii3(self):
        for ch in (149, 153, 157, 161, 165, 169, 173, 177):
            assert is_valid_channel_for_band(ch, "5ghz") is True

    def test_invalid_5ghz_channel(self):
        assert is_valid_channel_for_band(50, "5ghz") is False
        assert is_valid_channel_for_band(99, "5ghz") is False
        assert is_valid_channel_for_band(180, "5ghz") is False

    def test_dual_is_not_a_single_band(self):
        with pytest.raises(ValueError, match="Unknown band"):
            is_valid_channel_for_band(6, "dual")

    def test_channel_sets_include_169_173_177(self):
        """Channels 169, 173, 177 must be in the 5 GHz set."""
        assert 169 in VALID_CHANNELS_5GHZ
        assert 173 in VALID_CHANNELS_5GHZ
        assert 177 in VALID_CHANNELS_5GHZ


# ---------------------------------------------------------------------------
# Tests – ChannelManager.validate_channel (hardware validation)
# ---------------------------------------------------------------------------

class TestValidateChannel:
    """Test hardware-aware channel validation against cached data."""

    def test_valid_active_channel(self):
        mgr = ChannelManager()
        # Channel 6 is active in mock data — should not raise
        mgr.validate_channel("wls16", 6, "2.4ghz")

    def test_valid_5ghz_channel(self):
        mgr = ChannelManager()
        mgr.validate_channel("wls16", 36, "5ghz")

    def test_disabled_channel_raises(self):
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="disabled"):
            mgr.validate_channel("wls16", 14, "2.4ghz")

    def test_disabled_5ghz_channel_raises(self):
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="disabled"):
            mgr.validate_channel("wls16", 169, "5ghz")

    def test_no_ir_channel_raises(self):
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="disabled"):
            mgr.validate_channel("wls16", 12, "2.4ghz")

    def test_unsupported_channel_raises(self):
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="not supported"):
            mgr.validate_channel("wls16", 50, "5ghz")

    def test_error_includes_band(self):
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="band 5ghz"):
            mgr.validate_channel("wls16", 50, "5ghz")

    def test_wrong_band_for_channel(self):
        mgr = ChannelManager()
        # Channel 6 exists in 2.4 GHz but not in 5 GHz pool
        with pytest.raises(ValueError, match="not supported"):
            mgr.validate_channel("wls16", 6, "5ghz")


# ---------------------------------------------------------------------------
# API tests – channel validation on network creation
# ---------------------------------------------------------------------------

class TestNetworkCreationChannelValidation:
    """Test that POST /network rejects invalid/disabled channels."""

    @pytest.mark.parametrize("show_dfs_channels", [False, True])
    def test_show_dfs_channels_applies_to_listing_and_creation(
        self, client, valid_token, reservation_id, monkeypatch, show_dfs_channels, context,
    ):
        _set_show_dfs_channels(context, show_dfs_channels)
        start_network = Mock()
        monkeypatch.setattr(context.manager, "start_network", start_network)
        url = f"/api/v2/reservations/{reservation_id}/network"
        headers = {"Authorization": valid_token}

        listing = client.get("/api/v2/antennas/wls16", headers=headers)
        assert listing.status_code == 200
        channels = {ch["channel"]: ch for ch in listing.json()["bands"]["5ghz"]["channels"]}
        assert (52 in channels) is show_dfs_channels
        if show_dfs_channels:
            assert channels[52]["dfs"] is True and channels[52]["max_power_dbm"] == 20.0
        assert channels[36]["dfs"] is False

        request = {
            "ssid": "TestNet", "channel": 52, "encryption": "open",
            "band": "5ghz", "tx_power_level": 4,
        }
        response = create_network(client, headers, url, network_body(**request))[1]
        if not show_dfs_channels:
            assert response.status_code == 422
            assert response.json()["detail"]["message"].startswith("radio.channel: DFS channel 52")
            assert "show_dfs_channels: false" in response.json()["detail"]["message"]
            start_network.assert_not_called()
            response = create_network(client, headers, url, network_body(**{**request, "channel": 36}))[1]
        assert response.status_code == 200
        start_network.assert_called_once()

    def test_disabled_channel_returns_422(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v2/reservations/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestNet', channel=14, password='testpass123', encryption='wpa2', band='2.4ghz', tx_power_level=4),
        )
        assert resp.status_code == 422
        assert "disabled" in resp.json()['detail']['message'].lower()

    def test_unsupported_channel_returns_422(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v2/reservations/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestNet', channel=173, password='testpass123', encryption='wpa2', band='5ghz', tx_power_level=4),
        )
        # 173 passes static validation (it's in VALID_CHANNELS_5GHZ)
        # but is not in the mock hardware data → 422
        assert resp.status_code == 422
        assert "not supported" in resp.json()['detail']['message'].lower()

    def test_no_ir_channel_returns_422(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v2/reservations/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestNet', channel=12, password='testpass123', encryption='wpa2', band='2.4ghz', tx_power_level=4),
        )
        # Channel 12 has No IR in mock data — treated as disabled
        assert resp.status_code == 422
        assert "disabled" in resp.json()['detail']['message'].lower()


class TestChannelCacheRefresh:
    """BUG-4: a cached refusal is checked against a fresh reading; one cache for the service."""

    NO_IR = """Band 2:
        * 5180 MHz [36] 
          Maximum TX power: 20.0 dBm
          No IR
"""
    ALLOWED = """Band 2:
        * 5180 MHz [36] 
          Maximum TX power: 20.0 dBm
"""

    def _fake_iw(self, monkeypatch, outputs):
        from wilab.wifi import channels as channels_module

        readings = iter(outputs)
        calls = []

        def iw(args):
            calls.append(args)
            if args[-1] == "info":
                return "Interface wlan0\n\twiphy 0\n"
            return next(readings)

        monkeypatch.setattr(channels_module, "execute_iw", iw)
        return calls

    def test_channel_cached_before_the_regulatory_domain_is_accepted_after_a_reread(self, monkeypatch):
        self._fake_iw(monkeypatch, [self.NO_IR, self.ALLOWED])
        mgr = ChannelManager()
        assert next(c for c in mgr.get_channels("wlan0").channels_5ghz if c.channel == 36).disabled
        mgr.validate_channel("wlan0", 36, "5ghz")  # before BUG-4: 422 until a restart

    def test_a_real_refusal_still_refuses_after_one_reread(self, monkeypatch):
        calls = self._fake_iw(monkeypatch, [self.NO_IR, self.NO_IR])
        mgr = ChannelManager()
        with pytest.raises(ValueError, match="disabled"):
            mgr.validate_channel("wlan0", 36, "5ghz")
        assert sum(1 for c in calls if c[-1] == "channels") == 2

    def test_manager_and_api_share_one_cache(self, context):
        manager = context.manager
        assert manager._channel_manager is context.channels


class TestWeatherRadarChannels:
    """HAP-9: 120, 124 and 128 need a 10-minute radar check; never offered, 422 on a create."""

    def test_parsed_as_disabled_even_with_dfs_shown(self):
        output = "\n".join(
            f"* {5000 + 5 * ch} MHz [{ch}]\n  Maximum TX power: 23.0 dBm\n  Radar detection"
            for ch in (116, 120, 124, 128, 132)
        )
        parsed = {c.channel: c.disabled for c in ChannelManager._parse_iw_phy_output(output, show_dfs_channels=True)}
        assert parsed == {116: False, 120: True, 124: True, 128: True, 132: False}

    @pytest.mark.parametrize("channel", [120, 124, 128])
    def test_create_check_refuses_them_with_the_reason(self, channel):
        with pytest.raises(FieldError, match="10-minute radar check") as exc:
            ChannelManager(show_dfs_channels=lambda _i: True).validate_network("wls16", "5ghz", channel, 20, 5, "wpa2")
        assert exc.value.field == "channel"

    def test_not_listed_as_usable(self):
        info = ChannelManager(show_dfs_channels=lambda _i: True).get_channels("wls16")
        assert all(c.disabled for c in info.channels_5ghz if c.channel in (120, 124, 128))
