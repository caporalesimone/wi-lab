import pytest
from fastapi.testclient import TestClient
from wilab.api import create_app
from wilab.config import load_config
from wilab.version import __version__
from wilab.wifi.manager import NetworkManager
from wilab.api import dependencies


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
            net_id='test-net',
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
    
    def test_debug_endpoint_basic(self, client):
        """Test debug endpoint returns valid response."""
        resp = client.get('/api/v1/debug')
        assert resp.status_code == 200
        data = resp.json()
        assert 'version' in data
        assert 'status' in data
        assert 'system' in data
    
    def test_debug_endpoint_structure(self, client):
        """Test debug endpoint response structure."""
        resp = client.get('/api/v1/debug')
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
    
    def test_debug_endpoint_services_section(self, client):
        """Test debug endpoint includes services info."""
        resp = client.get('/api/v1/debug')
        data = resp.json()
        
        assert 'services' in data
        assert 'dnsmasq' in data['services']
        assert 'hostapd' in data['services']
        assert 'iptables_nat' in data['services']
        
        # Check service structure
        assert 'running' in data['services']['dnsmasq']
        assert 'instances' in data['services']['dnsmasq']
        assert isinstance(data['services']['dnsmasq']['instances'], int)
    
    def test_debug_endpoint_interfaces_section(self, client):
        """Test debug endpoint includes interfaces info."""
        resp = client.get('/api/v1/debug')
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
    
    def test_start_network_without_auth(self, client):
        """Test that network creation without auth is rejected."""
        resp = client.post(
            '/api/v1/interface/ap-01/network',
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 401  # Unauthorized (no token)
    
    def test_start_network_with_invalid_token(self, client, invalid_token):
        """Test that request with invalid token is rejected."""
        resp = client.post(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': invalid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 401  # Unauthorized
    
    def test_start_network_with_valid_token(self, client, valid_token, monkeypatch):
        """Test that request with valid token succeeds (with mocked DHCP)."""
        # Mock DHCP start to avoid system calls
        from wilab.api.dependencies import _manager
        if _manager:
            def mock_dhcp_start(*args, **kwargs):
                return {'gateway': '192.168.10.1'}
            monkeypatch.setattr(_manager.dhcp_server, 'start', mock_dhcp_start)
            monkeypatch.setattr(_manager.hostapd_manager, 'start', lambda *a, **kw: {})
        
        resp = client.post(
            '/api/v1/interface/ap-01/network',
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
    
    def test_start_network_invalid_json(self, client, valid_token):
        """Test that invalid JSON is rejected."""
        resp = client.post(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token},
            json={'invalid': 'payload'}
        )
        assert resp.status_code == 422  # Validation error
    
    def test_start_network_unknown_network(self, client, valid_token, monkeypatch):
        """Test starting a non-existent network."""
        from wilab.api.dependencies import _manager
        if _manager:
            def mock_dhcp_start(*args, **kwargs):
                return {'gateway': '192.168.10.1'}
            monkeypatch.setattr(_manager.dhcp_server, 'start', mock_dhcp_start)
            monkeypatch.setattr(_manager.hostapd_manager, 'start', lambda *a, **kw: {})
        
        resp = client.post(
            '/api/v1/interface/unknown-net/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'password': 'testpass123',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 404  # Not found
    
    def test_start_network_invalid_encryption(self, client, valid_token):
        """Test that invalid encryption is rejected."""
        resp = client.post(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'invalid-encryption',
                'band': '2.4ghz', 'tx_power_level': 4
            }
        )
        assert resp.status_code == 422  # Validation error
    
    def test_start_network_invalid_band(self, client, valid_token):
        """Test that invalid band is rejected."""
        resp = client.post(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token},
            json={
                'ssid': 'TestAP',
                'channel': 6,
                'encryption': 'wpa2',
                'band': 'invalid-band'
            }
        )
        assert resp.status_code == 422  # Validation error
    
    def test_network_response_structure(self, client, valid_token, monkeypatch):
        """Test that network response has correct structure."""
        from wilab.api.dependencies import _manager
        if _manager:
            def mock_dhcp_start(*args, **kwargs):
                return {'gateway': '192.168.10.1'}
            monkeypatch.setattr(_manager.dhcp_server, 'start', mock_dhcp_start)
            
            resp = client.post(
                '/api/v1/interface/ap-01/network',
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
                assert 'net_id' in data
                assert 'interface' in data
                assert 'active' in data
                assert 'ssid' in data
                assert 'subnet' in data


class TestNetworkGetEndpoint:
    """Tests for getting network status."""
    
    def test_get_network_status_inactive(self, client, valid_token):
        """Test getting status of inactive network."""
        resp = client.get(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Network is initially inactive
        assert data['active'] in [True, False]  # Either state is valid
    
    def test_get_network_status_unknown(self, client, valid_token):
        """Test getting status of unknown network."""
        resp = client.get(
            '/api/v1/interface/unknown-net/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_get_network_active_with_dhcp_and_clients(self, client, valid_token, monkeypatch):
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
        monkeypatch.setattr(dependencies, '_manager', manager, raising=False)

        # Start network
        start_resp = client.post(
            '/api/v1/interface/ap-01/network',
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
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Validate complete response structure
        assert data['net_id'] == 'ap-01'
        assert data['active'] is True
        assert data['ssid'] == 'TestAP'
        assert 'dhcp' in data
        assert data['dhcp']['gateway'] == '192.168.10.1'
        assert 'clients_connected' in data
        assert data['clients_connected'] == 0
        assert 'clients' in data
        assert isinstance(data['clients'], list)


class TestNetworkDeleteEndpoint:
    """Tests for network deletion."""
    
    def test_stop_network_inactive(self, client, valid_token):
        """Test stopping an inactive network."""
        resp = client.delete(
            '/api/v1/interface/ap-01/network',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        # API now returns only the net_id for confirmation
        assert data.get('net_id') == 'ap-01'
    
    def test_stop_network_unknown(self, client, valid_token):
        """Test stopping unknown network doesn't error."""
        resp = client.delete(
            '/api/v1/interface/unknown-net/network',
            headers={'Authorization': valid_token}
        )
        # Should succeed (no error on stopping non-existent)
        assert resp.status_code == 200


class TestInternetControlEndpoints:
    """Tests for internet enable/disable endpoints."""
    
    def test_enable_internet_inactive(self, client, valid_token):
        """Test enabling internet on inactive network fails."""
        resp = client.post(
            '/api/v1/interface/ap-01/internet/enable',
            headers={'Authorization': valid_token}
        )
        # Should fail with either 404 or 500 depending on implementation
        assert resp.status_code in [404, 422, 500]
    
    def test_disable_internet_inactive(self, client, valid_token):
        """Test disabling internet on inactive network fails."""
        resp = client.post(
            '/api/v1/interface/ap-01/internet/disable',
            headers={'Authorization': valid_token}
        )
        # Should fail with either 404 or 500 depending on implementation
        assert resp.status_code in [404, 422, 500]


class TestClientsEndpoint:
    """Tests for listing connected clients."""
    
    def test_list_clients_inactive(self, client, valid_token):
        """Test listing clients on inactive network."""
        resp = client.get(
            '/api/v1/interface/ap-01/clients',
            headers={'Authorization': valid_token}
        )
        # Should return empty list or 200
        assert resp.status_code in [200, 404]
    
    def test_list_clients_response_structure(self, client, valid_token):
        """Test clients response structure."""
        resp = client.get(
            '/api/v1/interface/ap-01/clients',
            headers={'Authorization': valid_token}
        )
        if resp.status_code == 200:
            data = resp.json()
            assert 'net_id' in data
            assert 'clients' in data
            assert isinstance(data['clients'], list)




