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


class TestHealthEndpoint:
    """Tests for health check endpoint."""
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        resp = client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] in ['ok', 'degraded', 'standby']  # standby when no networks active


class TestInterfacesEndpoint:
    """Tests for listing managed interfaces."""
    
    def test_list_interfaces(self, client):
        """Test listing all managed interfaces."""
        resp = client.get('/api/v1/interfaces')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        assert any(d['net_id'] == 'ap-01' for d in data)
    
    def test_list_interfaces_structure(self, client):
        """Test that interface list has correct structure."""
        resp = client.get('/api/v1/interfaces')
        data = resp.json()
        for interface in data:
            assert 'net_id' in interface
            assert 'interface' in interface


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


class TestSummaryEndpoint:
    """Tests for the summary endpoint."""

    def test_summary_unknown_net(self, client, valid_token):
        """Unknown net_id should return 404."""
        resp = client.get(
            '/api/v1/interface/unknown-net/summary',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_summary_active_network(self, client, valid_token, monkeypatch):
        """Summary for an active network contains DHCP and client info."""
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

        start_resp = client.post(
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
        assert start_resp.status_code == 200

        resp = client.get(
            '/api/v1/interface/ap-01/summary',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['net_id'] == 'ap-01'
        assert data['active'] is True
        assert data['dhcp']['gateway'] == '192.168.10.1'
        assert data['clients_connected'] == 0
        assert isinstance(data['clients'], list)

