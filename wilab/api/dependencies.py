from fastapi import Depends
from ..config import AppConfig, load_config
from ..wifi.manager import NetworkManager

_config: AppConfig | None = None
_manager: NetworkManager | None = None

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
