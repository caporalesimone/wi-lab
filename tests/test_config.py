import os

import pytest

from wilab.config import (
    CAPABILITY_REGISTRY,
    AppConfig,
    Capability,
    CapabilityType,
    NetworkEntry,
    load_config,
    normalise_capability_id,
)


class TestConfigLoading:
    """Tests for configuration file loading and validation."""

    def test_load_config_example(self):
        """Test loading the config.example.yaml file."""
        path = os.path.join(os.getcwd(), 'config.example.yaml')
        cfg = load_config(path)
        assert isinstance(cfg, AppConfig)
        assert cfg.api_port == 8080
        assert cfg.networks[0].device_id == 'wlxbc071dc527d6'
        assert cfg.networks[0].interface == 'wlxbc071dc527d6'

    def test_load_config_default_path(self):
        """Test loading config from default location."""
        cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.auth_token == "secret-token-12345"

    def test_config_has_required_fields(self):
        """Test that loaded config has all required fields."""
        cfg = load_config()
        assert hasattr(cfg, 'auth_token')
        assert hasattr(cfg, 'api_port')
        assert hasattr(cfg, 'dhcp_base_network')
        assert hasattr(cfg, 'upstream_interface')
        assert hasattr(cfg, 'dns_server')
        assert hasattr(cfg, 'networks')

    def test_config_defaults(self):
        """Test that config has correct default values."""
        cfg = load_config()
        assert cfg.api_port == 8080
        assert cfg.internet_enabled_by_default is True
        assert cfg.min_timeout == 60
        assert cfg.max_timeout == 86400  # 24 hours

    def test_config_file_not_found(self):
        """Test that SystemExit is raised for missing config file."""
        with pytest.raises(SystemExit) as exc_info:
            load_config('/nonexistent/path/config.yaml')
        assert "Configuration file not found" in str(exc_info.value)

    def test_invalid_config_exits_with_the_full_report(self, write_config):
        """load_config is the single enforcement point: no code path can bypass validation."""
        path = write_config({"min_timeout": 5, "dns_server": "nope"})
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        message = str(exc_info.value)
        assert "min_timeout" in message
        assert "dns_server" in message, "the report must list every problem, not just the first"


class TestNetworkEntryValidation:
    """Tests for NetworkEntry validation."""

    def test_valid_network_entry(self):
        """Test creating a valid NetworkEntry."""
        entry = NetworkEntry(
            interface='wlan0',
            display_name='test-device',
            capabilities={'2.4ghz': True, '5ghz': False},
        )
        assert entry.interface == 'wlan0'
        assert entry.device_id == 'wlan0'
        assert entry.display_name == 'test-device'

    def test_network_entry_with_display_name(self):
        """Test creating a NetworkEntry with display_name."""
        entry = NetworkEntry(
            interface='wlan0',
            display_name='bench-antenna-1',
            capabilities={'2.4ghz': True, '5ghz': True},
        )
        assert entry.device_id == 'wlan0'
        assert entry.display_name == 'bench-antenna-1'

    def test_network_entry_missing_display_name(self):
        """Test that missing display_name raises validation error."""
        with pytest.raises(ValueError):
            NetworkEntry(interface='wlan0', capabilities={'2.4ghz': True, '5ghz': True})

    def test_network_entry_missing_capabilities(self):
        """capabilities is required: there is no implicit default."""
        with pytest.raises(ValueError):
            NetworkEntry(interface='wlan0', display_name='test')

    def test_device_id_equals_interface(self):
        """Test that device_id is always equal to interface name."""
        entry = NetworkEntry(
            interface='wlx782051245264',
            display_name='antenna',
            capabilities={'2.4ghz': True, '5ghz': False},
        )
        assert entry.device_id == 'wlx782051245264'

    def test_each_interface_has_unique_device_id(self):
        """Test that each configured interface has unique device_id."""
        cfg = load_config()
        device_ids = [n.device_id for n in cfg.networks]
        assert len(device_ids) == len(set(device_ids))


class TestCapabilityModel:
    """Tests for the capability registry and the model helpers built on it."""

    def test_capability_ids_match_the_band_vocabulary(self):
        """The ids are deliberately the same strings NetworkCreateRequest accepts as `band`."""
        assert Capability.ids() == ['2.4ghz', '5ghz']

    def test_registry_covers_every_capability(self):
        assert set(CAPABILITY_REGISTRY) == set(Capability)

    def test_registry_entries_carry_a_label_and_kind(self):
        for cap, definition in CAPABILITY_REGISTRY.items():
            assert definition.id is cap
            assert definition.label
            assert definition.kind

    def test_v1_guard_rejects_a_non_boolean_capability(self):
        """The import-time guard must fire for anything the v1 algorithm cannot handle."""
        from wilab.config import CapabilityDef, CapabilityKind

        hypothetical = CapabilityDef(
            id=Capability.BAND_5GHZ,
            label="Max clients",
            kind=CapabilityKind.POLICY,
            type=CapabilityType.INTEGER,
        )
        unsupported = [
            d for d in [hypothetical]
            if d.type is not CapabilityType.BOOLEAN or not d.matchable
        ]
        assert unsupported, "a non-boolean capability must be flagged as unsupported in v1"

    def test_capability_set_returns_only_enabled(self):
        entry = NetworkEntry(
            interface='wlan0',
            display_name='a',
            capabilities={'2.4ghz': True, '5ghz': False},
        )
        assert entry.capability_set == {Capability.BAND_24GHZ}

    def test_capability_keys_are_canonicalised_by_the_model(self):
        entry = NetworkEntry(
            interface='wlan0',
            display_name='a',
            capabilities={' 2.4GHz ': True, '5GHZ': True},
        )
        assert set(entry.capabilities) == {'2.4ghz', '5ghz'}
        assert entry.capability_set == {Capability.BAND_24GHZ, Capability.BAND_5GHZ}

    def test_capability_values_are_strictly_boolean(self):
        """A YAML string must not be coerced to True behind the administrator's back."""
        with pytest.raises(ValueError):
            NetworkEntry(
                interface='wlan0',
                display_name='a',
                capabilities={'2.4ghz': 'yes', '5ghz': False},
            )

    def test_normalise_capability_id_is_shared_and_idempotent(self):
        for raw in [' 5GHz ', '5ghz', '5GHZ']:
            assert normalise_capability_id(raw) == '5ghz'
        assert normalise_capability_id(normalise_capability_id(' 2.4GHz ')) == '2.4ghz'


class TestCapabilitiesForHelper:
    """AppConfig.capabilities_for() is what the API routes serve."""

    def test_returns_sorted_enabled_ids(self):
        caps = load_config().capabilities_for('wls16')
        assert caps == sorted(caps)
        assert caps == ['2.4ghz', '5ghz']

    def test_disabled_capabilities_are_not_returned(self):
        cfg = load_config(os.path.join(os.getcwd(), 'config.example.yaml'))
        # bench-antenna-1 declares "5ghz": false
        assert cfg.capabilities_for('wlxbc071dc527d6') == ['2.4ghz']

    def test_unknown_device_returns_empty_list(self):
        assert load_config().capabilities_for('does-not-exist') == []


class TestSemanticRulesMovedOutOfPydantic:
    """The former field_validators now live in the rule set, with one reporting path.

    These guard against someone reintroducing a second, terser error channel.
    """

    def test_model_no_longer_carries_the_moved_validators(self):
        decorators = getattr(AppConfig, '__pydantic_decorators__', None)
        assert decorators is not None
        names = set(decorators.field_validators)
        for moved in (
            'validate_min_timeout',
            'validate_upstream_interface',
            'validate_dhcp_base_network',
            'validate_network_count',
        ):
            assert moved not in names, f"{moved} must live in the rule set, not in the model"

    def test_min_timeout_below_10_rejected(self, write_config):
        """min_timeout < 10 is rejected at config validation."""
        with pytest.raises(SystemExit, match="min_timeout"):
            load_config(write_config({"min_timeout": 5}))

    def test_min_timeout_10_accepted(self, write_config):
        """min_timeout = 10 is accepted (boundary)."""
        cfg = load_config(write_config({"min_timeout": 10}))
        assert cfg.min_timeout == 10


class TestConfigIntegration:
    """Integration tests for config with NetworkManager."""

    def test_dhcp_base_network_valid_cidr(self):
        """Test that dhcp_base_network is valid CIDR."""
        cfg = load_config()
        assert '/' in cfg.dhcp_base_network
        from ipaddress import IPv4Network
        IPv4Network(cfg.dhcp_base_network, strict=False)  # Should not raise


class TestAllowUnlimitedReservationConfig:
    """Tests for allow_unlimited_reservation config field."""

    def test_default_is_false(self):
        """allow_unlimited_reservation defaults to False."""
        cfg = load_config()
        assert cfg.allow_unlimited_reservation is False
