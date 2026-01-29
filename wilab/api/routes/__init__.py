"""API route organization by semantic domain.

This package splits Wi-Lab API routes into semantic groups:
- health: System health checks, service status, interface listing
- network: WiFi network CRUD (start/stop/query) and client enumeration
- internet: NAT/Internet connectivity management
- txpower: Transmit power control

All routes are prefixed with /api/v1.
"""

from fastapi import APIRouter

from .status import router as health_router
from .network import router as network_router
from .internet import router as internet_router
from .txpower import router as txpower_router

# Root router at /api/v1 prefix
router = APIRouter(prefix="/api/v1")

# Include all domain routers
router.include_router(health_router)
router.include_router(network_router)
router.include_router(internet_router)
router.include_router(txpower_router)
