"""Tests for WiFi channel manager and available-channels API endpoint."""

import pytest
from fastapi.testclient import TestClient
from wilab.api import create_app
from wilab.config import load_config
from wilab.wifi.channels import (
    ChannelManager,
    is_valid_channel_for_band,
    VALID_CHANNELS_5GHZ,
)
from wilab.api import dependencies
from wilab.reservation import ReservationManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a FastAPI test client."""
    load_config()
    app = create_app()
    return TestClient(app)


@pytest.fixture
def valid_token():
    cfg = load_config()
    return f"Bearer {cfg.auth_token}"


@pytest.fixture
def reservation_id(client, valid_token, monkeypatch):
    """Create a reservation and return the reservation_id token."""
    cfg = load_config()
    rmgr = ReservationManager([n.device_id for n in cfg.networks])
    monkeypatch.setattr(dependencies, '_reservation_manager', rmgr, raising=False)
    # Reset channel manager singleton so tests are isolated
    monkeypatch.setattr(dependencies, '_channel_manager', None, raising=False)

    resp = client.post(
        '/api/v1/device-reservation',
        headers={'Authorization': valid_token},
        json={'duration_seconds': 3600},
    )
    assert resp.status_code == 200
    return resp.json()['reservation_id']


# ---------------------------------------------------------------------------
# Unit tests – ChannelManager
# ---------------------------------------------------------------------------

class TestChannelManagerParsing:
    """Test iw output parsing logic."""

    def test_parse_active_channel(self):
        output = "* 2412.0 MHz [1] (20.0 dBm)"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 1
        assert ch.frequency_mhz == 2412
        assert ch.max_power_dbm == 20.0
        assert ch.disabled is False

    def test_parse_disabled_channel(self):
        output = "* 2484.0 MHz [14] (disabled)"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 14
        assert ch.frequency_mhz == 2484
        assert ch.max_power_dbm == 0.0
        assert ch.disabled is True

    def test_parse_channel_with_radar(self):
        output = "* 5260.0 MHz [52] (20.0 dBm) (radar detection)"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        ch = channels[0]
        assert ch.channel == 52
        assert ch.frequency_mhz == 5260
        assert ch.max_power_dbm == 20.0
        assert ch.disabled is False

    def test_parse_integer_frequency(self):
        """iw sometimes omits the decimal point."""
        output = "* 2437 MHz [6] (20.0 dBm)"
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 1
        assert channels[0].channel == 6
        assert channels[0].frequency_mhz == 2437

    def test_parse_mixed_output(self):
        output = """\
Band 1:
    Frequencies:
        * 2412.0 MHz [1] (20.0 dBm)
        * 2484.0 MHz [14] (disabled)
Band 2:
    Frequencies:
        * 5180.0 MHz [36] (23.0 dBm)
        * 5845.0 MHz [169] (disabled)
"""
        channels = ChannelManager._parse_iw_phy_output(output)
        assert len(channels) == 4
        active = [c for c in channels if not c.disabled]
        disabled = [c for c in channels if c.disabled]
        assert len(active) == 2
        assert len(disabled) == 2

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

    def test_disabled_channel_has_zero_power(self):
        mgr = ChannelManager()
        info = mgr.get_channels("wls16")
        ch14 = next(c for c in info.channels_24ghz if c.channel == 14)
        assert ch14.disabled is True
        assert ch14.max_power_dbm == 0.0

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
# API tests – GET /interface/{reservation_id}/network/available-channels
# ---------------------------------------------------------------------------

class TestAvailableChannelsAPI:
    """Test the available-channels endpoint."""

    def test_requires_auth(self, client):
        resp = client.get('/api/v1/interface/fake-id/network/available-channels')
        assert resp.status_code == 401

    def test_invalid_reservation_returns_404(self, client, valid_token):
        resp = client.get(
            '/api/v1/interface/nonexistent/network/available-channels',
            headers={'Authorization': valid_token},
        )
        assert resp.status_code == 404

    def test_returns_both_bands(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 'channels_24ghz' in data
        assert 'channels_5ghz' in data
        assert len(data['channels_24ghz']) > 0
        assert len(data['channels_5ghz']) > 0

    def test_response_includes_interface(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        data = resp.json()
        assert 'interface' in data
        assert isinstance(data['interface'], str)

    def test_channel_fields(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        data = resp.json()
        ch = data['channels_24ghz'][0]
        assert 'channel' in ch
        assert 'frequency_mhz' in ch
        assert 'max_power_dbm' in ch
        assert 'disabled' in ch

    def test_disabled_channel_in_response(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        data = resp.json()
        # Channel 14 should be disabled in 2.4 GHz
        ch14 = next(
            (c for c in data['channels_24ghz'] if c['channel'] == 14), None
        )
        assert ch14 is not None
        assert ch14['disabled'] is True
        assert ch14['max_power_dbm'] == 0.0

    def test_5ghz_disabled_channel(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        data = resp.json()
        ch169 = next(
            (c for c in data['channels_5ghz'] if c['channel'] == 169), None
        )
        assert ch169 is not None
        assert ch169['disabled'] is True

    def test_active_channel_power(self, client, valid_token, reservation_id):
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network/available-channels',
            headers={'Authorization': valid_token},
        )
        data = resp.json()
        ch1 = next(c for c in data['channels_24ghz'] if c['channel'] == 1)
        assert ch1['disabled'] is False
        assert ch1['max_power_dbm'] == 20.0
        assert ch1['frequency_mhz'] == 2412


# ---------------------------------------------------------------------------
# Tests – lifespan channel cache warm-up
# ---------------------------------------------------------------------------

class TestLifespanChannelCacheWarmup:
    """Verify that the app lifespan pre-populates the channel cache."""

    def test_cache_populated_after_startup(self):
        """After TestClient enters the lifespan, the cache should already have entries."""
        import time
        # Reset singleton so lifespan creates a fresh one
        dependencies._channel_manager = None
        load_config()
        app = create_app()
        with TestClient(app):
            cfg = load_config()
            channel_mgr = dependencies._channel_manager
            assert channel_mgr is not None
            # Give the background thread a moment to finish
            time.sleep(0.5)
            for net in cfg.networks:
                info = channel_mgr.get_channels(net.interface)
                assert info.interface == net.interface
                assert len(info.channels_24ghz) > 0

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
        # Reset the singleton so the lifespan creates a fresh one
        monkeypatch.setattr(dependencies, '_channel_manager', None, raising=False)

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

    def test_dual_accepts_24ghz(self):
        assert is_valid_channel_for_band(6, "dual") is True

    def test_dual_accepts_5ghz(self):
        assert is_valid_channel_for_band(36, "dual") is True

    def test_dual_rejects_invalid(self):
        assert is_valid_channel_for_band(99, "dual") is False

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

    def test_disabled_channel_returns_422(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestNet',
                'channel': 14,
                'password': 'testpass123',
                'encryption': 'wpa2',
                'band': '2.4ghz',
                'tx_power_level': 4,
            },
        )
        assert resp.status_code == 422
        assert "disabled" in resp.json()['detail'].lower()

    def test_unsupported_channel_returns_422(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestNet',
                'channel': 173,
                'password': 'testpass123',
                'encryption': 'wpa2',
                'band': '5ghz',
                'tx_power_level': 4,
            },
        )
        # 173 passes static validation (it's in VALID_CHANNELS_5GHZ)
        # but is not in the mock hardware data → 422
        assert resp.status_code == 422
        assert "not supported" in resp.json()['detail'].lower()
