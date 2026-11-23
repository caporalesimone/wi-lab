"""HAP-3: a startup failure is classified by its exception, not by the attempt number."""

from unittest.mock import Mock

import pytest

from wilab.config import load_config
from wilab.models import NetworkCreateRequest
from wilab.wifi import manager as manager_module
from wilab.wifi.hostapd import HostapdError, HostapdInitFailure, HostapdRadioFailure
from wilab.wifi.manager import NetworkManager, StartupFailure


def _request() -> NetworkCreateRequest:
    return NetworkCreateRequest(ssid="cls", channel=6, encryption="open", band="2.4ghz", tx_power_level=4)


@pytest.fixture
def manager(monkeypatch) -> NetworkManager:
    mgr = NetworkManager(load_config())
    monkeypatch.setattr(manager_module, "STARTUP_RETRY_DELAY", 0.0)
    monkeypatch.setattr(mgr.dhcp_server, "start", Mock(return_value={}))
    monkeypatch.setattr(mgr.dhcp_server, "stop", Mock())
    monkeypatch.setattr(mgr.hostapd_manager, "stop", Mock())
    return mgr


def _init_failure() -> HostapdInitFailure:
    return HostapdInitFailure("hostapd exited with code 1 on wlan0: beacon setup failed")


def test_init_failure_is_a_radio_failure() -> None:
    assert issubclass(HostapdInitFailure, HostapdRadioFailure)


@pytest.mark.parametrize("allow_internal_retry", [True, False])
def test_init_failure_is_radio_on_every_request(monkeypatch, manager, allow_internal_retry) -> None:
    """The second and third create of a sequence (no internal retry) and the
    watchdog restart got a generic 500 for the same failure the first create
    reported as 409 / 1001."""
    device = manager.config.networks[0].device_id
    start = Mock(side_effect=_init_failure())
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=allow_internal_retry)
    assert failure.value.radio and not failure.value.cleanup_failed
    assert start.call_count == (3 if allow_internal_retry else 1)


def test_unclassified_hostapd_error_is_not_radio(monkeypatch, manager) -> None:
    device = manager.config.networks[0].device_id
    start = Mock(side_effect=HostapdError("hostapd exited with code 1 on wlan0"))
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert not failure.value.radio
    assert start.call_count == 1  # not retried


def test_retry_after_a_radio_failure_keeps_the_classification(monkeypatch, manager) -> None:
    """An unclassified exit on the retry still follows a radio failure of this request."""
    device = manager.config.networks[0].device_id
    start = Mock(side_effect=[_init_failure(), HostapdError("hostapd exited with code 1 on wlan0")])
    monkeypatch.setattr(manager.hostapd_manager, "start", start)
    with pytest.raises(StartupFailure) as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert failure.value.radio
    assert start.call_count == 2


def test_non_ap_stage_after_a_radio_retry_is_not_radio(monkeypatch, manager) -> None:
    """A DHCP failure after the AP came up on the retry is not a radio failure."""
    from wilab.network.dhcp import DhcpServerError

    device = manager.config.networks[0].device_id
    monkeypatch.setattr(manager.hostapd_manager, "start", Mock(side_effect=[_init_failure(), None]))
    monkeypatch.setattr(manager.dhcp_server, "start", Mock(side_effect=DhcpServerError("port 67 in use")))
    with pytest.raises(StartupFailure, match="configure DHCP") as failure:
        manager.start_network(device, _request(), allow_internal_retry=True)
    assert not failure.value.radio
