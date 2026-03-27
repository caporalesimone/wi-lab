from fastapi import Depends
from ..config import AppConfig, load_config
from ..wifi.manager import NetworkManager
from ..reservation import ReservationManager

_config: AppConfig | None = None
_manager: NetworkManager | None = None
_reservation_manager: ReservationManager | None = None

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
