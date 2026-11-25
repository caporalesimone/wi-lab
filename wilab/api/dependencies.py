import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, Path

from .. import heartbeat
from ..config import AppConfig, NetworkEntry, load_config, scan_new_networks
from ..network.commands import CommandError
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from ..network.unmanaged import exclude_from_host_managers
from ..reservation import Reservation, ReservationManager
from ..wifi.channels import ChannelManager
from ..wifi.interface import reset_interface
from ..wifi.manager import NetworkManager
from .errors import GONE_REASONS

logger = logging.getLogger(__name__)

_config: AppConfig | None = None
_manager: NetworkManager | None = None
_reservation_manager: ReservationManager | None = None
_channel_manager: ChannelManager | None = None
_qos_manager: QosManager | None = None
_qos_profile_manager: QosProfileManager | None = None
_singleton_lock = threading.RLock()

def get_config() -> AppConfig:
    global _config
    with _singleton_lock:
        if _config is None:
            _config = load_config()
        return _config

def get_manager(config: AppConfig = Depends(get_config)) -> NetworkManager:
    global _manager
    with _singleton_lock:
        if _manager is None:
            manager = NetworkManager(config, channel_manager=get_channel_manager())
            manager.qos_manager = get_qos_manager()
            manager.qos_profile_manager = get_qos_profile_manager()
            _manager = manager
        return _manager

def get_reservation_manager(config: AppConfig = Depends(get_config)) -> ReservationManager:
    global _reservation_manager
    with _singleton_lock:
        if _reservation_manager is None:
            device_ids = [n.device_id for n in config.antennas]
            manager = get_manager(config)
            _reservation_manager = ReservationManager(
                device_ids, cleanup=manager.release_device, device_lock=manager.device_lock,
                cleanup_due=manager.cleanup_due, cleanup_wait=manager.cleanup_wait,
                before_release=manager.cancel_start,
            )
            manager.expire_reservations = _reservation_manager.expire
            manager.watchdog.start(_reservation_manager)
            manager.recovery.start_reprobe(_reservation_manager)
        return _reservation_manager


ReservationManagerDep = Annotated[ReservationManager, Depends(get_reservation_manager)]

_scan_lock = threading.Lock()
DISCOVERY_FAST_INTERVAL = 5.0
DISCOVERY_SLOW_INTERVAL = 30.0


def scan_devices(config: AppConfig, *, quiet: bool = False) -> list[NetworkEntry]:
    """Add newly found Wi-Fi interfaces to the allocatable pool."""
    with _scan_lock:
        reservations = get_reservation_manager(config)
        added = scan_new_networks(config, quiet=quiet)
        if not added:
            return []
        # Appending preserves the order used for subnet allocation.
        config.antennas = [*config.antennas, *added]
        exclude_from_host_managers(n.interface for n in config.antennas)
        reservations.add_devices([n.device_id for n in added])
        manager = get_manager(config)
        for net in added:
            # Clean what a previous run left on the radio (STAB-4); nobody uses it yet.
            with manager.device_lock(net.device_id):
                reset_interface(net.interface)
        manager.watchdog.watch([n.device_id for n in added])
        for net in added:
            logger.info(
                "Added %s as %r (%s)", net.interface, net.display_name,
                f"USB port {net.usb_recovery_port}" if net.usb_recovery_port else "non-USB",
            )
        channels = get_channel_manager()
        threading.Thread(
            target=_warm_channels, args=(channels, [n.interface for n in added]),
            name="channel-cache-scan", daemon=True,
        ).start()
        return added


def discovery_loop(config: AppConfig, stop: threading.Event) -> None:
    """Add antennas for the whole service lifetime.

    The first scan runs immediately. Scans repeat every 5 s while no antenna is
    managed, then every 30 s. Only the first scan logs configuration warnings.
    """
    interval = 0.0
    first = True
    searching: bool | None = None
    last_error: str | None = None
    while not stop.wait(interval):
        heartbeat.beat("discovery")
        try:
            scan_devices(config, quiet=not first)
        except Exception as exc:  # this loop must survive anything (WD-9)
            if str(exc) != last_error:
                logger.exception("Device discovery failed")
            last_error = str(exc)
        else:
            last_error = None
        first = False
        if searching != (not config.antennas):
            searching = not config.antennas
            if searching:
                logger.warning(
                    "No Wi-Fi adapter available; discovery runs every %.0f s", DISCOVERY_FAST_INTERVAL,
                )
            else:
                logger.info(
                    "%d Wi-Fi adapter(s) managed; discovery runs every %.0f s",
                    len(config.antennas), DISCOVERY_SLOW_INTERVAL,
                )
        interval = DISCOVERY_FAST_INTERVAL if searching else DISCOVERY_SLOW_INTERVAL


def _warm_channels(channels: ChannelManager, interfaces: list[str]) -> None:
    for interface in interfaces:
        try:
            channels.get_channels(interface)
        except (CommandError, ValueError) as exc:
            logger.warning("Failed to cache channels for %s: %s", interface, exc)


def get_channel_manager() -> ChannelManager:
    global _channel_manager
    with _singleton_lock:
        if _channel_manager is None:
            # Read through get_config(): discovery replaces `antennas` as it adds radios.
            _channel_manager = ChannelManager(show_dfs=lambda interface: get_config().show_dfs_for(interface))
        return _channel_manager


def get_qos_manager() -> QosManager:
    global _qos_manager
    with _singleton_lock:
        if _qos_manager is None:
            _qos_manager = QosManager()
        return _qos_manager


def get_qos_profile_manager() -> QosProfileManager:
    global _qos_profile_manager
    with _singleton_lock:
        if _qos_profile_manager is None:
            from pathlib import Path as _Path
            catalogue_dir = str(
                _Path(__file__).resolve().parent.parent / "data" / "qos-profiles"
            )
            _qos_profile_manager = QosProfileManager(catalogue_dir)
        return _qos_profile_manager




def reservation_gone(mgr: ReservationManager, reservation_id: str) -> HTTPException:
    """404 whose stable `reason` says why the ID is no longer valid (contract)."""
    reason = mgr.ended_reason(reservation_id)
    return HTTPException(status_code=404, detail={
        "code": 404, "reason": reason, "message": f"Reservation {GONE_REASONS[reason]}",
    })


def resolve_reservation(
    reservation_id: str = Path(..., description="Reservation token"),
    mgr: ReservationManager = Depends(get_reservation_manager),
) -> Reservation:
    """Validate reservation_id and return the active Reservation.

    Raises 404 if the token is unknown, expired, or already released.
    """
    r = mgr.get(reservation_id)
    if r is None:
        raise reservation_gone(mgr, reservation_id)
    return r


# Longest wait for another operation on the same device before answering
# 503 / 1006 device_busy (RACE-1). A start holds the device up to 20 s, 75 s on DFS.
DEVICE_BUSY_TIMEOUT = 5.0


@contextmanager
def hold_reservation(
    mgr: ReservationManager, reservation: Reservation, *, wait: bool = False,
) -> Iterator[None]:
    """Hold the reservation's device.

    Raises `DeviceBusyError` after `DEVICE_BUSY_TIMEOUT` seconds, or waits until
    the device is free with `wait=True`.
    """
    timeout = None if wait else DEVICE_BUSY_TIMEOUT
    with mgr.hold(reservation.reservation_id, timeout=timeout) as current:
        if current is not reservation:
            raise reservation_gone(mgr, reservation.reservation_id)
        yield
