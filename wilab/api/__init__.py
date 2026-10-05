from contextlib import asynccontextmanager
from pathlib import Path
import logging
import threading

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.openapi.utils import get_openapi

from .docs_style import SWAGGER_UI_EXTRA_CSS
from .dependencies import get_channel_manager, get_config, get_manager
from .routes import router as api_router
from ..version import __version__
from ..wifi.channels import set_regulatory_domain

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

    # Set regulatory domain before populating channel cache
    set_regulatory_domain(cfg.country_code)

    # Pre-populate channel cache in background to not delay startup
    channel_mgr = get_channel_manager()

    def _warm_channel_cache() -> None:
        for net in cfg.networks:
            try:
                channel_mgr.get_channels(net.interface)
                logger.info("Channels cached for %s", net.interface)
            except Exception as exc:
                logger.warning("Failed to cache channels for %s: %s", net.interface, exc)

    cache_thread = threading.Thread(
        target=_warm_channel_cache, name="channel-cache-warmup", daemon=True,
    )
    cache_thread.start()

    yield

    cache_thread.join(timeout=10)
    # Shutdown: gracefully stop any active networks
    try:
        mgr = get_manager(cfg)
        mgr.shutdown_all()
    except Exception:
        # Ignore shutdown errors to not block app teardown
        pass


# Order of the groups in Swagger UI and ReDoc (live /docs, /redoc and the exported bundle all
# read this list). System comes first: it is where a client starts (version, health, and the
# capabilities the lab offers).
OPENAPI_TAGS = [
    {
        "name": "System",
        "description": (
            "Where a client starts. **`/status`** reports the software version, overall health, "
            "every managed device with its capabilities and whether it is reserved, the "
            "**capability catalogue** (what the lab can offer, and how many devices are free for "
            "each) and the reservation limits (minimum, maximum, unlimited allowed). Build your "
            "reservation requests from it. **`/debug`** is a slow, detailed dump for "
            "troubleshooting: do not poll it."
        ),
    },
    {
        "name": "Reservation",
        "description": (
            "Every other operation needs a **reservation**. State which capabilities you need "
            "(`2.4ghz`, `5ghz`, or both; `[]` means any device) and for how long; Wi-Lab picks the device "
            "and returns a `reservation_id`, which identifies you in all the other endpoints. "
            "Reservations expire on their own, unless unlimited reservations are enabled and you "
            "asked for one. **409** means every suitable device is busy (retry later); **422** "
            "means the request is wrong or no device will ever provide what you asked."
        ),
    },
    {
        "name": "Network",
        "description": (
            "The WiFi access point on your reserved device. Create it with an SSID, band, channel "
            "and security settings, inspect it (status, connected clients) or stop it. The band must "
            "be one your device provides (see the `capabilities` of your reservation): anything "
            "else is refused at once. List the channels the device can actually use before "
            "choosing one. The network is stopped "
            "automatically when the reservation expires or is released."
        ),
    },
    {
        "name": "Internet",
        "description": (
            "Control whether the clients of your network can reach the Internet (NAT "
            "forwarding). A new network follows the lab default; enable or disable it at any "
            "time, for example to test how a device behaves when offline."
        ),
    },
    {
        "name": "TX Power",
        "description": (
            "⚠️ **Warning:** TX power control could not be made to work with the USB dongles "
            "tested so far, so correct operation is **not guaranteed** for now. "
            "Read or change the transmit power of your device, on a scale of **1 (lowest) to 4 "
            "(highest)**, while its network is active. Useful for range and roaming tests. The "
            "request is rejected if the hardware does not apply the requested level."
        ),
    },
    {
        "name": "QoS Profiles",
        "description": (
            "Simulate real-world network conditions on your network: bandwidth limits, packet "
            "loss, delay and jitter. Pick a **profile** from the catalogue (an ordered sequence "
            "of timed steps such as a 4G tunnel or a satellite link, played in a loop, bounced, "
            "once or held on the last step), or send fixed parameters. The network must be "
            "active; stopping the profile removes the traffic shaping."
        ),
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wi-Lab",
        version=__version__,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url=None,  # served below, with the extra stylesheet
    )

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
        # A request that omits mandatory fields (e.g. a 3.x client calling a 4.x server)
        # is told about ALL of them at once, so it can be fixed in one round trip.
        missing = [
            ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path"))
            for e in errors if e.get("type") == "missing"
        ]
        if missing:
            detail = f"Missing required field(s): {', '.join(missing)}"
        elif errors:
            first = errors[0]
            loc_parts = [str(part) for part in first.get("loc", []) if part not in ("body", "query", "path")]
            msg = first.get("msg", "Request validation failed")
            detail = f"{': '.join(loc_parts)}: {msg}" if loc_parts else msg
        else:
            detail = "Request validation failed"
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        page = get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=None,
        )
        html = bytes(page.body).decode("utf-8").replace(
            "</head>", f"<style>{SWAGGER_UI_EXTRA_CSS}</style></head>", 1
        )
        return HTMLResponse(html)

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

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app
