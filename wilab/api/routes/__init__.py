"""API route organization by semantic domain.

This package splits Wi-Lab API routes into semantic groups:
- health: System health checks and service status
- antennas: the managed radios and the options a network on each can use
- network: WiFi network CRUD (start/stop/query) and client enumeration
- internet: NAT/Internet connectivity management
- txpower: Transmit power control
- qos_profile: QoS profile catalogue and per-reservation profile control

All routes are prefixed with API_PREFIX (/api/v2). /api/v1 was removed in 4.0.0.
"""

from fastapi import APIRouter

from .antennas import router as antennas_router
from .internet import router as internet_router
from .network import router as network_router
from .qos_profile import catalogue_router as qos_catalogue_router
from .qos_profile import reservation_router as qos_reservation_router
from .reservation import maintenance_router as reservation_maintenance_router
from .reservation import router as reservation_router
from .status import router as health_router
from .txpower import router as txpower_router

# Every route is under API_PREFIX. Wi-Lab 4.0.0 changed the contract, so the prefix
# went from /api/v1 to /api/v2; /api/v1 is not kept and answers 404.
API_PREFIX = "/api/v2"
router = APIRouter(prefix=API_PREFIX)


def is_api_path(path: str) -> bool:
    """Any path under /api/ (also a removed version): answered with JSON errors, never the frontend."""
    return path == "/api" or path.startswith("/api/")

# Include all domain routers. Release-all comes before the reservation routes so
# that DELETE /reservations/all is not read as a reservation ID.
router.include_router(reservation_maintenance_router)
router.include_router(reservation_router)
router.include_router(health_router)
router.include_router(antennas_router)
router.include_router(network_router)
router.include_router(internet_router)
router.include_router(txpower_router)
router.include_router(qos_catalogue_router)
router.include_router(qos_reservation_router)
