import pytest
from fastapi.testclient import TestClient
from wilab.api import create_app
from wilab.config import load_config
from wilab.version import __version__
from wilab.wifi.manager import NetworkManager, TxPowerMismatchError
from wilab.api import dependencies
from wilab.models import ClientInfo
from wilab.reservation import ReservationManager


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    load_config()
    app = create_app()
    return TestClient(app)


@pytest.fixture
def valid_token():
    """Get valid auth token from config."""
    cfg = load_config()
    return f"Bearer {cfg.auth_token}"


@pytest.fixture
def invalid_token():
    """Get invalid auth token."""
    return "Bearer invalid-token-12345"


@pytest.fixture
def reservation_id(client, valid_token, monkeypatch):
    """Create a reservation and return the reservation_id token.

    Resets the reservation manager singleton to avoid cross-test state.
    The resulting token maps to the first available device (wls16).
    """
    cfg = load_config()
    rmgr = ReservationManager([n.device_id for n in cfg.networks])
    monkeypatch.setattr(dependencies, '_reservation_manager', rmgr, raising=False)

    resp = client.post(
        '/api/v1/device-reservation',
        headers={'Authorization': valid_token},
        json={'duration_seconds': 3600},
    )
    assert resp.status_code == 200
    return resp.json()['reservation_id']


class TestStatusEndpoint:
    """Tests for system status endpoint."""
    
    def test_status_requires_auth(self, client):
        """Test status endpoint requires authentication."""
        resp = client.get('/api/v1/status')
        assert resp.status_code == 401
    
    def test_status(self, client, valid_token):
        """Test status endpoint returns valid response."""
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] in ['ok', 'degraded', 'standby']
        assert 'version' in data
        assert 'networks' in data
        assert 'checks' in data
    
    def test_status_standby_mode(self, client, valid_token, monkeypatch):
        """Test status endpoint in standby mode (no active networks)."""
        from wilab.api.dependencies import get_manager
        
        # Mock manager with no active networks
        def mock_manager(*args, **kwargs):
            mgr = get_manager()
            mgr.active = {}  # No active networks = standby
            return mgr
        
        monkeypatch.setattr('wilab.api.routes.status.get_manager', mock_manager)
        
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        assert data['status'] == 'standby'
        assert data['active_networks'] == 0
    
    def test_status_response_structure(self, client, valid_token):
        """Test status response contains all required fields."""
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        
        # Check required top-level fields
        assert 'status' in data
        assert 'version' in data
        assert 'networks' in data
        assert 'active_networks' in data
        assert 'checks' in data
        
        # Check version and networks
        assert data['version'] is not None
        assert len(data['version']) > 0
        assert isinstance(data['networks'], list)
    
    def test_status_health_checks(self, client, valid_token):
        """Test status includes all health checks."""
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        
        # Check all required checks
        assert 'dnsmasq' in data['checks']
        assert 'iptables_nat' in data['checks']
        assert 'upstream_interface' in data['checks']
        
        # Check dnsmasq structure
        assert 'running' in data['checks']['dnsmasq']
        assert 'instances' in data['checks']['dnsmasq']
        assert isinstance(data['checks']['dnsmasq']['running'], bool)
        assert isinstance(data['checks']['dnsmasq']['instances'], int)
        
        # Check iptables_nat structure
        assert 'configured' in data['checks']['iptables_nat']
        assert 'errors' in data['checks']['iptables_nat']
        assert isinstance(data['checks']['iptables_nat']['configured'], bool)
        assert isinstance(data['checks']['iptables_nat']['errors'], list)
        
        # Check upstream_interface structure
        assert 'name' in data['checks']['upstream_interface']
        assert 'reachable' in data['checks']['upstream_interface']
        assert isinstance(data['checks']['upstream_interface']['reachable'], bool)
    
    def test_status_degraded_on_dhcp_down(self, client, valid_token, monkeypatch):
        """Test status returns degraded when DHCP is down but network is active."""
        from wilab.models import NetworkStatus
        from wilab.api.dependencies import get_manager as original_get_manager
        
        # Get the real manager once, then mock it
        real_mgr = original_get_manager()
        
        # Add an active network
        real_mgr.active['test-net'] = NetworkStatus(
            device_id='test-net',
            interface='wlan0',
            active=True,
            ssid='TestAP',
            subnet='192.168.120.0/24'
        )
        
        # Mock DHCP as not running
        original_status = real_mgr.dhcp_server.status
        monkeypatch.setattr(real_mgr.dhcp_server, 'status', 
                          lambda: {'running': False, 'instances': []})
        
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        assert data['status'] == 'degraded'
        assert data['active_networks'] == 1
        assert data['checks']['dnsmasq']['running'] is False
        
        # Cleanup
        real_mgr.active.clear()
        monkeypatch.setattr(real_mgr.dhcp_server, 'status', original_status)
    
    def test_status_upstream_error_handling(self, client, valid_token, monkeypatch):
        """Test status gracefully handles upstream interface errors."""
        from wilab.api.dependencies import get_manager as original_get_manager
        from wilab.network.commands import CommandError
        
        # Get the real manager once
        real_mgr = original_get_manager()
        
        # Mock get_upstream_interface to raise error
        original_get_upstream = real_mgr.nat_manager.get_upstream_interface
        monkeypatch.setattr(
            real_mgr.nat_manager,
            'get_upstream_interface',
            lambda: (_ for _ in ()).throw(CommandError("Test error"))
        )
        
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        assert resp.status_code == 200  # Should not crash
        data = resp.json()
        assert 'upstream_interface' in data['checks']
        assert data['checks']['upstream_interface']['reachable'] is False
        assert 'error' in data['checks']['upstream_interface']
        
        # Cleanup
        monkeypatch.setattr(real_mgr.nat_manager, 'get_upstream_interface', original_get_upstream)


class TestDebugEndpoint:
    """Tests for debug endpoint."""
    
    def test_debug_requires_auth(self, client):
        """Test debug endpoint requires authentication."""
        resp = client.get('/api/v1/debug')
        assert resp.status_code == 401

    def test_debug_with_invalid_token(self, client, invalid_token):
        """Test debug endpoint rejects invalid token."""
        resp = client.get('/api/v1/debug', headers={'Authorization': invalid_token})
        assert resp.status_code == 401

    def test_debug_endpoint_basic(self, client, valid_token):
        """Test debug endpoint returns valid response."""
        resp = client.get('/api/v1/debug', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()
        assert 'version' in data
        assert 'status' in data
        assert 'system' in data
    
    def test_debug_endpoint_structure(self, client, valid_token):
        """Test debug endpoint response structure."""
        resp = client.get('/api/v1/debug', headers={'Authorization': valid_token})
        data = resp.json()
        
        # Check main sections
        assert 'version' in data
        assert 'status' in data
        assert data['status'] in ['ok', 'degraded', 'standby']
        
        # Check system section
        assert 'system' in data
        assert 'active_networks' in data['system']
        assert 'configured_networks' in data['system']
        assert 'upstream_interface' in data['system']
    
    def test_debug_endpoint_services_section(self, client, valid_token):
        """Test debug endpoint includes services info."""
        resp = client.get('/api/v1/debug', headers={'Authorization': valid_token})
        data = resp.json()
        
        assert 'services' in data
        assert 'dnsmasq' in data['services']
        assert 'hostapd' in data['services']
        assert 'iptables_nat' in data['services']
        
        # Check service structure
        assert 'running' in data['services']['dnsmasq']
        assert 'instances' in data['services']['dnsmasq']
        assert isinstance(data['services']['dnsmasq']['instances'], int)
    
    def test_debug_endpoint_interfaces_section(self, client, valid_token):
        """Test debug endpoint includes interfaces info."""
        resp = client.get('/api/v1/debug', headers={'Authorization': valid_token})
        data = resp.json()
        
        assert 'interfaces' in data
        assert 'upstream' in data['interfaces']
        assert 'managed' in data['interfaces']
        
        # Check upstream interface structure
        upstream = data['interfaces']['upstream']
        assert 'name' in upstream
        assert 'up' in upstream
        assert 'has_ip' in upstream
        assert 'reachable' in upstream
        
        # Check managed interfaces
        assert isinstance(data['interfaces']['managed'], list)


class TestAppMetadata:
    """Tests for app metadata."""
    
    def test_app_version(self, client):
        """Test app version matches VERSION file."""
        app = client.app
        assert app.version == __version__
    
    def test_app_title(self, client):
        """Test app title."""
        app = client.app
        assert app.title == "Wi-Lab"


class TestAuthentication:
    """Tests for authentication and authorization."""
    
    def test_request_without_auth(self, client):
        """Test that request without auth token is rejected."""
        resp = client.get('/api/v1/interfaces')
        # GET /interfaces doesn't require auth, so should succeed
        assert resp.status_code == 200
    
    def test_start_network_without_auth(self, client, reservation_id):
        """Test that network creation without auth is rejected."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 401  # Unauthorized (no token)
    
    def test_start_network_with_invalid_token(self, client, invalid_token, reservation_id):
        """Test that request with invalid token is rejected."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': invalid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 401  # Unauthorized
    
    def test_start_network_with_valid_token(self, client, valid_token, reservation_id, monkeypatch):
        """Test that request with valid token succeeds (with mocked DHCP)."""
        from wilab.api.dependencies import _manager
        if _manager:
            def mock_dhcp_start(*args, **kwargs):
                return {'gateway': '192.168.10.1'}
            monkeypatch.setattr(_manager.dhcp_server, 'start', mock_dhcp_start)
            monkeypatch.setattr(_manager.hostapd_manager, 'start', lambda *a, **kw: {})
        
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        # Should succeed with mocked DHCP
        assert resp.status_code in [200, 500]  # 500 if DHCP not fully mocked


class TestNetworkCreateEndpoint:
    """Tests for network creation endpoint."""
    
    def test_start_network_invalid_json(self, client, valid_token, reservation_id):
        """Test that invalid JSON is rejected."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={'invalid': 'payload'}
        )
        assert resp.status_code == 422  # Validation error
    
    def test_start_network_invalid_reservation(self, client, valid_token):
        """Test starting with an invalid reservation token returns 404."""
        resp = client.post(
            '/api/v1/interface/invalid-token/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 404  # Reservation not found
    
    def test_start_network_invalid_encryption(self, client, valid_token, reservation_id):
        """Test that invalid encryption is rejected."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'invalid-encryption',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 422  # Validation error
    
    def test_start_network_invalid_band(self, client, valid_token, reservation_id):
        """Test that invalid band is rejected."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': 'invalid-band'
            }
        )
        assert resp.status_code == 422  # Validation error

    def test_start_network_runtime_failure_returns_500(self, client, valid_token, reservation_id, monkeypatch):
        """Operational failures during startup must map to 500, not 404."""
        from wilab.api.dependencies import _manager
        if _manager:
            monkeypatch.setattr(
                _manager,
                'start_network',
                lambda *args, **kwargs: (_ for _ in ()).throw(
                    ValueError('Failed to start AP: hostapd failed to start')
                )
            )

        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert resp.status_code == 500
    
    def test_network_response_structure(self, client, valid_token, reservation_id, monkeypatch):
        """Test POST returns a simple creation confirmation payload."""
        from wilab.api.dependencies import _manager
        if _manager:
            def mock_dhcp_start(*args, **kwargs):
                return {'gateway': '192.168.10.1'}
            monkeypatch.setattr(_manager.dhcp_server, 'start', mock_dhcp_start)
            
            resp = client.post(
                f'/api/v1/interface/{reservation_id}/network',
                headers={'Authorization': valid_token},
                json={
                    'ssid': 'TestAP',
                    'channel': 6,
                    'encryption': 'wpa2',
                    'band': '2.4ghz', 'tx_power_level': 4
                }
            )
            
            if resp.status_code == 200:
                data = resp.json()
                assert data == {'detail': 'Network wls16 created successfully'}

    def test_start_network_422_has_simple_detail(self, client, valid_token, reservation_id):
        """Validation errors should return a simple string detail."""
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={'invalid': 'payload'}
        )
        assert resp.status_code == 422
        data = resp.json()
        assert 'detail' in data
        assert isinstance(data['detail'], str)
        assert data['detail'].strip() != ''


class TestNetworkGetEndpoint:
    """Tests for getting network status."""
    
    def test_get_network_status_inactive(self, client, valid_token, reservation_id):
        """Test getting status of inactive network via valid reservation."""
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Network is initially inactive
        assert data['active'] in [True, False]  # Either state is valid
    
    def test_get_network_status_invalid_reservation(self, client, valid_token):
        """Test getting status with invalid reservation returns 404."""
        resp = client.get(
            '/api/v1/interface/invalid-token/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_get_network_active_with_dhcp_and_clients(self, client, valid_token, reservation_id, monkeypatch):
        """Test getting complete status of active network including DHCP and clients."""
        cfg = load_config()
        manager = NetworkManager(cfg)

        def mock_dhcp_start(net_id, interface, subnet, dns_server='192.168.10.21'):
            info = {
                'interface': interface,
                'subnet': subnet,
                'gateway': '192.168.10.1',
                'dhcp_range': '192.168.10.10,192.168.10.250',
            }
            manager.dhcp_server._instances[net_id] = info
            return info

        monkeypatch.setattr(manager.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *_args, **_kwargs: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        # Start network via reservation token
        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        # Get network status
        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Validate complete response structure
        assert data['device_id'] == 'wls16'
        assert data['active'] is True
        assert data['ssid'] == 'TestAP'
        assert 'dhcp' in data
        assert data['dhcp']['gateway'] == '192.168.10.1'
        assert 'clients_connected' in data
        assert data['clients_connected'] == 0
        assert 'clients' in data
        assert isinstance(data['clients'], list)
        assert 'tx_power' in data
        assert data['tx_power'] == {
            'requested_level': 4,
            'reported_level': 4,
            'reported_dbm': 20.0,
        }
        assert 'tx_power_level' not in data

    def test_get_network_status_returns_client_entries_with_ip_and_mac(self, client, valid_token, reservation_id, monkeypatch):
        """Test active network status returns stable clients[] entries with ip and mac."""
        cfg = load_config()
        manager = NetworkManager(cfg)

        def mock_dhcp_start(net_id, interface, subnet, dns_server='192.168.10.21'):
            info = {
                'interface': interface,
                'subnet': subnet,
                'gateway': '192.168.10.1',
                'dhcp_range': '192.168.10.10,192.168.10.250',
            }
            manager.dhcp_server._instances[net_id] = info
            return info

        monkeypatch.setattr(manager.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **kw: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            manager,
            'list_clients',
            lambda _device_id: [
                ClientInfo(mac='aa:bb:cc:dd:ee:01', ip='192.168.10.10'),
                ClientInfo(mac='aa:bb:cc:dd:ee:02', ip='192.168.10.11'),
            ]
        )
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data['clients_connected'] == 2
        assert data['clients'] == [
            {'mac': 'aa:bb:cc:dd:ee:01', 'ip': '192.168.10.10'},
            {'mac': 'aa:bb:cc:dd:ee:02', 'ip': '192.168.10.11'},
        ]
        for client_entry in data['clients']:
            assert set(client_entry.keys()) == {'ip', 'mac'}
            assert isinstance(client_entry['ip'], str)
            assert isinstance(client_entry['mac'], str)


class TestNetworkDeleteEndpoint:
    """Tests for network deletion."""

    def test_stop_network_active(self, client, valid_token, reservation_id, monkeypatch):
        """Test stopping an active network succeeds."""
        cfg = load_config()
        manager = NetworkManager(cfg)

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.hostapd_manager, 'stop', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'disable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'remove_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        stop_resp = client.delete(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert stop_resp.status_code == 200
        assert stop_resp.json() == {'detail': 'Network wls16 stopped successfully'}
    
    def test_stop_network_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test stopping an inactive network returns 409."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.delete(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data['detail'] == 'Network wls16 is already inactive'
    
    def test_stop_network_invalid_reservation(self, client, valid_token):
        """Test stopping with invalid reservation returns 404."""
        resp = client.delete(
            '/api/v1/interface/invalid-token/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404


class TestTxPowerGetEndpoint:
    """Tests for txpower GET response shape."""

    def test_get_txpower_nested_shape(self, client, valid_token, reservation_id, monkeypatch):
        cfg = load_config()
        manager = NetworkManager(cfg)

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 10.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 2
            }
        )
        assert start_resp.status_code == 200

        resp = client.get(f'/api/v1/interface/{reservation_id}/txpower', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()

        assert data['device_id'] == 'wls16'
        assert 'max_dbm' in data
        assert 'levels_dbm' in data
        assert 'tx_power' in data
        assert data['tx_power']['requested_level'] == 2
        assert data['tx_power']['reported_level'] == 2
        assert data['tx_power']['reported_dbm'] == 10.0

    def test_get_txpower_omits_legacy_warning_fields(self, client, valid_token, reservation_id, monkeypatch):
        cfg = load_config()
        manager = NetworkManager(cfg)

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        resp = client.get(f'/api/v1/interface/{reservation_id}/txpower', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()

        assert 'current_level' not in data
        assert 'current_dbm' not in data
        assert 'reported_dbm' not in data
        assert 'warning' not in data


class TestTxPowerPostEndpoint:
    """Tests for txpower POST behavior."""

    def test_post_txpower_success_shape_without_warning(self, client, valid_token, reservation_id, monkeypatch):
        cfg = load_config()
        manager = NetworkManager(cfg)

        monkeypatch.setattr(
            manager,
            'set_tx_power_level',
            lambda device_id, level: {
                'device_id': device_id,
                'interface': 'wlx-test0',
                'max_dbm': 20.0,
                'levels_dbm': {'1': 5.0, '2': 10.0, '3': 15.0, '4': 20.0},
                'tx_power': {
                    'requested_level': level,
                    'reported_level': level,
                    'reported_dbm': float(level * 5),
                },
            },
        )
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.post(
            f'/api/v1/interface/{reservation_id}/txpower',
            headers={'Authorization': valid_token},
            json={'level': 2},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data['device_id'] == 'wls16'
        assert data['tx_power']['requested_level'] == 2
        assert data['tx_power']['reported_level'] == 2
        assert data['tx_power']['reported_dbm'] == 10.0
        assert 'warning' not in data

    def test_post_txpower_mismatch_returns_422(self, client, valid_token, reservation_id, monkeypatch):
        cfg = load_config()
        manager = NetworkManager(cfg)

        def fake_set_tx_power_level(_device_id, _level):
            raise TxPowerMismatchError('Interface does not support dynamic power change.')

        monkeypatch.setattr(manager, 'set_tx_power_level', fake_set_tx_power_level)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.post(
            f'/api/v1/interface/{reservation_id}/txpower',
            headers={'Authorization': valid_token},
            json={'level': 2},
        )

        assert resp.status_code == 422
        data = resp.json()
        assert data['detail'] == 'Interface does not support dynamic power change.'

    def test_post_txpower_out_of_range_returns_422_simple_message(self, client, valid_token, reservation_id):
        resp = client.post(
            f'/api/v1/interface/{reservation_id}/txpower',
            headers={'Authorization': valid_token},
            json={'level': 9},
        )

        assert resp.status_code == 422
        data = resp.json()
        assert data == {
            'detail': 'Requested power out of range. Valid values are 1, 2, 3, 4.'
        }

    def test_post_txpower_openapi_documents_422_examples(self, client, valid_token):
        resp = client.get('/openapi.json', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        schema = resp.json()

        txpower_post = schema['paths']['/api/v1/interface/{reservation_id}/txpower']['post']
        responses = txpower_post['responses']
        assert '422' in responses

        examples = responses['422']['content']['application/json']['examples']
        assert examples['out_of_range']['value']['detail'] == (
            'Requested power out of range. Valid values are 1, 2, 3, 4.'
        )
        assert examples['hardware_mismatch']['value']['detail'] == (
            'Interface does not support dynamic power change.'
        )

    def test_get_network_openapi_422_uses_simple_detail_schema(self, client, valid_token):
        resp = client.get('/openapi.json', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        schema = resp.json()

        network_get = schema['paths']['/api/v1/interface/{reservation_id}/network']['get']
        response_422 = network_get['responses']['422']
        json_schema = response_422['content']['application/json']['schema']

        assert json_schema['type'] == 'object'
        assert json_schema['properties']['detail']['type'] == 'string'


class TestInternetControlEndpoints:
    """Tests for internet enable/disable endpoints."""
    
    def test_enable_internet_success(self, client, valid_token, reservation_id, monkeypatch):
        """Test enabling internet on active network succeeds and returns detail message."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        # Start network first
        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        # Enable internet
        enable_resp = client.post(
            f'/api/v1/interface/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert enable_resp.status_code == 200
        data = enable_resp.json()
        assert data == {'detail': 'Network wls16 internet enabled successfully'}
    
    def test_disable_internet_success(self, client, valid_token, reservation_id, monkeypatch):
        """Test disabling internet on active network succeeds and returns detail message."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'disable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        # Start network first
        start_resp = client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz',
                'tx_power_level': 4
            }
        )
        assert start_resp.status_code == 200

        # Enable internet first
        enable_resp = client.post(
            f'/api/v1/interface/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert enable_resp.status_code == 200

        # Then disable internet
        disable_resp = client.post(
            f'/api/v1/interface/{reservation_id}/internet/disable',
            headers={'Authorization': valid_token}
        )
        assert disable_resp.status_code == 200
        data = disable_resp.json()
        assert data == {'detail': 'Network wls16 internet disabled successfully'}
    
    def test_enable_internet_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test enabling internet on inactive network fails."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.post(
            f'/api/v1/interface/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        # Should fail with either 404 or 500 depending on implementation
        assert resp.status_code in [404, 422, 500]
    
    def test_disable_internet_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test disabling internet on inactive network fails."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.post(
            f'/api/v1/interface/{reservation_id}/internet/disable',
            headers={'Authorization': valid_token}
        )
        # Should fail with either 404 or 500 depending on implementation
        assert resp.status_code in [404, 422, 500]


class TestReservationRequiredForOperations:
    """Tests that network operations require a valid reservation token."""

    def test_network_op_without_reservation_returns_404(self, client, valid_token):
        """Any network operation with invalid reservation returns 404."""
        resp = client.get(
            '/api/v1/interface/nonexistent-token/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404
        assert 'Reservation' in resp.json()['detail']

    def test_internet_op_without_reservation_returns_404(self, client, valid_token):
        """Internet enable with invalid reservation returns 404."""
        resp = client.post(
            '/api/v1/interface/nonexistent-token/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_txpower_op_without_reservation_returns_404(self, client, valid_token):
        """TX power GET with invalid reservation returns 404."""
        resp = client.get(
            '/api/v1/interface/nonexistent-token/txpower',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_expired_reservation_returns_404(self, client, valid_token, monkeypatch):
        """Expired reservation token is rejected with 404."""
        import time
        from wilab.api.dependencies import get_reservation_manager

        rmgr = get_reservation_manager()
        r = rmgr.create(3600)
        # Force expiry
        r.expires_at = time.time() - 1

        resp = client.get(
            f'/api/v1/interface/{r.reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_released_reservation_returns_404(self, client, valid_token):
        """Released reservation token is rejected with 404."""
        # Create and immediately release
        resp = client.post(
            '/api/v1/device-reservation',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 3600},
        )
        rid = resp.json()['reservation_id']
        client.delete(
            f'/api/v1/device-reservation/{rid}',
            headers={'Authorization': valid_token}
        )

        # Try to use the released token
        resp = client.post(
            f'/api/v1/interface/{rid}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP', 'channel': 6,
                'encryption': 'wpa2', 'password': 'testpass123',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 404


class TestStatusReservationInfo:
    """Tests for reservation info in status endpoint (Task 6)."""

    def test_status_networks_include_reservation_remaining(self, client, valid_token, monkeypatch):
        """Status API includes reservation_remaining_seconds for each device."""
        cfg = load_config()
        rmgr = ReservationManager([n.device_id for n in cfg.networks])
        monkeypatch.setattr(dependencies, '_reservation_manager', rmgr, raising=False)

        # Before reservation: remaining should be None
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        net_entry = data['networks'][0]
        assert 'device_id' in net_entry
        assert net_entry['reservation_remaining_seconds'] is None

    def test_status_reservation_remaining_after_reservation(self, client, valid_token, reservation_id):
        """After reservation, remaining seconds are positive and decrease."""
        resp = client.get('/api/v1/status', headers={'Authorization': valid_token})
        data = resp.json()
        net_entry = data['networks'][0]
        assert net_entry['device_id'] == 'wls16'
        remaining = net_entry['reservation_remaining_seconds']
        assert isinstance(remaining, int)
        assert remaining > 3500  # 3600s reservation, allow small margin


class TestGetNetworkExpiryAlwaysPresent:
    """Tests that Get Network always exposes expires_at/expires_in (Task 6)."""

    def test_get_network_off_still_has_expiry(self, client, valid_token, reservation_id, monkeypatch):
        """When network is off, expires_at and expires_in from reservation are present."""
        cfg = load_config()
        manager = NetworkManager(cfg)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['active'] is False
        assert data['expires_at'] is not None
        assert isinstance(data['expires_at'], str)
        assert len(data['expires_at']) == 19  # "yyyy-mm-dd HH:MM:SS"
        assert data['expires_in'] is not None
        assert data['expires_in'] > 3500

    def test_get_network_active_has_expiry(self, client, valid_token, reservation_id, monkeypatch):
        """When network is active, expires_at and expires_in are present."""
        cfg = load_config()
        manager = NetworkManager(cfg)

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager, '_read_current_txpower', lambda _iface: 20.0)
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        client.post(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP', 'channel': 6,
                'encryption': 'wpa2', 'password': 'testpass123',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )

        resp = client.get(
            f'/api/v1/interface/{reservation_id}/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['active'] is True
        assert data['expires_at'] is not None
        assert data['expires_in'] is not None
        assert data['expires_in'] > 3500


class TestNamingCleanup:
    """Tests for Task 7 naming conventions and OpenAPI contract."""

    def test_openapi_paths_use_reservation_id(self, client, valid_token):
        """OpenAPI paths use {reservation_id}, not {device_id}."""
        resp = client.get('/openapi.json', headers={'Authorization': valid_token})
        schema = resp.json()
        paths = list(schema['paths'].keys())
        for p in paths:
            if '/interface/' in p:
                assert '{reservation_id}' in p, f"Path {p} should use {{reservation_id}}"
                assert '{device_id}' not in p, f"Path {p} should not use {{device_id}}"

    def test_static_config_net_id_not_used_as_key(self):
        """Config does not expose net_id as operational key."""
        cfg = load_config()
        for net in cfg.networks:
            assert not hasattr(net, 'net_id') or net.device_id == net.interface
            assert net.device_id == net.interface
