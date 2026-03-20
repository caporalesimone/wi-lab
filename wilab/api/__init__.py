from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi

from .dependencies import get_config, get_manager
from .routes import router as api_router
from ..version import __version__

logger = logging.getLogger(__name__)


def _candidate_frontend_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    return [
        project_root / "frontend" / "dist" / "wi-lab-frontend" / "browser",  # Docker build output (preferred)
#        Path("/opt/wilab-frontend"),  # System install location used previously
#        project_root / "wilab-frontend",  # Local sibling folder
#        Path.home() / "wi-lab" / "wilab-frontend",  # User home
#        Path("/root/wi-lab/wilab-frontend"),  # Root home (service as root)
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: instantiate manager so background expiry runs
    cfg = get_config()
    get_manager(cfg)
    yield
    # Shutdown: gracefully stop any active networks
    try:
        mgr = get_manager(cfg)
        mgr.shutdown_all()
    except Exception:
        # Ignore shutdown errors to not block app teardown
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="Wi-Lab", version=__version__, lifespan=lifespan)

    # Configure CORS if origins are specified in config
    config = get_config()
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logger.info(f"CORS enabled for origins: {config.cors_origins}")
    else:
        logger.info("CORS disabled (no cors_origins configured)")

    # Include API router
    app.include_router(api_router)

    # Serve static files (frontend) if directory exists
    frontend_candidates = _candidate_frontend_paths()
    frontend_path = next((path for path in frontend_candidates if path.is_dir()), None)

    if frontend_path:
        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = frontend_path / "index.html"
            if index_path.is_file():
                return FileResponse(index_path)
            return {"error": "Frontend index.html not found"}

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str):
            if (
                full_path.startswith("api/")
                or full_path == "docs"
                or full_path.startswith("docs/")
                or full_path == "openapi.json"
            ):
                return None

            file_path = frontend_path / full_path
            if file_path.is_file():
                return FileResponse(file_path)

            index_path = frontend_path / "index.html"
            if index_path.is_file():
                return FileResponse(index_path)
            return {"error": "Frontend not found"}

        logger.info(f"Frontend static files served from {frontend_path}")
    else:
        tried = ", ".join(str(path) for path in frontend_candidates)
        logger.warning(f"Frontend directory not found. Tried: {tried}. Skipping static file serving.")

    # Inject examples for OpenAPI/Swagger documentation
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            description=app.description,
        )
        try:
            paths = openapi_schema.get("paths", {})
            
            # POST /interface/{net_id}/network example
            post_route = paths.get("/api/v1/interface/{net_id}/network", {}).get("post", {})
            content = post_route.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                content["application/json"]["example"] = {
                    "ssid": "TestNetwork",
                    "channel": 5,
                    "password": "testpass123",
                    "encryption": "wpa2",
                    "band": "2.4ghz",
                    "tx_power_level": 4,
                    "timeout": 3600,
                    "internet_enabled": True,
                }
            
            # POST /interface/{net_id}/txpower example
            txpower_post = paths.get("/api/v1/interface/{net_id}/txpower", {}).get("post", {})
            txpower_content = txpower_post.get("requestBody", {}).get("content", {})
            if "application/json" in txpower_content:
                txpower_content["application/json"]["example"] = {
                    "level": 2
                }

            # GET /interface/{net_id}/network response example
            network_get = paths.get("/api/v1/interface/{net_id}/network", {}).get("get", {})
            network_responses = network_get.get("responses", {})
            network_200 = network_responses.get("200", {})
            network_200_content = network_200.get("content", {})
            if "application/json" in network_200_content:
                network_200_content["application/json"]["example"] = {
                    "net_id": "ap-01",
                    "interface": "wlxbc071dc527d6",
                    "active": True,
                    "ssid": "test-network-ap-01",
                    "channel": 6,
                    "password": "12345678",
                    "encryption": "wpa2",
                    "band": "2.4ghz",
                    "hidden": False,
                    "subnet": "192.168.120.0/24",
                    "internet_enabled": True,
                    "tx_power": {
                        "requested_level": 4,
                        "reported_level": 4,
                        "reported_dbm": 20.0,
                    },
                    "expires_at": "2026-03-20 19:33:46",
                    "expires_in": 3471,
                    "dhcp": {
                        "interface": "wlxbc071dc527d6",
                        "subnet": "192.168.120.0/24",
                        "gateway": "192.168.120.1",
                        "config_file": "/tmp/wilab-dnsmasq/dnsmasq-ap-01.conf",
                        "pid_file": "/tmp/wilab-dnsmasq/pids/dnsmasq-ap-01.pid",
                        "lease_file": "/tmp/wilab-dnsmasq/leases-ap-01.db",
                        "network_addr": "192.168.120.0",
                        "dhcp_range": "192.168.120.10,192.168.120.250",
                    },
                    "clients_connected": 2,
                    "clients": [
                        {"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.120.10"},
                        {"mac": "aa:bb:cc:dd:ee:02", "ip": "192.168.120.11"},
                    ],
                }
            
            # GET /interface/{net_id}/txpower response example
            txpower_get = paths.get("/api/v1/interface/{net_id}/txpower", {}).get("get", {})
            txpower_responses = txpower_get.get("responses", {})
            txpower_200 = txpower_responses.get("200", {})
            txpower_200_content = txpower_200.get("content", {})
            if "application/json" in txpower_200_content:
                txpower_200_content["application/json"]["example"] = {
                    "net_id": "ap-01",
                    "interface": "wlx782051245264",
                    "max_dbm": 20.0,
                    "levels_dbm": {
                        "1": 5.0,
                        "2": 10.0,
                        "3": 15.0,
                        "4": 20.0
                    },
                    "tx_power": {
                        "requested_level": 1,
                        "reported_level": 1,
                        "reported_dbm": 0.0
                    }
                }
        except Exception:
            # If schema structure changes, skip injection silently
            pass

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app
