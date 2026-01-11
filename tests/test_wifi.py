import pytest
import time
from wilab.config import load_config, NetworkEntry
from wilab.wifi.manager import NetworkManager
from wilab.models import NetworkCreateRequest


class TestNetworkManagerInit:
    """Tests for NetworkManager initialization."""
    
    def test_network_manager_init(self):
        """Test NetworkManager initialization."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        assert mgr.config == cfg
        assert mgr.active == {}
    
    def test_network_manager_has_dhcp_server(self):
        """Test that NetworkManager has DHCP server instance."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        assert hasattr(mgr, 'dhcp_server')
        assert mgr.dhcp_server is not None


class TestSubnetResolution:
    """Tests for subnet resolution (explicit vs calculated)."""
    
    def test_get_subnet_explicit(self):
        """First subnet matches dhcp_base_network /24."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        subnet = mgr._get_subnet('ap-01')
        assert subnet == '192.168.120.0/24'
    
    def test_get_subnet_unknown_net_id(self):
        """Test that unknown net_id raises ValueError."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        with pytest.raises(ValueError, match="Unknown net_id"):
            mgr._get_subnet('unknown-network')
    
    def test_get_subnet_fallback_calculation(self):
        """Test sequential allocation increments third octet."""
        cfg = load_config()
        cfg.networks.append(NetworkEntry(net_id='ap-02', interface='wlan1'))
        mgr = NetworkManager(cfg)
        first = mgr._get_subnet('ap-01')
        second = mgr._get_subnet('ap-02')
        assert first == '192.168.120.0/24'
        assert second == '192.168.121.0/24'


class TestNetworkLifecycle:
    """Tests for network start/stop lifecycle."""
    
    def test_get_status_inactive_network(self):
        """Test getting status of inactive network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        status = mgr.get_status('ap-01')
        assert status is not None
        assert status.active is False
        assert status.net_id == 'ap-01'
    
    def test_get_status_unknown_network(self):
        """Test getting status of unknown network returns None."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        status = mgr.get_status('unknown-network')
        assert status is None
    
    def test_start_network_basic(self, monkeypatch):
        """Test starting a network (with mocked DHCP)."""
        # Mock the DHCP server start method to avoid system calls
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {
                'gateway': '192.168.120.1',
                'dhcp_range': '192.168.120.10,192.168.120.250'
            }
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        status = mgr.start_network('ap-01', req)
        assert status.active is True
        assert status.ssid == 'TestAP'
        assert status.channel == 6
        assert status.encryption == 'wpa2'
        assert status.band == '2.4ghz'
        assert status.subnet == '192.168.120.0/24'
        assert status.internet_enabled is True  # Default from config
    
    def test_start_network_with_internet_disabled(self, monkeypatch):
        """Test starting network with internet disabled."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=4,
            internet_enabled=False
        )
        
        status = mgr.start_network('ap-01', req)
        assert status.internet_enabled is False
    
    def test_start_network_with_custom_timeout(self, monkeypatch):
        """Test starting network with custom timeout."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
            timeout=7200  # 2 hours
        )
        
        now = time.time()
        status = mgr.start_network('ap-01', req)
        assert status.expires_at is not None
        # expires_at should be a string in format yyyy-mm-dd HH:MM:SS
        assert isinstance(status.expires_at, str)
        assert len(status.expires_at) == 19  # "2026-01-11 12:34:56" length
        # Check expires_in is within expected range (2 hours = 7200 seconds, allow 100s margin)
        assert status.expires_in > 7100
        assert status.expires_in < 7300
    
    def test_start_network_timeout_bounds(self, monkeypatch):
        """Test that custom timeout is bounded by min/max."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        # Test minimum timeout enforcement
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
            timeout=10  # Less than min_timeout (60)
        )
        
        now = time.time()
        status = mgr.start_network('ap-01', req)
        # Should be bounded to min_timeout (60 seconds)
        assert status.expires_in > 50
        assert status.expires_in < 100
    
    def test_stop_network(self, monkeypatch):
        """Test stopping a network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_dhcp_stop(*args, **kwargs):
            pass
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.dhcp_server, 'stop', mock_dhcp_stop)
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        status = mgr.start_network('ap-01', req)
        assert status.active is True
        assert 'ap-01' in mgr.active
        
        mgr.stop_network('ap-01')
        assert 'ap-01' not in mgr.active
    
    def test_stop_network_nonexistent(self, monkeypatch):
        """Test stopping a network that doesn't exist (should not raise)."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        mgr.stop_network('nonexistent')  # Should not raise
    
    def test_auto_expire_network(self, monkeypatch):
        """Test that network auto-expires after timeout."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_dhcp_stop(*args, **kwargs):
            pass
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.dhcp_server, 'stop', mock_dhcp_stop)
        
        # Test expiration logic by directly manipulating expires_at
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
            timeout=3600  # Normal timeout
        )
        
        status = mgr.start_network('ap-01', req)
        assert status.active is True
        
        # Manually set internal timestamp to past to simulate expiration
        mgr.active['ap-01']._expires_at_timestamp = time.time() - 1  # Expired 1 second ago
        
        # Check status should return inactive due to expiration
        expired_status = mgr.get_status('ap-01')
        assert expired_status.active is False


class TestInternetControl:
    """Tests for internet enable/disable."""
    
    def test_enable_internet(self, monkeypatch):
        """Test enabling internet for a network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_nat_enable(interface, net_id):
            pass  # Mock NAT enable - now requires net_id parameter
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', mock_nat_enable)
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
            internet_enabled=False
        )
        
        mgr.start_network('ap-01', req)
        status = mgr.enable_internet('ap-01')
        assert status.internet_enabled is True
    
    def test_disable_internet(self, monkeypatch):
        """Test disabling internet for a network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_nat_enable(interface, net_id):
            pass  # Mock NAT enable - now requires net_id parameter
        
        def mock_nat_disable(interface, net_id):
            pass  # Mock NAT disable - now requires net_id parameter
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', mock_nat_enable)
        monkeypatch.setattr(mgr.nat_manager, 'disable_nat', mock_nat_disable)
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
            internet_enabled=True
        )
        
        mgr.start_network('ap-01', req)
        status = mgr.disable_internet('ap-01')
        assert status.internet_enabled is False
    
    def test_internet_control_inactive_network(self):
        """Test that internet control on inactive network raises error."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        with pytest.raises(ValueError, match="Unknown or inactive"):
            mgr.enable_internet('ap-01')


class TestClientList:
    """Tests for listing connected clients."""
    
    def test_list_clients_empty(self, monkeypatch):
        """Test listing clients returns empty list for now."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        mgr.start_network('ap-01', req)
        clients = mgr.list_clients('ap-01')
        assert clients == []
    
    def test_list_clients_with_leases(self, monkeypatch, tmp_path):
        """Test listing clients from dnsmasq lease file."""
        import tempfile
        
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        # Create a fake lease file
        lease_file = tmp_path / "leases-ap-01.db"
        lease_file.write_text(
            "1234567890 aa:bb:cc:dd:ee:ff 192.168.10.10 client1 *\n"
            "1234567891 11:22:33:44:55:66 192.168.10.11 client2 *\n"
        )
        
        def mock_dhcp_start(net_id, interface, subnet, dns_server='192.168.10.21'):
            dhcp_info = {
                'gateway': '192.168.10.1',
                'lease_file': str(lease_file)
            }
            # Store in _instances so get_subnet_info() works
            mgr.dhcp_server._instances[net_id] = dhcp_info
            return dhcp_info
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        mgr.start_network('ap-01', req)
        clients = mgr.list_clients('ap-01')
        
        assert len(clients) == 2
        assert clients[0].mac == 'aa:bb:cc:dd:ee:ff'
        assert clients[0].ip == '192.168.10.10'
        assert clients[1].mac == '11:22:33:44:55:66'
        assert clients[1].ip == '192.168.10.11'


class TestNetworkSummary:
    """Tests for network summary information."""

    def test_summary_inactive_network(self):
        """Summary for known but inactive network returns defaults."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        summary = mgr.get_summary('ap-01')
        assert summary is not None
        assert summary['active'] is False
        assert summary['dhcp'] == {}
        assert summary['clients_connected'] == 0
        assert summary['clients'] == []

    def test_summary_active_network(self, monkeypatch):
        """Summary for active network includes DHCP info and clients count."""
        cfg = load_config()
        mgr = NetworkManager(cfg)

        def mock_dhcp_start(net_id, interface, subnet, dns_server='192.168.10.21'):
            info = {
                'interface': interface,
                'subnet': subnet,
                'gateway': '192.168.10.1',
                'dhcp_range': '192.168.10.10,192.168.10.250',
            }
            mgr.dhcp_server._instances[net_id] = info
            return info

        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', lambda *_args, **_kwargs: None)

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )

        mgr.start_network('ap-01', req)
        summary = mgr.get_summary('ap-01')
        assert summary is not None
        assert summary['active'] is True
        assert summary['dhcp']['gateway'] == '192.168.10.1'
        assert summary['clients_connected'] == 0
        assert summary['clients'] == []


class TestShutdownAll:
    """Tests for shutting down all networks."""
    
    def test_shutdown_all_networks(self, monkeypatch):
        """Test shutting down all active networks."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_dhcp_stop(*args, **kwargs):
            pass
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(mgr.dhcp_server, 'stop', mock_dhcp_stop)
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        mgr.start_network('ap-01', req)
        assert len(mgr.active) == 1
        
        mgr.shutdown_all()
        assert len(mgr.active) == 0


class TestTxPower:
    """Tests for TX power level handling."""

    def test_tx_power_levels_default_on_start(self, monkeypatch):
        cfg = load_config()
        mgr = NetworkManager(cfg)

        # Mock subsystems
        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda **kwargs: {'gateway': '192.168.120.1'})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda **kwargs: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(mgr.isolation_manager, 'add_network', lambda *a, **k: None)

        calls = []
        def fake_set_tx_power(interface, level, channel, verify_change=False):
            calls.append((interface, level, channel))
            return {
                'interface': interface,
                'channel': channel,
                'frequency_mhz': 2437,
                'max_dbm': 20.0,
                'levels_dbm': {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0},
                'current_level': level,
                'current_dbm': 20.0,
                'reported_dbm': 20.0,
            }

        monkeypatch.setattr(mgr, '_set_tx_power', fake_set_tx_power)

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=3  # Now required
        )

        status = mgr.start_network('ap-01', req)
        assert status.tx_power_level == 3
        assert calls[-1] == ('wlx782051245264', 3, 6)

    def test_set_tx_power_level(self, monkeypatch):
        cfg = load_config()
        mgr = NetworkManager(cfg)

        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda **kwargs: {'gateway': '192.168.120.1'})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda **kwargs: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(mgr.isolation_manager, 'add_network', lambda *a, **k: None)

        def fake_set_tx_power(interface, level, channel, verify_change=False):
            result = {
                'interface': interface,
                'channel': channel,
                'frequency_mhz': 2437,
                'max_dbm': 20.0,
                'levels_dbm': {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0},
                'current_level': level,
                'current_dbm': float(level * 5),
                'reported_dbm': float(level * 5) if not verify_change else None,
            }
            if verify_change:
                result['warning'] = None
            return result

        monkeypatch.setattr(mgr, '_set_tx_power', fake_set_tx_power)

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=4
        )

        mgr.start_network('ap-01', req)
        info = mgr.set_tx_power_level('ap-01', 2)
        assert info['current_level'] == 2
        assert mgr.active['ap-01'].tx_power_level == 2

        # GET should reflect the last level
        info2 = mgr.get_tx_power_info('ap-01')
        assert info2['current_level'] == 2
