from fastapi import Depends, HTTPException, Path
from ..config import AppConfig, load_config
from ..wifi.manager import NetworkManager
from ..wifi.channels import ChannelManager
from ..reservation import ReservationManager, Reservation
from ..network.qos import QosManager

_config: AppConfig | None = None
_manager: NetworkManager | None = None
_reservation_manager: ReservationManager | None = None
_channel_manager: ChannelManager | None = None
_qos_manager: QosManager | None = None

def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config

def get_manager(config: AppConfig = Depends(get_config)) -> NetworkManager:
    global _manager
    if _manager is None:
        _manager = NetworkManager(config)
    return _manager

def get_reservation_manager(config: AppConfig = Depends(get_config)) -> ReservationManager:
    global _reservation_manager
    if _reservation_manager is None:
        device_ids = [n.device_id for n in config.networks]
        _reservation_manager = ReservationManager(device_ids)
    return _reservation_manager


def get_channel_manager() -> ChannelManager:
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager


def get_qos_manager() -> QosManager:
    global _qos_manager
    if _qos_manager is None:
        _qos_manager = QosManager()
    return _qos_manager


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
