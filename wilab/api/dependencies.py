from fastapi import Depends, HTTPException, Path
import threading
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Annotated
from ..config import AppConfig, load_config
from ..wifi.manager import NetworkManager
from ..wifi.channels import ChannelManager
from ..reservation import ReservationManager, Reservation
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager

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
            manager = NetworkManager(config)
            manager.qos_manager = get_qos_manager()
            manager.qos_profile_manager = get_qos_profile_manager()
            _manager = manager
        return _manager

def get_reservation_manager(config: AppConfig = Depends(get_config)) -> ReservationManager:
    global _reservation_manager
    with _singleton_lock:
        if _reservation_manager is None:
            device_ids = [n.device_id for n in config.networks]
            manager = get_manager(config)
            _reservation_manager = ReservationManager(
                device_ids, cleanup=manager.release_device, device_lock=manager.device_lock
            )
            manager.expire_reservations = _reservation_manager.expire
            manager.watchdog.start(_reservation_manager)
        return _reservation_manager


ReservationManagerDep = Annotated[ReservationManager, Depends(get_reservation_manager)]


def get_channel_manager() -> ChannelManager:
    global _channel_manager
    with _singleton_lock:
        if _channel_manager is None:
            _channel_manager = ChannelManager()
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


def resolve_reservation(
    reservation_id: str = Path(..., description="Reservation token"),
    mgr: ReservationManager = Depends(get_reservation_manager),
) -> Reservation:
    """Validate reservation_id and return the active Reservation.

    Raises 404 if the token is unknown, expired, or already released.
    """
    r = mgr.get(reservation_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Reservation not found or expired")
    return r


@contextmanager
def hold_reservation(
    mgr: ReservationManager, reservation: Reservation
) -> Iterator[None]:
    with mgr.hold(reservation.reservation_id) as current:
        if current is not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found or expired")
        yield
