"""API route organization by semantic domain.

This package splits Wi-Lab API routes into semantic groups:
- health: System health checks and service status
- antennas: the managed radios and the options a network on each can use
- network: WiFi network CRUD (start/stop/query) and client enumeration
- internet: NAT/Internet connectivity management
- txpower: Transmit power control
- qos_profile: QoS profile catalogue and per-reservation profile control

All routes are prefixed with /api/v1.
"""

from fastapi import APIRouter

from .antennas import router as antennas_router
from .internet import router as internet_router
from .network import router as network_router
from .qos_profile import catalogue_router as qos_catalogue_router
from .qos_profile import reservation_router as qos_reservation_router
from .reservation import maintenance_router as reservation_maintenance_router
from .reservation import router as reservation_router
from .status import maintenance_router as debug_router
from .status import router as health_router
from .txpower import router as txpower_router

# Root router at /api/v1 prefix
router = APIRouter(prefix="/api/v1")

# Include all domain routers. Release-all comes before the reservation routes so
# that DELETE /reservations/all is not read as a reservation ID.
router.include_router(reservation_maintenance_router)
router.include_router(reservation_router)
router.include_router(health_router)
router.include_router(debug_router)
router.include_router(antennas_router)
router.include_router(network_router)
router.include_router(internet_router)
router.include_router(txpower_router)
router.include_router(qos_catalogue_router)
router.include_router(qos_reservation_router)
