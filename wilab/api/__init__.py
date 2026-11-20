import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..network.captive import remove_stale_captive_rules
from ..reservation import ReservationCleanupError
from ..version import __version__
from ..wifi.channels import set_regulatory_domain
from .dependencies import discovery_loop, get_config, get_manager
from .errors import ApiErrorCode, api_error_response, document_errors, domain_error
from .routes import router as api_router

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
## Reservation and network lifecycle

Authenticate with a Bearer token. Reserve an adapter with
`POST /api/v1/device-reservation` (for example `{"duration_seconds": 120}`),
then pass the returned `reservation_id` to the network endpoints. Use one
creation request at a time per reservation. Release with
`DELETE /api/v1/device-reservation/{reservation_id}` when finished; this also
stops the network. A failed cleanup can return `503` and keep the device held.

Every API error body has a `detail` object with an integer `code` and a
stable `reason`. Generic errors use the HTTP status as their code and
include a human-readable `message`. Use the HTTP status and `detail.code`,
not the message, for control flow. Success responses are unchanged.

| Operation and response | Client action |
|---|---|
| Create `409`, `detail.code: 1001` | Repeat the same POST with the same ID and body after `Retry-After` seconds (5 then 10). Early calls do not use up an attempt. Expiry is unchanged. |
| Create `409` without `1001` | Do not blindly retry. Check network status for an active AP or a watchdog restoration. |
| Create `500`, `detail.code: 1003`, `reservation_invalidated: true` | Discard the ID. Do not retry creation or release it. Request a new reservation if needed. |
| Create generic `500` | No automatic retry. The reservation is still valid; release it if no longer needed. |
| Reserve `409`, `detail.code: 1005` | Ordinary contention. Use `detail.next_available_in` as an estimate, not a guarantee. |
| Reserve `503`, `detail.code: 1002` | Retry the **reservation** POST after `Retry-After` (10 seconds, a polling interval). |
| Reserve `503`, `detail.code: 1003` | All adapters are quarantined and none is recovering. No automatic retry. |
| `503`, `detail.code: 1004` | Cleanup failed. Do not apply a recovery-code retry policy; check status and resolve the cleanup failure. |

A transport timeout is not a recovery code. For a lost create response, check
`GET /api/v1/interface/{reservation_id}/network` before attempting another
create. A lost reservation response may already have allocated an adapter:
do not blindly repeat it. A `404` for a reservation ID means stop using it.

`GET /api/v1/status` distinguishes quarantined adapters (`recovery_state`)
from reserved networks being repaired (`runtime_state`). `reserved: false`
does not make a quarantined adapter allocatable. During
`restoring_ap` or `restoring_dhcp`, poll status instead of sending a new
create. `dhcp_failed` means the AP may still be up, but new clients may not
receive an address.
"""

OPENAPI_TAGS = [
    {"name": "System", "description": "Service health, reservations and per-adapter recovery state. Poll status, not debug."},
    {"name": "Reservation", "description": "Allocate or release an adapter. Use the returned reservation ID for device operations."},
    {"name": "Network", "description": "Create, stop and inspect an AP. The creation response describes when to retry with the same reservation."},
    {"name": "Internet", "description": "Enable or disable Internet access for a reserved network."},
    {"name": "TX Power", "description": "Inspect or request transmit power. Hardware support is not guaranteed."},
    {"name": "QoS Profiles", "description": "Inspect and manage traffic shaping profiles for a reserved network."},
]


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
    manager = get_manager(cfg)
    manager.nat_manager.remove_stale_rules()
    remove_stale_captive_rules()

    # Set regulatory domain before any channel query
    set_regulatory_domain(cfg.country_code)

    # Antennas are added by discovery; their channel cache is warmed when added.
    stop_discovery = threading.Event()
    discovery_thread = threading.Thread(
        target=discovery_loop, args=(cfg, stop_discovery),
        name="device-discovery", daemon=True,
    )
    discovery_thread.start()

    yield

    stop_discovery.set()
    discovery_thread.join(timeout=10)
    # Shutdown: gracefully stop any active networks
    try:
        mgr = get_manager(cfg)
        mgr.shutdown_all()
    except Exception:
        # Ignore shutdown errors to not block app teardown
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wi-Lab", version=__version__, lifespan=lifespan,
        description=API_DESCRIPTION, openapi_tags=OPENAPI_TAGS,
    )

    @app.exception_handler(StarletteHTTPException)
    async def api_http_exception(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if not (path == "/api/v1" or path.startswith("/api/v1/")) or exc.status_code < 400:
            return await http_exception_handler(request, exc)
        return api_error_response(request, exc.status_code, exc.detail, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled_api_exception(request: Request, exc: Exception):
        if request.url.path == "/api/v1" or request.url.path.startswith("/api/v1/"):
            return api_error_response(request, 500, None)
        return PlainTextResponse("Internal Server Error", status_code=500)

    @app.exception_handler(ReservationCleanupError)
    async def reservation_cleanup_exception_handler(
        request: Request, exc: ReservationCleanupError
    ) -> JSONResponse:
        return api_error_response(request, 503, domain_error(ApiErrorCode.CLEANUP_FAILED, str(exc)))

    # Configure CORS if origins are specified in config
    config = get_config()
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Retry-After"],
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
        return api_error_response(request, 422, detail)

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
            if full_path == "api/v1" or full_path.startswith("api/v1/"):
                raise StarletteHTTPException(status_code=404)
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
            tags=app.openapi_tags,
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
                network_200_content["application/json"].setdefault("examples", {})["active"] = {"value": {
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
                    "expires_at": "2026-03-20T19:33:46Z",
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
                }}
            
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

        except Exception:
            # If schema structure changes, skip injection silently
            pass

        document_errors(openapi_schema["paths"])
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app
