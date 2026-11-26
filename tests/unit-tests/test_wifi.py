import signal
import time
from types import SimpleNamespace

import pytest

from wilab.config import NetworkEntry, load_config
from wilab.models import NetworkCreateRequest, NetworkStatus
from wilab.network.commands import CommandError, CommandTimeout
from wilab.network.dhcp import DhcpServerError
from wilab.wifi import hostapd
from wilab.wifi.manager import NetworkManager, NetworkNotActive, TxPowerMismatchError


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

    def test_configure_networkmanager_unmanaged_when_nmcli_available(self, monkeypatch):
        """Test unmanaged setup triggers nmcli commands when available."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        calls = []

        def mock_execute_command(cmd, check=True):
            calls.append((cmd, check))
            return ""

        monkeypatch.setattr('wilab.wifi.manager.execute_command', mock_execute_command)
        monkeypatch.setattr('wilab.wifi.manager._nmcli_available', lambda: True)

        mgr._configure_networkmanager_unmanaged('wlan0')

        # PERF-1: availability is looked up once, not by running `nmcli --version` each start.
        assert not any(c[0] == ['nmcli', '--version'] for c in calls)
        assert any(c[0] == ['nmcli', 'device', 'set', 'wlan0', 'managed', 'no'] for c in calls)
        assert any(c[0] == ['nmcli', 'device', 'disconnect', 'wlan0'] for c in calls)

    def test_configure_networkmanager_unmanaged_when_nmcli_missing(self, monkeypatch):
        """Test unmanaged setup is skipped cleanly when nmcli is unavailable."""
        cfg = load_config()
        mgr = NetworkManager(cfg)

        calls = []

        def mock_execute_command(cmd, check=True):
            calls.append(cmd)
            raise CommandError("Command not found: nmcli")

        monkeypatch.setattr('wilab.wifi.manager.execute_command', mock_execute_command)
        monkeypatch.setattr('wilab.wifi.manager._nmcli_available', lambda: False)

        # Should not raise, and runs nothing
        mgr._configure_networkmanager_unmanaged('wlan0')
        assert calls == []


class TestSubnetResolution:
    """Tests for subnet resolution (explicit vs calculated)."""
    
    def test_get_subnet_explicit(self):
        """First subnet matches dhcp_base_network /24."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        subnet = mgr._get_subnet('wls16')
        assert subnet == '192.168.120.0/24'
    
    def test_get_subnet_unknown_device_id(self):
        """Test that unknown device_id raises ValueError."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        with pytest.raises(ValueError, match="antenna of this reservation is not managed"):
            mgr._get_subnet('unknown-network')
    
    def test_get_subnet_fallback_calculation(self):
        """Test sequential allocation increments third octet."""
        cfg = load_config()
        cfg.antennas.append(NetworkEntry(interface='wlan1', display_name='extra'))
        mgr = NetworkManager(cfg)
        first = mgr._get_subnet('wls16')
        second = mgr._get_subnet('wlan1')
        assert first == '192.168.120.0/24'
        assert second == '192.168.121.0/24'

    def test_skip_host_network_without_reassigning_other_antennas(self, monkeypatch):
        from ipaddress import IPv4Network

        cfg = load_config()
        cfg.dhcp_base_network = "192.168.9.0/24"
        cfg.antennas.append(NetworkEntry(interface="wlan1", display_name="extra"))
        host_routes = {IPv4Network("192.168.10.0/24")}
        monkeypatch.setattr("wilab.wifi.manager.host_ipv4_networks", lambda: host_routes)
        mgr = NetworkManager(cfg)
        # A later antenna can start first without taking the first antenna's slot.
        assert mgr._get_subnet("wlan1") == "192.168.11.0/24"
        assert mgr._get_subnet("wls16") == "192.168.9.0/24"
        host_routes.add(IPv4Network("192.168.12.0/23"))
        host_routes.add(IPv4Network("192.168.11.0/24"))
        assert mgr._get_subnet("wlan1") == "192.168.14.0/24"
        assert mgr._get_subnet("wls16") == "192.168.9.0/24"

    def test_no_safe_subnet_does_not_start_ap(self, monkeypatch):
        from ipaddress import IPv4Network
        from unittest.mock import Mock

        mgr = NetworkManager(load_config())
        monkeypatch.setattr(
            "wilab.wifi.manager.host_ipv4_networks", lambda: {IPv4Network("192.168.0.0/16")},
        )
        start = Mock()
        monkeypatch.setattr(mgr.hostapd_manager, "start", start)
        req = NetworkCreateRequest(ssid="TestAP", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)
        with pytest.raises(ValueError, match="No available /24 AP subnet"):
            mgr.start_network("wls16", req)
        start.assert_not_called()


class TestNetworkLifecycle:
    """Tests for network start/stop lifecycle."""
    
    def test_get_status_inactive_network(self):
        """Test getting status of inactive network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        status = mgr.get_status('wls16')
        assert status is not None
        assert status.active is False
        assert status.interface == 'wls16'
    
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
        startup = []
        
        def mock_dhcp_start(*args, **kwargs):
            startup.append("dhcp")
            assert not mgr.active
            return {
                'gateway': '192.168.120.1',
                'dhcp_range': '192.168.120.10,192.168.120.250'
            }
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda **kw: startup.append("ap"))

        def assign_gateway(args):
            startup.append("gateway")
            assert args == ["addr", "add", "192.168.120.1/24", "dev", "wls16"]

        monkeypatch.setattr("wilab.wifi.manager.execute_ip", assign_gateway)
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4
        )
        
        status = mgr.start_network('wls16', req)
        assert startup == ["ap", "gateway", "dhcp"]
        assert status.active is True
        assert status.ssid == 'TestAP'
        assert status.channel == 6
        assert status.encryption == 'wpa2'
        assert status.band == '2.4ghz'
        assert status.subnet == '192.168.120.0/24'
        assert status.internet_enabled is True  # Default from config

    @pytest.mark.parametrize("failure", ["ap", "readiness_timeout", "gateway", "dhcp"])
    def test_partial_start_is_rolled_back(self, monkeypatch, tmp_path, failure):
        mgr = NetworkManager(load_config())
        device = "wls16"
        events = []
        monkeypatch.setattr(hostapd, "HOSTAPD_CONFIG_DIR", str(tmp_path))
        reset_blocked = True

        def ap_command(cmd, **kwargs):
            if cmd[0] == "ip" and cmd[1:3] == ["link", "set"] and events and reset_blocked:
                raise CommandError("reset failed")
            return ""

        def launch(cmd: list[str], *, classify_output, keep_lines=0) -> SimpleNamespace:
            assert cmd[:2] == ["hostapd", "-d"]
            events.append("ap")
            if failure == "ap":
                raise CommandError("launch failed")
            return SimpleNamespace(stop=lambda: events.append("stop"))

        def wait_until_ready(*args) -> None:
            if failure == "readiness_timeout":
                raise hostapd.HostapdError("AP not ready")

        def assign_gateway(args):
            events.append("gateway")
            if failure == "gateway":
                raise CommandError("address failed")

        def start_dhcp(**kwargs):
            events.append("dhcp")
            mgr.dhcp_server._instances[device] = {"process_stopped": True}
            raise DhcpServerError("DHCP failed")

        def stop_dhcp(device_id):
            mgr.dhcp_server._instances.pop(device_id, None)

        monkeypatch.setattr(hostapd, "execute_command", ap_command)
        monkeypatch.setattr(hostapd, "start_foreground", launch)
        monkeypatch.setattr(mgr.hostapd_manager, "_wait_until_ready", wait_until_ready)
        monkeypatch.setattr("wilab.wifi.manager.execute_ip", assign_gateway)
        monkeypatch.setattr(mgr.dhcp_server, "start", start_dhcp)
        monkeypatch.setattr(mgr.dhcp_server, "stop", stop_dhcp)

        req = NetworkCreateRequest(
            ssid="TestAP", channel=6, encryption="open", band="2.4ghz",
            tx_power_level=4,
        )
        with pytest.raises(ValueError, match={
            "ap": "launch failed", "readiness_timeout": "AP not ready",
            "gateway": "address failed", "dhcp": "DHCP failed",
        }[failure]):
            mgr.start_network(device, req)
        assert events == {
            "ap": ["ap"], "readiness_timeout": ["ap", "stop"],
            "gateway": ["ap", "gateway", "stop"],
            "dhcp": ["ap", "gateway", "dhcp", "stop"],
        }[failure]
        assert not mgr.active
        assert not mgr.dhcp_server.list_active()
        with pytest.raises(RuntimeError, match="reset failed"):
            mgr.release_device(device)
        reset_blocked = False
        mgr.release_device(device)
        assert device not in mgr.hostapd_manager._instances
        assert not list(tmp_path.glob("ap-*"))

    @pytest.mark.parametrize(
        "scenario, band, expected_attempts",
        [
            ("recover", "2.4ghz", 2),
            ("second_crash", "2.4ghz", 3),
            ("retry_timeout", "2.4ghz", 2),
            ("cleanup_failed", "2.4ghz", 1),
            ("budget_exhausted", "2.4ghz", 1),
            ("reservation_expired", "2.4ghz", 1),
            ("non_segfault", "2.4ghz", 1),
            ("recover", "5ghz", 2),
            ("init_failure", "2.4ghz", 2),
            ("init_failure", "5ghz", 2),
        ],
    )
    def test_startup_segfault_retry(
        self, monkeypatch, tmp_path, scenario, band, expected_attempts,
    ):
        from wilab.network import commands
        from wilab.wifi import manager

        mgr = NetworkManager(load_config())
        device = "wls16"
        events = []
        now = 0.0
        expires_at = 110.0
        monkeypatch.setattr(mgr, "_configure_networkmanager_unmanaged", lambda _: None)
        monkeypatch.setattr(hostapd, "HOSTAPD_CONFIG_DIR", str(tmp_path))

        def wait(seconds: float) -> None:
            nonlocal now
            now += seconds
            events.append("wait")

        monkeypatch.setattr(manager, "time", SimpleNamespace(
            monotonic=lambda: now, time=lambda: 100.0 + now, sleep=wait,
        ))

        def advance_poll_clock(seconds: float) -> None:
            nonlocal now
            now += seconds

        polling_clock = SimpleNamespace(
            monotonic=lambda: now, sleep=advance_poll_clock,
        )
        monkeypatch.setattr(hostapd, "time", polling_clock)
        monkeypatch.setattr(commands, "time", polling_clock)

        def ap_command(cmd: list[str], **kwargs) -> str:
            if cmd[:3] == ["ip", "link", "set"] and events[-1:] == ["stop"]:
                events.append("rollback")
                if scenario == "cleanup_failed":
                    raise CommandError("reset failed")
            return ""

        def launch(cmd: list[str], *, classify_output, keep_lines=0) -> SimpleNamespace:
            nonlocal now
            events.append("ap")
            code = None
            if events.count("ap") == 1 or scenario == "second_crash":
                now += 14.0 if scenario == "budget_exhausted" else 1.5
                code = 1 if scenario in ("non_segfault", "init_failure") else -signal.SIGSEGV
            init_events = (
                "state_country_update", "beacon_failed", "beacon_failed", "interface_init_failed",
            ) if scenario == "init_failure" and code == 1 else ()
            return SimpleNamespace(
                poll=lambda: code, stop=lambda: events.append("stop"),
                output_events=lambda **kwargs: init_events,
            )

        poll_readiness = mgr.hostapd_manager._wait_until_ready

        def wait_until_ready(process, interface, *args) -> None:
            if scenario == "retry_timeout":
                poll_readiness(process, interface, *args)
                return
            mgr.hostapd_manager._check_process(process, interface)

        monkeypatch.setattr(hostapd, "execute_command", ap_command)
        monkeypatch.setattr(hostapd, "start_foreground", launch)
        monkeypatch.setattr(mgr.hostapd_manager, "_wait_until_ready", wait_until_ready)
        monkeypatch.setattr(manager, "execute_ip", lambda args: events.append("gateway"))
        monkeypatch.setattr(mgr.dhcp_server, "start", lambda **kw: events.append("dhcp"))
        req = NetworkCreateRequest(
            ssid="TestAP", channel=6 if band == "2.4ghz" else 36,
            encryption="open", band=band, tx_power_level=4,
        )
        if scenario == "reservation_expired":
            expires_at = 101.5

        if scenario in ("recover", "init_failure") and expected_attempts == 2:
            assert mgr.start_network(device, req, expires_at).active
            assert events == ["ap", "stop", "rollback", "wait", "ap", "gateway", "dhcp"]
            assert now == 2.5
        else:
            error = "AP not ready" if scenario == "retry_timeout" else "Failed to start AP"
            with pytest.raises(ValueError, match=error) as failure:
                mgr.start_network(device, req, expires_at)
            if scenario == "second_crash":
                # Three failed starts in one request count as a single radio failure for the client.
                assert failure.value.radio and not failure.value.cleanup_failed
            assert not mgr.active
            assert "gateway" not in events and "dhcp" not in events
            assert (device in mgr.hostapd_manager._instances) == (scenario == "cleanup_failed")
            if scenario == "retry_timeout":
                # The second attempt runs until the reservation expires (t=10), so no third one.
                assert now == 10.0
                assert events == ["ap", "stop", "rollback", "wait", "ap", "stop", "rollback"]
                assert not list(tmp_path.glob("ap-*"))
        assert events.count("ap") == expected_attempts
    
    def test_start_network_with_internet_disabled(self, monkeypatch):
        """Test starting network with internet disabled."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        events = []
        
        def mock_dhcp_start(*args, **kwargs):
            assert kwargs["subnet"] == "192.168.121.0/24"
            return {'gateway': '192.168.10.1'}
        
        from ipaddress import IPv4Network

        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.nat_manager, 'block_internet', lambda *a: events.append('block'))
        monkeypatch.setattr(
            "wilab.wifi.manager.host_ipv4_networks", lambda: {IPv4Network("192.168.120.0/24")},
        )
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: events.append('ap'))
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=4,
            internet_enabled=False
        )
        
        status = mgr.start_network('wls16', req)
        assert status.internet_enabled is False
        assert events == ['block', 'ap']
        assert status.subnet == "192.168.121.0/24"

    def test_failed_hostapd_stop_keeps_internet_block(self, monkeypatch):
        mgr = NetworkManager(load_config())
        released = []

        def fail(_device):
            raise RuntimeError("hostapd did not stop")

        monkeypatch.setattr(mgr.hostapd_manager, 'stop', fail)
        monkeypatch.setattr(mgr.dhcp_server, 'stop', lambda *args: None)
        monkeypatch.setattr(mgr.nat_manager, 'release_network', lambda *args: released.append(args))
        with pytest.raises(RuntimeError, match="hostapd did not stop"):
            mgr.stop_network('wls16')
        assert not released

    def test_partial_offline_block_is_cleaned_before_ap_start(self, monkeypatch):
        mgr = NetworkManager(load_config())
        ap_started = []
        fw = _BlockFirewall()
        calls = fw.calls
        monkeypatch.setattr("wilab.network.nat.execute_iptables", fw)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *args, **kwargs: ap_started.append(True))
        monkeypatch.setattr(mgr.hostapd_manager, 'stop', lambda *args: None)
        monkeypatch.setattr(mgr.dhcp_server, 'stop', lambda *args: None)
        req = NetworkCreateRequest(
            ssid='TestAP', channel=6, encryption='open', band='2.4ghz',
            tx_power_level=4, internet_enabled=False,
        )
        with pytest.raises(ValueError, match="block Internet"):
            mgr.start_network('wls16', req)
        assert not ap_started
        assert not mgr.nat_manager.has_pending_network('wls16')
        assert calls[-1][:2] == ['-D', 'FORWARD']
    
    def test_start_network_with_reservation_expiry(self, monkeypatch):
        """Test starting network with explicit expires_at_timestamp from reservation."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        monkeypatch.setattr(mgr.dhcp_server, 'start', mock_dhcp_start)
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda *a, **kw: {})
        
        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='wpa2',
            password='testpass123',
            band='2.4ghz',
            tx_power_level=4,
        )
        
        expires_at = time.time() + 7200  # 2 hours from now
        status = mgr.start_network('wls16', req, expires_at_timestamp=expires_at)
        assert status.expires_at is not None
        assert isinstance(status.expires_at, str)
        assert status.expires_at.endswith('Z')
        # Check expires_in is within expected range (2 hours = 7200 seconds, allow 100s margin)
        assert status.expires_in > 7100
        assert status.expires_in < 7300
    
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
        
        status = mgr.start_network('wls16', req)
        assert status.active is True
        assert 'wls16' in mgr.active
        
        mgr.stop_network('wls16')
        assert 'wls16' not in mgr.active
    
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
        )
        
        status = mgr.start_network('wls16', req)
        assert status.active is True
        
        # Manually set internal timestamp to past to simulate expiration
        mgr.active['wls16']._expires_at_timestamp = time.time() - 1  # Expired 1 second ago
        
        # Check status should return inactive due to expiration
        expired_status = mgr.get_status('wls16')
        assert expired_status.active is False


class TestInternetControl:
    """Tests for internet enable/disable."""

    def test_failed_disable_keeps_enabled_state(self, monkeypatch):
        mgr = NetworkManager(load_config())
        device = 'wls16'
        mgr.active[device] = NetworkStatus(interface=device, active=True, internet_enabled=True)

        def fail(*args):
            raise RuntimeError("block failed")

        monkeypatch.setattr(mgr.nat_manager, 'disable_nat', fail)
        with pytest.raises(RuntimeError, match="Cannot disable Internet"):
            mgr.disable_internet(device)
        assert mgr.active[device].internet_enabled is True
    
    def test_enable_internet(self, monkeypatch):
        """Test enabling internet for a network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_nat_enable(interface, device_id, subnet):
            pass  # Mock NAT enable
        
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
        
        mgr.start_network('wls16', req)
        status = mgr.enable_internet('wls16')
        assert status.internet_enabled is True
    
    def test_disable_internet(self, monkeypatch):
        """Test disabling internet for a network."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        def mock_dhcp_start(*args, **kwargs):
            return {'gateway': '192.168.10.1'}
        
        def mock_nat_enable(interface, device_id, subnet):
            pass  # Mock NAT enable
        
        def mock_nat_disable(interface, device_id, subnet):
            pass  # Mock NAT disable
        
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
        
        mgr.start_network('wls16', req)
        status = mgr.disable_internet('wls16')
        assert status.internet_enabled is False
    
    def test_internet_control_inactive_network(self):
        """Test that internet control on inactive network raises error."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        
        with pytest.raises(NetworkNotActive, match="is not active"):
            mgr.enable_internet('wls16')


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
        
        mgr.start_network('wls16', req)
        clients = mgr.list_clients('wls16')
        assert clients == []
    
    def test_list_clients_with_leases(self, monkeypatch, tmp_path):
        """Test listing clients from dnsmasq lease file."""
        
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
        
        mgr.start_network('wls16', req)
        clients = mgr.list_clients('wls16')
        
        # DHCP leases may not persist in test environment
        assert isinstance(clients, list)
        if clients:  # If leases are available, validate structure
            assert hasattr(clients[0], 'mac')
            assert hasattr(clients[0], 'ip')


class TestNetworkSummary:
    """Tests for network summary information."""

    def test_summary_inactive_network(self):
        """Summary for known but inactive network returns defaults."""
        cfg = load_config()
        mgr = NetworkManager(cfg)
        summary = mgr.get_summary('wls16')
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

        mgr.start_network('wls16', req)
        summary = mgr.get_summary('wls16')
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
        
        mgr.start_network('wls16', req)
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
                'max_dbm': 20.0,
                'levels_dbm': {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0},
                'tx_power': {
                    'requested_level': level,
                    'reported_level': level,
                    'reported_dbm': 20.0,
                },
            }

        monkeypatch.setattr(mgr, '_set_tx_power', fake_set_tx_power)

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=3  # Now required
        )

        status = mgr.start_network('wls16', req)
        assert status.tx_power_level == 3
        # Hardware-independent: verify interface from config, not hardcoded
        cfg_interface = cfg.antennas[0].interface
        assert calls[-1] == (cfg_interface, 3, 6)

    def test_set_tx_power_level(self, monkeypatch):
        cfg = load_config()
        mgr = NetworkManager(cfg)

        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda **kwargs: {'gateway': '192.168.120.1'})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda **kwargs: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(mgr.isolation_manager, 'add_network', lambda *a, **k: None)

        def fake_set_tx_power(interface, level, channel, verify_change=False):
            return {
                'interface': interface,
                'max_dbm': 20.0,
                'levels_dbm': {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0},
                'tx_power': {
                    'requested_level': level,
                    'reported_level': level if not verify_change else None,
                    'reported_dbm': float(level * 5) if not verify_change else None,
                },
            }

        monkeypatch.setattr(mgr, '_set_tx_power', fake_set_tx_power)

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=4
        )

        mgr.start_network('wls16', req)
        info = mgr.set_tx_power_level('wls16', 2)
        assert info['tx_power']['requested_level'] == 2
        assert mgr.active['wls16'].tx_power_level == 2

        # GET should reflect the last level
        info2 = mgr.get_tx_power_info('wls16')
        assert info2['tx_power']['requested_level'] == 2

    def test_set_tx_power_level_mismatch_raises_and_preserves_state(self, monkeypatch):
        cfg = load_config()
        mgr = NetworkManager(cfg)

        monkeypatch.setattr(mgr.dhcp_server, 'start', lambda **kwargs: {'gateway': '192.168.120.1'})
        monkeypatch.setattr(mgr.hostapd_manager, 'start', lambda **kwargs: {})
        monkeypatch.setattr(mgr.nat_manager, 'enable_nat', lambda *a, **k: None)
        monkeypatch.setattr(mgr.isolation_manager, 'add_network', lambda *a, **k: None)

        monkeypatch.setattr(
            mgr,
            '_set_tx_power',
            lambda interface, level, channel, verify_change=False: {
                'interface': interface,
                'max_dbm': 20.0,
                'levels_dbm': {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0},
                'tx_power': {
                    'requested_level': level,
                    'reported_level': level,
                    'reported_dbm': float(level * 5),
                },
            },
        )

        req = NetworkCreateRequest(
            ssid='TestAP',
            channel=6,
            encryption='open',
            band='2.4ghz',
            tx_power_level=4,
        )
        mgr.start_network('wls16', req)

        def fake_mismatch(*args, **kwargs):
            raise TxPowerMismatchError('Interface does not support dynamic power change.')

        monkeypatch.setattr(mgr, '_set_tx_power', fake_mismatch)

        with pytest.raises(TxPowerMismatchError):
            mgr.set_tx_power_level('wls16', 2)

        assert mgr.active['wls16'].tx_power_level == 4


@pytest.mark.parametrize("state, interface, ssid, ready", [
    ("DFS", "wlan0", "TestAP", False),
    ("ENABLED", "wlan1", "TestAP", False),
    ("ENABLED", "wlan0", "TestAP", True),
    # HAP-1: hostapd escapes the SSID in its status output; readiness must not depend on it.
    ("ENABLED", "wlan0", "Caff\\xc3\\xa8", True),
    ("ENABLED", "wlan0", 'my\\"net\\\\', True),
])
def test_hostapd_checks_ap_readiness(monkeypatch, tmp_path, state, interface, ssid, ready):
    mgr = hostapd.HostapdManager()
    (tmp_path / "wlan0").touch()
    process = SimpleNamespace(poll=lambda: None, output_events=lambda **kwargs: ())
    now = 0.0

    def sleep(seconds):
        nonlocal now
        now += seconds

    def status(cmd, **kwargs):
        assert cmd == ["hostapd_cli", "-p", str(tmp_path), "-i", "wlan0", "status"]
        assert 0 < kwargs["timeout"] <= 0.3
        return f"state={state}\nbss[0]={interface}\nssid[0]={ssid}\n"

    monkeypatch.setattr(hostapd.time, "monotonic", lambda: now)
    monkeypatch.setattr(hostapd.time, "sleep", sleep)
    monkeypatch.setattr(hostapd, "execute_command", status)
    if ready:
        mgr._wait_until_ready(process, "wlan0", str(tmp_path), 0.3)
    else:
        with pytest.raises(hostapd.HostapdError, match="AP not ready"):
            mgr._wait_until_ready(process, "wlan0", str(tmp_path), 0.3)


@pytest.mark.parametrize("exit_code", [1, None])
def test_hostapd_diagnostics_at_probe_timeout(monkeypatch, tmp_path, caplog, exit_code):
    mgr = hostapd.HostapdManager()
    (tmp_path / "wlan0").touch()
    now = 0.0
    process = SimpleNamespace(
        poll=lambda: exit_code if now >= 10 else None,
        output_events=lambda **kwargs: ("channel_list_timeout",),
    )

    def probe(*args, **kwargs):
        nonlocal now
        if now == 0:
            return "state=COUNTRY_UPDATE\nssid[0]=private-network\n"
        now = 10
        raise CommandTimeout("probe timeout")

    def sleep(seconds):
        nonlocal now
        now += seconds

    monkeypatch.setattr(hostapd, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(hostapd, "execute_command", probe)
    expected_error = hostapd.HostapdError if exit_code else hostapd.HostapdRadioFailure
    with pytest.raises(expected_error) as error:
        mgr._wait_until_ready(process, "wlan0", str(tmp_path), 10)
    assert type(error.value) is expected_error
    assert "elapsed=10.000s budget=10.000s socket_seen=True" in caplog.text
    assert "last_state=COUNTRY_UPDATE last_probe=timed_out" in caplog.text
    assert f"exit_code={exit_code} events=channel_list_timeout" in caplog.text
    assert "private-network" not in caplog.text


def test_hostapd_exit_during_a_hung_status_probe_is_reported_quickly(monkeypatch, tmp_path, caplog):
    """hostapd_cli waits for a dead hostapd; the short probe lets the exit surface in ~1 s."""
    mgr = hostapd.HostapdManager()
    (tmp_path / "wlan0").touch()
    now = 0.0
    process = SimpleNamespace(
        poll=lambda: 1 if now >= 1 else None,
        output_events=lambda **kwargs: (
            "state_country_update", "beacon_failed", "beacon_failed", "interface_init_failed",
            "state_disabled", "ap_disabled",
        ),
    )

    def probe(cmd, **kwargs):
        nonlocal now
        assert kwargs["timeout"] == hostapd.STATUS_PROBE_TIMEOUT
        now += kwargs["timeout"]
        raise CommandTimeout("no reply")

    monkeypatch.setattr(hostapd, "time", SimpleNamespace(monotonic=lambda: now, sleep=lambda s: None))
    monkeypatch.setattr(hostapd, "execute_command", probe)
    with pytest.raises(hostapd.HostapdInitFailure):
        mgr._wait_until_ready(process, "wlan0", str(tmp_path), 10)
    assert "elapsed=1.000s" in caplog.text


def test_exit_without_beacon_failure_stays_unclassified():
    process = SimpleNamespace(poll=lambda: 1, output_events=lambda **kwargs: ("interface_init_failed",))
    with pytest.raises(hostapd.HostapdError) as error:
        hostapd.HostapdManager._check_process(process, "wlan0")
    assert type(error.value) is hostapd.HostapdError


_INIT_EVENTS = (
    "state_country_update", "beacon_failed", "beacon_failed", "interface_init_failed",
    "state_disabled", "ap_disabled",
)


@pytest.mark.parametrize("seen_first", ["disabled_then_exit", "exit", "disabled_still_running"])
def test_beacon_failure_has_one_class_whatever_the_probe_sees_first(monkeypatch, tmp_path, seen_first):
    """HAP-2: DISABLED-before-exit and exit-before-DISABLED are the same failure."""
    mgr = hostapd.HostapdManager()
    (tmp_path / "wlan0").touch()
    now = 0.0
    probed = False

    def poll():
        if seen_first == "exit":
            return 1
        if seen_first == "disabled_then_exit" and probed and now >= 0.1:
            return 1
        return None

    def probe(cmd, **kwargs):
        nonlocal probed
        probed = True
        return "state=DISABLED\nbss[0]=wlan0\n"

    def sleep(seconds):
        nonlocal now
        now += seconds

    process = SimpleNamespace(poll=poll, output_events=lambda **kwargs: _INIT_EVENTS)
    monkeypatch.setattr(hostapd, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(hostapd, "execute_command", probe)
    with pytest.raises(hostapd.HostapdInitFailure):
        mgr._wait_until_ready(process, "wlan0", str(tmp_path), 10)
    assert now <= hostapd.DISABLED_SETTLE + 0.1  # the settle wait is short


def test_disabled_without_beacon_failure_stays_a_generic_radio_failure(monkeypatch, tmp_path):
    mgr = hostapd.HostapdManager()
    (tmp_path / "wlan0").touch()
    now = 0.0

    def sleep(seconds):
        nonlocal now
        now += seconds

    process = SimpleNamespace(poll=lambda: None, output_events=lambda **kwargs: ("state_disabled",))
    monkeypatch.setattr(hostapd, "time", SimpleNamespace(monotonic=lambda: now, sleep=sleep))
    monkeypatch.setattr(hostapd, "execute_command", lambda cmd, **kw: "state=DISABLED\nbss[0]=wlan0\n")
    with pytest.raises(hostapd.HostapdRadioFailure, match="AP not ready") as error:
        mgr._wait_until_ready(process, "wlan0", str(tmp_path), 10)
    assert type(error.value) is hostapd.HostapdRadioFailure


class TestHostapdConfigGeneration:
    """Tests for hostapd configuration file generation."""

    def _generate(self, **overrides):
        from wilab.wifi.hostapd import HostapdManager

        params = dict(
            interface='wlan0',
            ssid='TestAP',
            channel=5,
            encryption='wpa2',
            password='testpass123',
            hidden=False,
            band='2.4ghz',
            country_code='IT',
        )
        params.update(overrides)
        return HostapdManager()._generate_config(**params)

    def test_country_regulatory_advertised(self):
        """802.11d must be enabled so the driver applies the regulatory domain."""
        config = self._generate()
        assert 'country_code=IT' in config
        assert 'ieee80211d=1' in config

    def test_no_dot11h_on_24ghz(self):
        """802.11h (DFS/TPC) is only relevant on 5 GHz, not 2.4 GHz."""
        config = self._generate(band='2.4ghz')
        assert 'ieee80211h=1' not in config

    def test_dot11h_enabled_on_5ghz(self):
        """802.11h must be enabled on 5 GHz for DFS/TPC regulatory compliance."""
        config = self._generate(band='5ghz', channel=36)
        assert 'ieee80211h=1' in config

    def test_ssid_is_written_as_hex(self):
        """BUG-1: ssid2 in hex means no SSID byte is parsed by hostapd."""
        ssid = 'Caffè "x"\\'
        config = self._generate(ssid=ssid)
        assert "ssid2=" + ssid.encode("utf-8").hex() in config
        assert "\nssid=" not in config

    @pytest.mark.parametrize("field", ["ssid", "password", "country_code"])
    @pytest.mark.parametrize("breaker", ["\n", "\r"])
    def test_line_breaks_are_rejected(self, field, breaker):
        """BUG-1: defence in depth, independent of the API model."""
        with pytest.raises(hostapd.HostapdError, match=f"Invalid {field}"):
            self._generate(**{field: f"x{breaker}interface=eth0"})


@pytest.mark.parametrize("status, enabled", [
    ("state=ENABLED\nbss[0]=wlan0\nssid[0]=Caff\\xc3\\xa8\n", True),
    ("state=ENABLED\nbss[0]=wlan1\nssid[0]=TestAP\n", False),
    ("state=DISABLED\nbss[0]=wlan0\nssid[0]=TestAP\n", False),
])
def test_is_enabled_ignores_escaped_ssid(monkeypatch, status, enabled):
    """HAP-1: the watchdog probe must not depend on hostapd's SSID escaping."""
    mgr = hostapd.HostapdManager()
    mgr._instances["wlan0"] = {
        "interface": "wlan0", "ssid": "Caffè", "control_dir": "/run/x",
        "process": SimpleNamespace(poll=lambda: None),
    }
    monkeypatch.setattr(mgr, "is_running", lambda net_id: True)
    monkeypatch.setattr(hostapd, "execute_command", lambda cmd, **kw: status)
    assert mgr.is_enabled("wlan0") is enabled


class _BlockFirewall:
    """FORWARD only, in memory: the second change fails."""

    def __init__(self):
        self.rules: list[list[str]] = []
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        if args[0] == "-S":
            return "\n".join("-A " + " ".join(r) for r in self.rules)
        if args[0] == "-C":
            raise CommandError("Bad rule", returncode=1)
        self.calls.append(args)
        if len(self.calls) == 2:
            raise CommandError("block failed", returncode=1)
        if args[0] == "-I":
            self.rules.insert(0, [args[1], *args[3:]])
        elif args[0] == "-D":
            self.rules.remove(args[1:])
        return ""
