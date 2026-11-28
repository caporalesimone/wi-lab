from unittest.mock import Mock

import pytest
from conftest import active_network, configured_devices, create_network, network_body
from fastapi.testclient import TestClient

from wilab.api import create_app
from wilab.config import load_config
from wilab.models import ClientInfo
from wilab.reservation import ReservationManager
from wilab.version import __version__
from wilab.wifi.manager import NetworkManager


@pytest.fixture
def client(app):
    """Create a FastAPI test client."""
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
    rmgr = ReservationManager(configured_devices(cfg))
    monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

    resp = client.post(
        '/api/v2/reservations',
        headers={'Authorization': valid_token},
        json={'duration_seconds': 3600},
    )
    assert resp.status_code == 200
    return resp.json()['reservation_id']


class TestStatusEndpoint:
    """Tests for system status endpoint."""
    
    def test_status_requires_auth(self, client):
        """Test status endpoint requires authentication."""
        resp = client.get('/api/v2/status')
        assert resp.status_code == 401

    @pytest.mark.parametrize("token", ["invalid-token-12345", "", "é-not-ascii"])
    def test_a_wrong_token_is_refused(self, client, valid_token, token):
        # Bytes: the test client refuses a non-ASCII str header, a real client may send one.
        resp = client.get('/api/v2/status', headers={"Authorization": f"Bearer {token}".encode()})
        assert resp.status_code == 401

    def test_the_token_is_compared_in_constant_time(self, client, valid_token, monkeypatch):
        """BUG-8: hmac.compare_digest, never `!=`."""
        from wilab.api import auth
        calls = []
        real = auth.hmac.compare_digest
        monkeypatch.setattr(auth.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
        assert client.get('/api/v2/status', headers={"Authorization": valid_token}).status_code == 200
        assert calls
    
    def test_status(self, client, valid_token):
        """Test status endpoint returns valid response."""
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()
        total = len(client.get('/api/v2/antennas', headers={'Authorization': valid_token}).json()['antennas'])
        assert data['service'] == {'health': 'good', 'free_antennas': total, 'degraded_reasons': [], 'restart_required': None}
        assert list(data) == ['version', 'service', 'checked_at', 'check_interval_seconds', 'checks']
    
    def test_free_antennas_counts_what_a_reserve_would_get(self, client, valid_token, context):
        """A reserved antenna, even without a network, and a quarantined one are not free."""
        from wilab.devices import Device
        context.devices.add(Device(interface="wlx-second", display_name="Second"))
        headers = {'Authorization': valid_token}
        total = len(client.get('/api/v2/antennas', headers=headers).json()['antennas'])
        assert total >= 2
        rid = client.post('/api/v2/reservations', headers=headers, json={'duration_seconds': 600}).json()['reservation_id']
        data = client.get('/api/v2/status', headers=headers).json()
        assert data['service'] == {'health': 'good', 'free_antennas': total - 1, 'degraded_reasons': [], 'restart_required': None}
        listing = client.get('/api/v2/antennas', headers=headers).json()
        assert listing['free_antennas'] == total - 1
        assert not any(a['access_point_active'] for a in listing['antennas'])
        other = next(a['interface'] for a in listing['antennas'] if a['reservation'] is None)
        context.reservations._blocked[other] = False          # quarantined: degraded and not free
        data = client.get('/api/v2/status', headers=headers).json()
        assert data['service']['health'] == 'degraded' and data['service']['free_antennas'] == total - 2
        assert client.get('/api/v2/antennas', headers=headers).json()['free_antennas'] == total - 2
        assert [r['code'] for r in data['service']['degraded_reasons']] == ['antenna_quarantined']
        context.reservations._blocked.pop(other)
        assert client.delete(f'/api/v2/reservations/{rid}', headers=headers).status_code == 200
        assert client.get('/api/v2/status', headers=headers).json()['service'] == {'health': 'good', 'free_antennas': total, 'degraded_reasons': [], 'restart_required': None}

    def test_status_with_every_antenna_free(self, client, valid_token):
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        data = resp.json()
        listing = client.get('/api/v2/antennas', headers={'Authorization': valid_token}).json()
        assert data['service'] == {'health': 'good', 'free_antennas': len(listing['antennas']), 'degraded_reasons': [], 'restart_required': None}
        assert not any(a['access_point_active'] for a in listing['antennas'])
        assert data['checks']['commands'] == {'stuck': 0}

    def test_status_degraded_when_a_command_is_stuck_in_the_kernel(self, client, valid_token, monkeypatch):
        """STAB-1: a child that survived SIGKILL makes the service degraded, even in standby."""
        monkeypatch.setattr('wilab.api.routes.status.stuck_commands', lambda: 2)
        data = client.get('/api/v2/status', headers={'Authorization': valid_token}).json()
        assert data["service"]["health"] == "degraded"
        assert data['checks']['commands'] == {'stuck': 2}
    
    def test_status_response_structure(self, client, valid_token):
        """Test status response contains all required fields."""
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        data = resp.json()
        
        # Check required top-level fields
        assert 'service' in data and 'status' not in data
        assert 'version' in data
        assert 'antennas' not in data and 'reservation_policy' not in data
        assert 'active_networks' not in data and 'degraded_reasons' not in data and 'restart_required' not in data
        assert {'degraded_reasons', 'restart_required'} <= set(data['service'])
        assert {'checked_at', 'check_interval_seconds', 'checks'} <= set(data)
        assert data['version'] is not None
        assert len(data['version']) > 0
    
    def test_status_health_checks(self, client, valid_token):
        """Test status includes all health checks."""
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        
        # Check all required checks
        assert 'dnsmasq' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']
        assert 'iptables_nat' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']
        assert 'upstream_interface' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']
        
        # Check dnsmasq structure
        assert 'running' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['dnsmasq']
        assert 'instances' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['dnsmasq']
        assert isinstance(client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['dnsmasq']['running'], bool)
        assert isinstance(client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['dnsmasq']['instances'], int)
        
        # Check iptables_nat structure
        assert 'configured' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['iptables_nat']
        assert 'errors' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['iptables_nat']
        assert isinstance(client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['iptables_nat']['configured'], bool)
        assert isinstance(client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['iptables_nat']['errors'], list)
        
        # Check upstream_interface structure
        assert 'name' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['upstream_interface']
        upstream = client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['upstream_interface']
        assert {'operstate', 'mac', 'mtu', 'ipv4', 'ipv6', 'gateway'} <= set(upstream)
        assert 'reachable' not in upstream and 'up' not in upstream
    
    def test_status_degraded_on_dhcp_down(self, client, valid_token, monkeypatch):
        """Test status returns degraded when DHCP is down but network is active."""
        # Get the real manager once, then mock it
        real_mgr = client.app.state.context.manager
        
        # Add an active network
        real_mgr.active['test-net'] = active_network(
            interface='wlan0', ssid='TestAP',
            subnet='192.168.120.0/24'
        )
        
        # hostapd is alive, DHCP is not: the only reason for degraded
        monkeypatch.setattr(real_mgr.hostapd_manager, 'is_running', lambda _device: True)
        monkeypatch.setattr(real_mgr.dhcp_server, 'is_running', lambda _device: False)
        
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        data = resp.json()
        assert data["service"]["health"] == "degraded"
        assert [reason['code'] for reason in data["service"]["degraded_reasons"]] == ['dnsmasq_not_running']
        assert client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['dnsmasq']['running'] is False
    
    def test_status_upstream_error_handling(self, client, valid_token, monkeypatch):
        """Test status gracefully handles upstream interface errors."""
        from wilab.network.commands import CommandError
        
        # Get the real manager once
        real_mgr = client.app.state.context.manager
        
        # Mock get_upstream_interface to raise error
        monkeypatch.setattr(
            real_mgr.nat_manager,
            'get_upstream_interface',
            lambda: (_ for _ in ()).throw(CommandError("Test error"))
        )
        
        resp = client.get('/api/v2/status', headers={'Authorization': valid_token})
        assert resp.status_code == 200  # Should not crash
        assert resp.json()["service"]["health"] in ("good", "degraded")
        assert 'upstream_interface' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']
        assert 'error' in client.get('/api/v2/status', headers={'Authorization': valid_token}).json()['checks']['upstream_interface']


class TestDebugRemoved:
    def test_debug_is_gone(self, client, valid_token):
        """API-1: /debug duplicated /monitoring and exposed every reservation ID (SEC-2)."""
        client.app.state.context.config.protected_commands_password = "qwerty-test"
        resp = client.get('/api/v2/debug', headers={'Authorization': valid_token, 'X-Confirm-Password': 'qwerty-test'})
        assert resp.status_code == 404
        assert "/api/v2/debug" not in client.get("/openapi.json").json()["paths"]


class TestMaintenanceRule:
    def test_every_maintenance_endpoint_requires_token_and_confirm_password(self, client, valid_token):
        """Rule: anything listed under Maintenance needs X-Confirm-Password, like release-all."""
        client.app.state.context.config.protected_commands_password = "qwerty-test"
        spec = client.get("/openapi.json").json()
        operations = [
            (method, path) for path, item in spec["paths"].items()
            for method, op in item.items() if "Maintenance" in op.get("tags", [])
        ]
        assert set(operations) >= {("delete", "/api/v2/reservations/all")}
        for method, path in operations:
            assert client.request(method, path).status_code == 401, path
            for headers in ({}, {"X-Confirm-Password": "wrong"}):
                resp = client.request(method, path, headers={"Authorization": valid_token, **headers})
                assert resp.status_code == 403, path


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
        """A missing token returns a coded error for a protected API route."""
        resp = client.get('/api/v2/status')
        assert resp.status_code == 401
        assert resp.json()['detail']['code'] == 401

    def test_dual_band_create_is_rejected_before_radio_work(self, client, valid_token, reservation_id, monkeypatch):
        manager = client.app.state.context.manager
        from unittest.mock import Mock
        start = Mock()
        monkeypatch.setattr(manager, 'start_network', start)
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='open', band='dual', tx_power_level=4),
        )
        assert resp.status_code == 422
        assert resp.json()['detail']['code'] == 422
        start.assert_not_called()

    def test_protected_reservation_rejects_non_bearer_scheme(self, client):
        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': 'Basic invalid'},
            json={'duration_seconds': 120},
        )
        assert resp.status_code == 401
        assert resp.json()['detail']['code'] == 401
    
    def test_start_network_without_auth(self, client, reservation_id):
        """Test that network creation without auth is rejected."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            json=network_body(ssid='TestAP', channel=6, encryption='wpa2', band='2.4ghz', tx_power_level=4))
        assert resp.status_code == 401  # Unauthorized (no token)
    
    def test_start_network_with_invalid_token(self, client, invalid_token, reservation_id):
        """Test that request with invalid token is rejected."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': invalid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='wpa2', band='2.4ghz', tx_power_level=4))
        assert resp.status_code == 401  # Unauthorized
    
    def test_start_network_with_valid_token(self, client, valid_token, reservation_id, monkeypatch):
        """Test that request with valid token succeeds (with mocked DHCP)."""
        manager = client.app.state.context.manager
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **kw: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **kw: {})

        resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert resp.status_code == 200, resp.text
        assert resp.json()['active'] is True


class TestNetworkCreateEndpoint:
    """Tests for network creation endpoint."""
    
    def test_start_network_invalid_reservation(self, client, valid_token):
        """Test starting with an invalid reservation token returns 404."""
        resp = client.post(
            '/api/v2/access-point/invalid-token',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))
        assert resp.status_code == 404  # Reservation not found
    
    def test_start_network_invalid_encryption(self, client, valid_token, reservation_id):
        """Test that invalid encryption is rejected."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='invalid-encryption', band='2.4ghz', tx_power_level=4))
        assert resp.status_code == 422  # Validation error
    
    def test_start_network_invalid_band(self, client, valid_token, reservation_id):
        """Test that invalid band is rejected."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='wpa2', band='invalid-band'))
        assert resp.status_code == 422  # Validation error

    @pytest.mark.parametrize("body", [
        {'ssid': 'x\ninterface=eth0', 'channel': 6, 'encryption': 'open'},
        {'ssid': '', 'channel': 6, 'encryption': 'open'},
        {'ssid': 'x' * 33, 'channel': 6, 'encryption': 'open'},
        {'ssid': 'TestAP', 'channel': 6, 'encryption': 'wpa2', 'password': 'abc'},
        {'ssid': 'TestAP', 'channel': 6, 'encryption': 'wpa2'},
        {'ssid': 'TestAP', 'channel': 99, 'encryption': 'open'},
    ])
    def test_start_network_rejects_unsafe_or_invalid_fields(self, client, valid_token, reservation_id, body):
        """BUG-1: invalid SSID, password or channel must be a 422 before hostapd is touched."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
            json=network_body(**{**body, 'band': '2.4ghz', 'tx_power_level': 4}),
        )
        assert resp.status_code == 422
        assert resp.json()['detail']['code'] == 422

    def test_start_network_runtime_failure_is_start_failed(self, client, valid_token, reservation_id, monkeypatch):
        """Operational failures during startup end as start_failed with 1013, not 404 (REV-16)."""
        manager = client.app.state.context.manager
        monkeypatch.setattr(
            manager, 'start_network',
            Mock(side_effect=ValueError('Failed to start AP: hostapd failed to start')),
        )

        created, resp = create_network(
            client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}',
            network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))
        assert created.status_code == 202
        assert resp.json()['runtime_state'] == 'start_failed'
        assert resp.json()['error'] == {
            'code': 1013, 'reason': 'startup_failed', 'stage': None,
            'message': 'Failed to start AP: hostapd failed to start',
        }

    def test_create_returns_the_network(self, client, valid_token, reservation_id, monkeypatch):
        """API-5: a successful create answers what GET /access-point/{reservation_id} answers."""
        from unittest.mock import Mock

        from wilab.models import NetworkStatus
        manager = client.app.state.context.manager
        channels = client.app.state.context.channels
        monkeypatch.setattr(channels, 'validate_network', Mock())
        monkeypatch.setattr(manager, 'start_network', Mock())
        status = NetworkStatus(
            interface='wls16', active=True, ssid='TestAP', channel=6, band='2.4ghz',
            encryption='wpa2', password='testpass123', channel_width=20, reported_channel_width=20,
            wifi_generation=4, subnet='192.168.120.0/24', internet_enabled=True,
        )
        monkeypatch.setattr(manager, 'get_status', lambda device: status)
        url = f'/api/v2/access-point/{reservation_id}'
        headers = {'Authorization': valid_token}

        resp = create_network(client, headers, url, network_body(
            ssid='TestAP', channel=6, encryption='wpa2', password='testpass123',
            band='2.4ghz', tx_power_level=4,
        ))[1]

        assert resp.status_code == 200
        data = resp.json()
        assert data['active'] is True
        assert data['wifi']['ssid'] == 'TestAP'
        assert data['radio']['channel'] == 6
        assert data['reservation']['expires_in'] is not None
        assert data == client.get(url, headers=headers).json() | {'reservation': data['reservation']}

    def test_start_network_422_has_coded_detail(self, client, valid_token, reservation_id):
        """Validation errors should expose a stable code and a display message."""
        resp = client.post(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
            json=network_body(invalid='payload'))
        assert resp.status_code == 422
        data = resp.json()
        assert 'detail' in data
        assert data['detail']['code'] == 422
        assert data['detail']['message'].strip() != ''


class TestNetworkGetEndpoint:
    """Tests for getting network status."""
    
    def test_get_network_status_inactive(self, client, valid_token, reservation_id):
        """Test getting status of inactive network via valid reservation."""
        resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert (data['active'], data['runtime_state'], data['error']) == (False, None, None)
        assert data['restarts'] == {'ap': 0, 'dhcp': 0, 'last_at': None, 'last_reason': None}
    
    def test_get_network_status_invalid_reservation(self, client, valid_token):
        """Test getting status with invalid reservation returns 404."""
        resp = client.get(
            '/api/v2/access-point/invalid-token',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_get_network_active_with_dhcp_and_clients(self, client, valid_token, reservation_id, monkeypatch):
        """Test getting complete status of active network including DHCP and clients."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))

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
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        # Start network via reservation token
        start_resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert start_resp.status_code == 200

        # Get network status
        resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Validate complete response structure
        assert data['interface'] == 'wls16'
        assert data['active'] is True
        assert data['wifi'] == {
            'ssid': 'TestAP', 'hidden': False,
            'security': {'encryption': 'wpa2', 'password': 'testpass123'},
        }
        assert data['ip']['gateway'] == '192.168.10.1'
        assert data['ip']['dns_server'] == load_config().dns_server
        assert data['clients'] == []
        assert data['radio']['band'] == '2.4ghz' and data['radio']['channel'] == 6
        assert data['radio']['tx_power'] == {
            'requested_level': 4,
            'reported_level': 4,
            'reported_dbm': 20.0,
        }
        # API-8: no duplicated or internal fields.
        for gone in ('dhcp', 'clients_connected', 'tx_power_level', 'ssid', 'subnet', 'expires_at'):
            assert gone not in data

    def test_get_network_status_returns_client_entries_with_ip_and_mac(self, client, valid_token, reservation_id, monkeypatch):
        """Test active network status returns stable clients[] entries with ip and mac."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))

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
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        start_resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert start_resp.status_code == 200

        resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data['ip']['dhcp_range'] == {'start': '192.168.10.10', 'end': '192.168.10.250'}
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
        manager = NetworkManager(cfg, configured_devices(cfg))

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.hostapd_manager, 'stop', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'disable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'remove_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        start_resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert start_resp.status_code == 200

        stop_resp = client.delete(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert stop_resp.status_code == 200
        assert stop_resp.json() == {'detail': 'Access point on wls16 stopped'}
    
    def test_same_create_again_answers_the_network_a_different_one_1008(
        self, client, valid_token, reservation_id, monkeypatch, context,
    ):
        """A create repeated after a lost answer is safe: same body -> 200, different -> 409 / 1008."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        start = Mock(return_value={})
        monkeypatch.setattr(manager.hostapd_manager, 'start', start)
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)
        headers = {'Authorization': valid_token}
        url = f'/api/v2/access-point/{reservation_id}'
        body = network_body(
            ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz',
            tx_power_level=4,
        )
        first = create_network(client, headers, url, body)[1]
        assert first.status_code == 200

        again = client.post(url, headers=headers, json=body)
        assert again.status_code == 200
        assert again.json()['wifi'] == first.json()['wifi']
        assert start.call_count == 1  # nothing started twice

        other = network_body(
            ssid='OtherAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz',
            tx_power_level=4,
        )
        resp = client.post(url, headers=headers, json=other)
        assert resp.status_code == 409
        # API-3: an AP already running has its own code, not only a message.
        assert (resp.json()['detail']['code'], resp.json()['detail']['reason']) == (1008, 'access_point_already_active')

    def test_stop_stuck_in_the_kernel_is_503_and_a_repeat_finishes_it(
        self, client, valid_token, reservation_id, monkeypatch, context,
    ):
        """hostapd stuck after SIGKILL: repeated for STOP_RETRY_BUDGET, then a coded 503."""
        from wilab.api.routes import network as network_routes
        monkeypatch.setattr(network_routes, 'STOP_RETRY_BUDGET', 0.05)
        monkeypatch.setattr(network_routes, 'STOP_RETRY_PAUSE', 0.01)
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'disable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'remove_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)
        headers = {'Authorization': valid_token}
        url = f'/api/v2/access-point/{reservation_id}'
        assert create_network(client, headers, url, network_body(
            ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz',
            tx_power_level=4))[1].status_code == 200

        def stuck(*a, **k):
            raise RuntimeError("Failed to stop hostapd for wls16: Process 101153 stuck in the kernel")
        monkeypatch.setattr(manager.hostapd_manager, 'stop', stuck)
        resp = client.delete(url, headers=headers)
        assert resp.status_code == 503
        assert resp.headers['Retry-After'] == '5'
        assert (resp.json()['detail']['code'], resp.json()['detail']['reason']) == (1012, 'stop_incomplete')
        assert 'stuck in the kernel' in resp.json()['detail']['message']
        assert manager.stop_failed('wls16')
        assert client.get(url, headers=headers).json()['runtime_state'] == 'stop_failed'
        # A create now has its own code, not 1008: repeat the DELETE, then the create.
        create = client.post(url, headers=headers, json=network_body(
            ssid='OtherAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz',
            tx_power_level=4))
        assert (create.status_code, create.json()['detail']['code']) == (409, 1012)
        assert create.json()['detail']['reason'] == 'stop_incomplete'

        monkeypatch.setattr(manager.hostapd_manager, 'stop', lambda *a, **k: None)
        assert client.delete(url, headers=headers).status_code == 200
        assert not manager.stop_failed('wls16')
        assert 'wls16' not in manager.active

        # B: stuck for a moment only -> the server repeats the stop itself, the client sees 200.
        assert create_network(client, headers, url, network_body(
            ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz',
            tx_power_level=4))[1].status_code == 200
        monkeypatch.setattr(network_routes, 'STOP_RETRY_BUDGET', 5.0)
        calls = []

        def stuck_once(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                stuck()
        monkeypatch.setattr(manager.hostapd_manager, 'stop', stuck_once)
        assert client.delete(url, headers=headers).status_code == 200
        assert len(calls) == 2
        assert not manager.stop_failed('wls16')

    def test_startup_failure_names_its_stage(self, client, valid_token, reservation_id, monkeypatch):
        """A non-radio startup failure is start_failed with 1013 and the stage that failed."""
        from wilab.network.dhcp import DhcpServerError

        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})

        def dhcp_fails(*a, **k):
            raise DhcpServerError("dnsmasq refused the configuration")
        monkeypatch.setattr(manager.dhcp_server, 'start', dhcp_fails)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)
        _, resp = create_network(
            client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}',
            network_body(ssid='TestAP', channel=6, encryption='open', band='2.4ghz', tx_power_level=4),
        )
        assert resp.json()['runtime_state'] == 'start_failed'
        detail = resp.json()['error']
        assert (detail['code'], detail['reason'], detail['stage']) == (1013, 'startup_failed', 'dhcp')
        assert 'dnsmasq refused' in detail['message']

    def test_stop_network_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test stopping an inactive network returns 409."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        resp = client.delete(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data['detail']['code'] == 1007  # access_point_not_active
        assert data['detail']['message'] == 'No access point is active on wls16'
    
    def test_stop_network_invalid_reservation(self, client, valid_token):
        """Test stopping with invalid reservation returns 404."""
        resp = client.delete(
            '/api/v2/access-point/invalid-token',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404


class TestAccessPointOpenApi:
    """The published schema of GET /access-point/{reservation_id}."""

    def test_get_network_openapi_422_uses_coded_detail_schema(self, client, valid_token):
        resp = client.get('/openapi.json', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        schema = resp.json()

        network_get = schema['paths']['/api/v2/access-point/{reservation_id}']['get']
        response_422 = network_get['responses']['422']
        json_schema = response_422['content']['application/json']['schema']

        assert json_schema['type'] == 'object'
        assert 'code' in json_schema['properties']['detail']['required']


class TestInternetControlEndpoints:
    """Tests for internet enable/disable endpoints."""

    def test_disable_internet_failure_returns_500(self, client, valid_token, reservation_id, monkeypatch):
        manager = NetworkManager(load_config(), configured_devices())
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        def fail(_device):
            raise RuntimeError("firewall failed")

        monkeypatch.setattr(manager, 'disable_internet', fail)
        response = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/disable',
            headers={'Authorization': valid_token}
        )
        assert response.status_code == 500
        assert response.json()['detail'] == {
            'code': 500, 'reason': 'internal_server_error', 'message': 'firewall failed'
        }
    
    def test_enable_internet_success(self, client, valid_token, reservation_id, monkeypatch):
        """Test enabling internet on active network succeeds and returns detail message."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        # Start network first
        start_resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert start_resp.status_code == 200

        # Enable internet
        enable_resp = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert enable_resp.status_code == 200
        data = enable_resp.json()
        assert data == {'detail': 'Internet enabled on the access point on wls16'}
    
    def test_disable_internet_success(self, client, valid_token, reservation_id, monkeypatch):
        """Test disabling internet on active network succeeds and returns detail message."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        
        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.nat_manager, 'disable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        # Start network first
        start_resp = create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]
        assert start_resp.status_code == 200

        # Enable internet first
        enable_resp = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert enable_resp.status_code == 200

        # Then disable internet
        disable_resp = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/disable',
            headers={'Authorization': valid_token}
        )
        assert disable_resp.status_code == 200
        data = disable_resp.json()
        assert data == {'detail': 'Internet disabled on the access point on wls16'}
    
    def test_enable_internet_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test enabling internet on inactive network fails."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        resp = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/enable',
            headers={'Authorization': valid_token}
        )
        # API-2: a valid reservation without a network is 409 / 1007, never 404.
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == 1007
    
    def test_disable_internet_inactive(self, client, valid_token, reservation_id, monkeypatch):
        """Test disabling internet on inactive network fails."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        resp = client.post(
            f'/api/v2/access-point/{reservation_id}/internet/disable',
            headers={'Authorization': valid_token}
        )
        # API-2: a valid reservation without a network is 409 / 1007, never 404.
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == 1007


class TestReservationRequiredForOperations:
    """Tests that network operations require a valid reservation token."""

    def test_network_op_without_reservation_returns_404(self, client, valid_token):
        """Any network operation with invalid reservation returns 404."""
        resp = client.get(
            '/api/v2/access-point/nonexistent-token',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404
        assert resp.json()['detail']['code'] == 404
        assert resp.json()['detail']['reason'] == 'reservation_not_found'
        assert 'Reservation' in resp.json()['detail']['message']

    def test_internet_op_without_reservation_returns_404(self, client, valid_token):
        """Internet enable with invalid reservation returns 404."""
        resp = client.post(
            '/api/v2/access-point/nonexistent-token/internet/enable',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_txpower_op_without_reservation_returns_404(self, client, valid_token):
        """TX power GET with invalid reservation returns 404."""
        resp = client.get(
            '/api/v2/access-point/nonexistent-token/tx-power',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404

    def test_expired_reservation_returns_404(self, client, valid_token, monkeypatch):
        """Expired reservation token is rejected with 404."""
        import time

        rmgr = client.app.state.context.reservations
        r = rmgr.create(3600)
        # Force expiry
        r.expires_at = time.time() - 1

        resp = client.get(
            f'/api/v2/access-point/{r.reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 404
        assert resp.json()['detail']['reason'] == 'reservation_expired'
        # Still the reason after the expired reservation was purged.
        again = client.get(f'/api/v2/reservations/{r.reservation_id}', headers={'Authorization': valid_token})
        assert again.json()['detail']['reason'] == 'reservation_expired'

    def test_released_reservation_returns_404(self, client, valid_token):
        """Released reservation token is rejected with 404."""
        # Create and immediately release
        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 3600},
        )
        rid = resp.json()['reservation_id']
        client.delete(
            f'/api/v2/reservations/{rid}',
            headers={'Authorization': valid_token}
        )

        # Try to use the released token
        resp = client.post(
            f'/api/v2/access-point/{rid}',
            headers={'Authorization': valid_token},
            json=network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))
        assert resp.status_code == 404
        assert resp.json()['detail']['reason'] == 'reservation_released'


class TestStatusReservationInfo:
    """Tests for reservation info in status endpoint (Task 6)."""

    def test_status_antennas_have_reservation_and_network_active(self, client, valid_token, monkeypatch):
        """Each antenna has `reservation` (null when free) and `access_point_active` (API-1)."""
        cfg = load_config()
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        # Before a reservation: `reservation` is null
        resp = client.get('/api/v2/antennas', headers={'Authorization': valid_token})
        data = resp.json()
        net_entry = data['antennas'][0]
        assert 'display_name' in net_entry
        assert 'interface' in net_entry
        assert net_entry['reservation'] is None
        assert net_entry['access_point_active'] is False
        assert 'reserved' not in net_entry and 'reservation_remaining_seconds' not in net_entry

    def test_status_reservation_expiry_after_reservation(self, client, valid_token, reservation_id):
        """A reserved antenna reports `reservation.expires_at` and `expires_in`."""
        resp = client.get('/api/v2/antennas', headers={'Authorization': valid_token})
        data = resp.json()
        net_entry = data['antennas'][0]
        assert net_entry['display_name'] == 'bench-antenna-1'
        assert net_entry['interface'] == 'wls16'
        remaining = net_entry['reservation']['expires_in']
        assert net_entry['reservation']['expires_at'].endswith('Z')
        assert isinstance(remaining, int)
        assert remaining > 3500  # 3600s reservation, allow small margin


class TestGetNetworkExpiryAlwaysPresent:
    """Tests that Get Network always exposes expires_at/expires_in (Task 6)."""

    def test_get_network_off_still_has_expiry(self, client, valid_token, reservation_id, monkeypatch):
        """When network is off, expires_at and expires_in from reservation are present."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['active'] is False
        assert data['reservation']['expires_at'] is not None
        assert isinstance(data['reservation']['expires_at'], str)
        assert data['reservation']['expires_at'].endswith('Z')
        reservation = client.get(
            f'/api/v2/reservations/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert reservation.status_code == 200
        assert data['reservation']['expires_at'] == reservation.json()['expires_at']
        assert data['reservation']['expires_in'] is not None
        assert data['reservation']['expires_in'] > 3500

    def test_get_network_active_has_expiry(self, client, valid_token, reservation_id, monkeypatch):
        """When network is active, expires_at and expires_in are present."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))

        monkeypatch.setattr(manager.dhcp_server, 'start', lambda *a, **k: {'gateway': '192.168.10.1'})
        monkeypatch.setattr(manager.hostapd_manager, 'start', lambda *a, **k: {})
        monkeypatch.setattr(manager.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(manager.isolation_manager, 'add_network', lambda *a, **k: None)
        monkeypatch.setattr(manager.tx_power, 'read_dbm', lambda _iface: 20.0)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)

        create_network(client, {'Authorization': valid_token}, f'/api/v2/access-point/{reservation_id}', network_body(ssid='TestAP', channel=6, encryption='wpa2', password='testpass123', band='2.4ghz', tx_power_level=4))[1]

        resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['active'] is True
        assert data['reservation']['expires_at'].endswith('Z')
        assert data['reservation']['expires_in'] is not None
        assert data['reservation']['expires_in'] > 3500


class TestNamingCleanup:
    """Tests for Task 7 naming conventions and OpenAPI contract."""

    def test_openapi_paths_use_reservation_id(self, client, valid_token):
        """OpenAPI paths use {reservation_id}, not {device_id}."""
        resp = client.get('/openapi.json', headers={'Authorization': valid_token})
        schema = resp.json()
        paths = list(schema['paths'].keys())
        for p in paths:
            if '/reservations/{' in p:
                assert '{reservation_id}' in p, f"Path {p} should use {{reservation_id}}"
                assert '{device_id}' not in p, f"Path {p} should not use {{device_id}}"

    def test_static_config_net_id_not_used_as_key(self):
        """Config does not expose net_id as operational key."""
        cfg = load_config()
        for net in cfg.antennas:
            assert not hasattr(net, 'net_id') or net.device_id == net.interface
            assert net.device_id == net.interface


# ======================================================================
# Unlimited reservation API tests
# ======================================================================


class TestUnlimitedReservationAPI:
    """API-level tests for unlimited (duration_seconds=0) reservations."""

    def test_create_unlimited_when_allowed(self, client, valid_token, monkeypatch):
        """POST with duration_seconds=0 and allow_unlimited_reservation=true → 200."""
        cfg = load_config()
        monkeypatch.setattr(cfg, 'allow_unlimited_reservation', True)
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'config', cfg)
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['expires_at'] is None
        assert data['expires_in'] is None

    def test_create_unlimited_when_not_allowed(self, client, valid_token, monkeypatch):
        """POST with duration_seconds=0 and allow_unlimited_reservation=false → 422."""
        cfg = load_config()
        monkeypatch.setattr(cfg, 'allow_unlimited_reservation', False)
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 0},
        )
        assert resp.status_code == 422

    def test_get_unlimited_reservation_has_null_expiry(self, client, valid_token, monkeypatch):
        """GET reservation returns expires_at/expires_in as null for unlimited."""
        cfg = load_config()
        monkeypatch.setattr(cfg, 'allow_unlimited_reservation', True)
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'config', cfg)
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        create_resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 0},
        )
        assert create_resp.status_code == 200
        reservation_id = create_resp.json()['reservation_id']

        get_resp = client.get(
            f'/api/v2/reservations/{reservation_id}',
            headers={'Authorization': valid_token},
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data['expires_at'] is None
        assert data['expires_in'] is None

    def test_get_network_for_unlimited_reservation_has_null_expiry(self, client, valid_token, monkeypatch):
        """GET network returns expires_at/expires_in as null for unlimited reservations."""
        cfg = load_config()
        manager = NetworkManager(cfg, configured_devices(cfg))
        monkeypatch.setattr(cfg, 'allow_unlimited_reservation', True)
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'config', cfg)
        monkeypatch.setattr(client.app.state.context, 'manager', manager)
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        create_resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 0},
        )
        assert create_resp.status_code == 200
        reservation_id = create_resp.json()['reservation_id']

        get_resp = client.get(
            f'/api/v2/access-point/{reservation_id}',
            headers={'Authorization': valid_token},
        )
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data['active'] is False
        assert data['reservation']['expires_at'] is None
        assert data['reservation']['expires_in'] is None

    def test_create_duration_below_min_timeout(self, client, valid_token, monkeypatch):
        """POST with duration_seconds < min_timeout (and != 0) → 422."""
        cfg = load_config()
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': cfg.min_timeout - 1},
        )
        assert resp.status_code == 422

    def test_create_duration_above_max_timeout(self, client, valid_token, monkeypatch):
        """POST with duration_seconds > max_timeout → 422."""
        cfg = load_config()
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': cfg.max_timeout + 1},
        )
        assert resp.status_code == 422

    def test_antennas_expose_reservation_policy(self, client, valid_token, monkeypatch):
        """/antennas includes reservation_policy with min, max, and allow_unlimited."""
        cfg = load_config()
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        resp = client.get('/api/v2/antennas', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()
        assert 'reservation_policy' in data
        policy = data['reservation_policy']
        assert policy['min_seconds'] == cfg.min_timeout
        assert policy['max_seconds'] == cfg.max_timeout
        assert policy['allow_unlimited'] is False

    def test_status_shows_null_expiry_for_unlimited(self, client, valid_token, monkeypatch):
        """/antennas: an unlimited reservation is an object with null expiry, not a free antenna."""
        cfg = load_config()
        monkeypatch.setattr(cfg, 'allow_unlimited_reservation', True)
        rmgr = ReservationManager(configured_devices(cfg))
        monkeypatch.setattr(client.app.state.context, 'config', cfg)
        monkeypatch.setattr(client.app.state.context, 'reservations', rmgr)

        # Create unlimited reservation
        resp = client.post(
            '/api/v2/reservations',
            headers={'Authorization': valid_token},
            json={'duration_seconds': 0},
        )
        assert resp.status_code == 200

        # Check status
        resp = client.get('/api/v2/antennas', headers={'Authorization': valid_token})
        assert resp.status_code == 200
        data = resp.json()
        reserved_net = [n for n in data['antennas'] if n['reservation'] is not None]
        assert reserved_net[0]['reservation'] == {'expires_at': None, 'expires_in': None}


def test_unexpected_error_is_answered_without_dropping_the_connection(caplog):
    """A bug answers a coded 500 and is not re-raised: uvicorn would close the connection."""
    app = create_app()

    def boom():
        raise RuntimeError("unexpected")

    app.add_api_route("/api/v2/boom", boom)
    app.router.routes.insert(0, app.router.routes.pop())   # before the frontend catch-all

    # raise_server_exceptions=True: the test fails if the exception reaches the server.
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get("/api/v2/boom")
    assert resp.status_code == 500
    assert resp.json()["detail"]["code"] == 500
    assert "Unhandled error in GET /api/v2/boom" in caplog.text


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/api/v1/status"),
    ("POST", "/api/v1/reservations"),
    ("DELETE", "/api/v1/reservations/abc"),
    ("GET", "/api/v3/anything"),
])
def test_removed_or_unknown_api_paths_are_a_json_404(method, path, tmp_path, monkeypatch):
    """/api/v1 was removed in 4.0.0: a JSON 404, never the frontend page or an empty 200."""
    from wilab import api as api_module

    (tmp_path / "index.html").write_text("<html>frontend</html>")
    monkeypatch.setattr(api_module, "_candidate_frontend_paths", lambda: [tmp_path])
    resp = TestClient(create_app()).request(method, path)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == 404


def test_every_route_is_under_api_v2():
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    assert paths and all(p.startswith("/api/v2/") for p in paths)


# --------------------------------------------------------------------------- unit-test-13


@pytest.fixture
def stop_clock(monkeypatch, app, context):
    """A running network through the API; the stop route's monotonic and sleep are a fake clock."""
    from wilab.api.routes import network as network_routes

    config = context.config
    manager = context.manager
    instances = manager.hostapd_manager._instances
    monkeypatch.setattr(manager.hostapd_manager, "start", lambda *, net_id, **kw: instances.__setitem__(net_id, Mock()))
    monkeypatch.setattr(manager.hostapd_manager, "stop", lambda net_id: instances.pop(net_id, None))
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(manager.dhcp_server, "stop", Mock())
    clock = {"now": 100.0, "pauses": []}

    def sleep(seconds):
        clock["pauses"].append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(network_routes, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(network_routes, "sleep", sleep)
    headers = {"Authorization": f"Bearer {config.auth_token}"}
    with TestClient(app) as client:
        rid = client.post("/api/v2/reservations", headers=headers, json={"duration_seconds": 300}).json()[
            "reservation_id"]
        url = f"/api/v2/access-point/{rid}"
        body = network_body(ssid="stop-budget", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
        assert create_network(client, headers, url, body)[1].json()["active"] is True
        yield client, headers, url, manager, clock
        manager.active.clear()


def test_stop_retry_budget_with_a_fake_clock(stop_clock, monkeypatch):
    """unit-test-13: 8 attempts 2 s apart in the 15 s budget, then 503 / 1012; a stop that recovers is 200."""
    from wilab.api.routes import network as network_routes
    from wilab.network.commands import CommandError

    client, headers, url, manager, clock = stop_clock
    assert (network_routes.STOP_RETRY_BUDGET, network_routes.STOP_RETRY_PAUSE) == (15.0, 2.0)
    # Attempts at 0, 2, ..., 14 s: after the one at 14 s a pause would reach the 15 s deadline.
    attempts = 8
    device = manager.config.antennas[0].device_id
    real_stop = manager.hostapd_manager.stop
    stuck = Mock(side_effect=CommandError("hostapd stuck in the kernel"))
    monkeypatch.setattr(manager.hostapd_manager, "stop", stuck)
    resp = client.delete(url, headers=headers)
    assert (resp.status_code, resp.json()["detail"]["code"]) == (503, 1012)
    assert resp.headers["Retry-After"] == "5"
    assert stuck.call_count == attempts
    assert clock["pauses"] == [2.0] * (attempts - 1)
    lock = manager.devices.lock(device)
    assert lock.acquire(blocking=False)   # the failed stop did not keep the device
    lock.release()
    state = client.get(url, headers=headers)
    assert (state.status_code, state.json()["runtime_state"]) == (200, "stop_failed")

    clock["pauses"].clear()
    calls = {"n": 0}

    def stop_on_the_third_attempt(net_id):
        calls["n"] += 1
        if calls["n"] < 3:
            raise CommandError("hostapd stuck in the kernel")
        real_stop(net_id)

    monkeypatch.setattr(manager.hostapd_manager, "stop", stop_on_the_third_attempt)
    assert client.delete(url, headers=headers).status_code == 200
    assert calls["n"] == 3 and clock["pauses"] == [2.0, 2.0]
    assert device not in manager.active and not manager.stop_failed(device)


def test_tx_power_endpoints_are_removed(client, valid_token):
    """2026-11-28: the mt7921u ignores the level in AP mode and a change on a running AP hung the VM."""
    paths = client.get('/openapi.json', headers={'Authorization': valid_token}).json()['paths']
    assert not any('tx-power' in path or 'txpower' in path for path in paths)
    resp = client.post('/api/v2/access-point/deadbeef/tx-power', headers={'Authorization': valid_token},
                       json={'tx_power_level': 2})
    assert resp.status_code in (404, 405)
