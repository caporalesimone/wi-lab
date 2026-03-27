from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc_parts = [str(part) for part in first.get("loc", []) if part not in ("body", "query", "path")]
            msg = first.get("msg", "Request validation failed")
            detail = f"{': '.join(loc_parts)}: {msg}" if loc_parts else msg
        else:
            detail = "Request validation failed"
        return JSONResponse(status_code=422, content={"detail": detail})

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
            
            # POST /interface/{reservation_id}/network example
            post_route = paths.get("/api/v1/interface/{reservation_id}/network", {}).get("post", {})
            content = post_route.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                content["application/json"]["example"] = {
                    "ssid": "TestNetwork",
                    "channel": 5,
                    "password": "testpass123",
                    "encryption": "wpa2",
                    "band": "2.4ghz",
                    "tx_power_level": 4,
                    "internet_enabled": True,
                }
            
            # POST /interface/{reservation_id}/txpower example
            txpower_post = paths.get("/api/v1/interface/{reservation_id}/txpower", {}).get("post", {})
            txpower_content = txpower_post.get("requestBody", {}).get("content", {})
            if "application/json" in txpower_content:
                txpower_content["application/json"]["example"] = {
                    "level": 2
                }

            txpower_post_responses = txpower_post.get("responses", {})
            txpower_post_200 = txpower_post_responses.get("200", {})
            txpower_post_200_content = txpower_post_200.get("content", {})
            if "application/json" in txpower_post_200_content:
                txpower_post_200_content["application/json"]["example"] = {
                    "device_id": "wls16",
                    "interface": "wls16",
                    "max_dbm": 20.0,
                    "levels_dbm": {
                        "1": 5.0,
                        "2": 10.0,
                        "3": 15.0,
                        "4": 20.0,
                    },
                    "tx_power": {
                        "requested_level": 2,
                        "reported_level": 2,
                        "reported_dbm": 10.0,
                    },
                }

            txpower_post_422 = txpower_post_responses.get("422", {})
            txpower_post_422_content = txpower_post_422.setdefault("content", {})
            txpower_post_422_json = txpower_post_422_content.setdefault("application/json", {})
            txpower_post_422_json["examples"] = {
                "out_of_range": {
                    "summary": "Requested level is outside 1-4",
                    "value": {"detail": "Requested power out of range. Valid values are 1, 2, 3, 4."},
                },
                "hardware_mismatch": {
                    "summary": "Hardware does not apply requested TX power",
                    "value": {"detail": "Interface does not support dynamic power change."},
                },
            }

            # GET /interface/{reservation_id}/network response example
            network_get = paths.get("/api/v1/interface/{reservation_id}/network", {}).get("get", {})
            network_responses = network_get.get("responses", {})
            network_200 = network_responses.get("200", {})
            network_200_content = network_200.get("content", {})
            if "application/json" in network_200_content:
                network_200_content["application/json"]["example"] = {
                    "device_id": "wls16",
                    "interface": "wls16",
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
            
            # GET /interface/{reservation_id}/txpower response example
            txpower_get = paths.get("/api/v1/interface/{reservation_id}/txpower", {}).get("get", {})
            txpower_responses = txpower_get.get("responses", {})
            txpower_200 = txpower_responses.get("200", {})
            txpower_200_content = txpower_200.get("content", {})
            if "application/json" in txpower_200_content:
                txpower_200_content["application/json"]["example"] = {
                    "device_id": "wls16",
                    "interface": "wls16",
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

            # Normalize all documented 422 responses to a compact payload schema.
            simple_422_schema = {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                },
                "required": ["detail"],
            }
            for path_item in paths.values():
                for operation in path_item.values():
                    if not isinstance(operation, dict):
                        continue
                    responses = operation.get("responses", {})
                    response_422 = responses.get("422")
                    if not isinstance(response_422, dict):
                        continue

                    response_422["description"] = response_422.get("description") or "Validation error"
                    response_422_content = response_422.setdefault("content", {})
                    response_422_json = response_422_content.setdefault("application/json", {})
                    response_422_json["schema"] = simple_422_schema
                    if "examples" not in response_422_json:
                        response_422_json["example"] = {"detail": "field_name: validation error"}

            # Ensure built-in FastAPI validation schemas are also compact when referenced.
            components = openapi_schema.setdefault("components", {})
            schemas = components.setdefault("schemas", {})
            schemas["HTTPValidationError"] = simple_422_schema
            schemas["ValidationError"] = simple_422_schema
        except Exception:
            # If schema structure changes, skip injection silently
            pass

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app
