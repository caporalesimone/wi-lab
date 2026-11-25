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

from .. import heartbeat
from ..network.captive import remove_stale_captive_rules
from ..network.host_guard import remove_stale_guards
from ..reservation import DeviceBusyError, ReservationCleanupError
from ..runtime_cleanup import cleanup_runtime
from ..version import __version__
from ..wifi.channels import set_regulatory_domain
from ..wifi.manager import NetworkNotActive
from .dependencies import (
    discovery_loop,
    get_config,
    get_manager,
    get_reservation_manager,
)
from .errors import (
    DEVICE_BUSY_RETRY_AFTER,
    ApiErrorCode,
    api_error_response,
    document_errors,
    domain_error,
)
from .routes import is_api_path
from .routes import router as api_router
from .routes.recovery_responses import device_busy_detail

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
## Reservation and network lifecycle

Authenticate with a Bearer token. Reserve an adapter with
`POST /api/v2/reservations` (for example `{"duration_seconds": 120}`),
then pass the returned `reservation_id` to the network endpoints. Use one
creation request at a time per reservation. Release with
`DELETE /api/v2/reservations/{reservation_id}` when finished; this also
stops the network. A failed cleanup can return `503` and keep the device held.

Set `"captive_portal": {"enabled": true}` when creating a network to hold each
client behind a simulated captive portal until it presses **Sign in** on the
portal page; see the network creation operation. Omitted, it is disabled.

Operations under **Maintenance** are not part of the client workflow. Each one
requires the `X-Confirm-Password` header matching `protected_commands_password`
in the server configuration, and is disabled when that setting is missing.
`DELETE /api/v2/reservations/all` releases every reservation, including
other clients'; `GET /api/v2/debug` shows internal state.

Every API error body has a `detail` object with an integer `code` and a
stable `reason`. Generic errors use the HTTP status as their code and
include a human-readable `message`. Use the HTTP status and `detail.code`,
not the message, for control flow. Every code is listed in `docs/error-codes.md`.

| Operation and response | Client action |
|---|---|
| Create `409`, `detail.code: 1008` | A network with different settings already runs on this reservation; read it with `GET .../network`. The same create again (same body, e.g. after a lost answer) answers `200` with the network. |
| Create `409`, `detail.code: 1009` | The watchdog is restarting this network: poll `GET .../network` until `runtime_state` is `null`. |
| Create `503`, `detail.code: 1003`, `reservation_invalidated: true` | Every start failed (the server already retried radio failures), or the reservation expires too soon for another start. Discard the ID. Do not retry creation or release it. Request a new reservation if needed. |
| Create `500`, `detail.code: 1013` | Startup failed for a non-radio reason, named by `detail.stage`. No automatic retry. The reservation is still valid; release it if no longer needed. |
| Reserve `409`, `detail.code: 1005` | Ordinary contention. Use `detail.next_available_in` as an estimate, not a guarantee. |
| Reserve `503`, `detail.code: 1002` | Retry the **reservation** POST after `Retry-After` (10 seconds, a polling interval). |
| Reserve `503`, `detail.code: 1003` | All adapters are quarantined and none is recovering. No automatic retry. |
| Release `200` | Always, even if the cleanup failed: the server then keeps the adapter out of the pool and repeats the cleanup itself (`GET /status`: `cleanup_failed`). |
| `409`, `detail.code: 1007` | The reservation is valid but has no running network (Internet, TX power, QoS profile, stop). Create a network first. A `404` always means the reservation itself is gone. |
| `409`, `detail.code: 1010` / `1011` | A QoS profile is already running / no QoS profile is running. |
| `503`, `detail.code: 1006` | Adapter busy: another operation on it (for example a network start) still held it after 5 s. Nothing changed; repeat the same request after `Retry-After` (2 seconds). Every reservation endpoint except the create, which waits instead. |

A transport timeout is not a recovery code. For a lost create response, send
the same create again (same ID and body): it waits for a create in progress and
answers `200` if the AP already runs with that body. A lost reservation response may already have allocated an adapter:
do not blindly repeat it. A `404` for a reservation ID means stop using it.

### Service health and quarantined adapters

Poll `GET /api/v2/status` to know whether the service is fully usable.
Its `status` is `standby` (nothing active, all adapters healthy), `ok`
(networks active and healthy) or `degraded`. `degraded` means an adapter is
quarantined (`antennas[].recovery_state`), a reserved network is being
repaired or lost DHCP (`antennas[].runtime_state`), or a health check failed
while networks are active: `degraded_reasons` lists each cause with a stable
`code`, and `GET /api/v2/monitoring` gives the detail of every check. Show it
to the user with the affected adapter: fewer adapters may be allocatable than
are listed.

| `antennas[]` field | Value | Client action |
|---|---|---|
| `recovery_state` | `recovering` | Adapter quarantined, USB recovery in progress. It may return by itself; do not count it as allocatable. |
| `recovery_state` | `unavailable` | Adapter quarantined, no USB reset running. Wi-Lab re-probes it periodically (30 s, backing off to 15 min) and returns it to the pool when it works. Not allocatable meanwhile; report it if it persists. |
| `runtime_state` | `restoring_ap`, `restoring_dhcp` | The owner's network is being repaired. Wait; do not send a create. |
| `runtime_state` | `dhcp_failed` | DHCP could not be repaired alone; within 5 s the watchdog restarts the whole network (`restoring_ap`). Wait. |
| `runtime_state` | `restore_failed` | AP down: the restart failed and the watchdog retries (15 s, 30 s, 60 s, 120 s, then every 5 min). Wait, or `DELETE .../network` to stop the retries, or create a new network. |

`GET /api/v2/status` distinguishes quarantined adapters (`recovery_state`)
from reserved networks being repaired (`runtime_state`). `reservation: null`
does not make a quarantined adapter allocatable. During
`restoring_ap` or `restoring_dhcp`, poll status instead of sending a new
create. `dhcp_failed` is brief: the watchdog then restarts the whole network.
"""

OPENAPI_TAGS = [
    {"name": "System", "description": "Service health, reservations and per-adapter recovery state. Poll status; the detail of the health checks is in monitoring."},
    {"name": "Reservation", "description": "Allocate or release an adapter. Use the returned reservation ID for device operations."},
    {"name": "Antennas", "description": "The managed radios and what a network on each can use "
     "(encryptions, Wi-Fi generations, channel widths, channels): fill a create form from here. No reservation needed."},
    {"name": "Network", "description": "Create, stop and inspect an AP. The creation response describes when to retry with the same reservation."},
    {"name": "Internet", "description": "Enable or disable Internet access for a reserved network."},
    {"name": "TX Power", "description": "Inspect or request transmit power. Hardware support is not guaranteed."},
    {"name": "QoS Profiles", "description": "Inspect and manage traffic shaping profiles for a reserved network."},
    {"name": "Maintenance", "description": "Operator-only commands and diagnostics, not for clients; "
     "they may be removed in the future. Every one requires the X-Confirm-Password header matching "
     "protected_commands_password, besides the token. Debug is deprecated and will be removed: "
     "it is expensive and shows internal state."},
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
    remove_stale_guards()
    # Processes, runtime files and QoS devices of a previous unclean run (STAB-4).
    cleanup_runtime()

    # Set regulatory domain before any channel query
    set_regulatory_domain(cfg.country_code)

    # Antennas are added by discovery; their channel cache is warmed when added.
    stop_discovery = threading.Event()
    discovery_thread = threading.Thread(
        target=discovery_loop, args=(cfg, stop_discovery),
        name="device-discovery", daemon=True,
    )
    discovery_thread.start()

    # Host-command health checks in the background: /status only reads them.
    stop_health = threading.Event()
    threading.Thread(
        target=manager.health.loop, args=(stop_health,), name="health-checks", daemon=True,
    ).start()

    # systemd watchdog (STAB-1): restart only when a loop stalled and Wi-Lab is idle.
    reservations = get_reservation_manager(cfg)
    stop_notify = threading.Event()
    if heartbeat.watchdog_enabled():
        threading.Thread(
            target=heartbeat.notify_loop, args=(stop_notify, reservations.is_idle),
            name="systemd-watchdog", daemon=True,
        ).start()
    heartbeat.sd_notify("READY=1")

    yield

    stop_notify.set()
    stop_health.set()
    heartbeat.sd_notify("STOPPING=1")
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
        if not is_api_path(path) or exc.status_code < 400:
            return await http_exception_handler(request, exc)
        return api_error_response(request, exc.status_code, exc.detail, headers=exc.headers)

    @app.middleware("http")
    async def answer_unexpected_errors(request: Request, call_next):
        """Answer an unexpected exception here, keeping the connection open.

        The `Exception` handler below runs in Starlette's outermost middleware,
        which re-raises after answering: uvicorn then closes the connection, and
        the client's next keep-alive request on it fails with a transport error
        (seen as ReadError / RemoteProtocolError right after a 500).
        """
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error in %s %s", request.method, request.url.path)
            if is_api_path(request.url.path):
                return api_error_response(request, 500, None)
            return PlainTextResponse("Internal Server Error", status_code=500)

    @app.exception_handler(Exception)
    async def unhandled_api_exception(request: Request, exc: Exception):
        if is_api_path(request.url.path):
            return api_error_response(request, 500, None)
        return PlainTextResponse("Internal Server Error", status_code=500)

    @app.exception_handler(ReservationCleanupError)
    async def reservation_cleanup_exception_handler(
        request: Request, exc: ReservationCleanupError
    ) -> JSONResponse:
        return api_error_response(request, 503, domain_error(ApiErrorCode.CLEANUP_FAILED, str(exc)))

    @app.exception_handler(NetworkNotActive)
    async def network_not_active_handler(request: Request, exc: NetworkNotActive) -> JSONResponse:
        # API-2: one answer for "valid reservation, no network", distinct from 404.
        return api_error_response(
            request, 409, domain_error(ApiErrorCode.NETWORK_NOT_ACTIVE, str(exc)),
        )

    @app.exception_handler(DeviceBusyError)
    async def device_busy_exception_handler(request: Request, exc: DeviceBusyError) -> JSONResponse:
        # RACE-1: never park a request thread behind a slow operation on the same adapter.
        return api_error_response(
            request, 503, device_busy_detail(),
            headers={"Retry-After": str(DEVICE_BUSY_RETRY_AFTER)},
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
            # pydantic prefixes errors raised by validators with "Value error, ".
            msg = first.get("msg", "Request validation failed").removeprefix("Value error, ")
            # One format for every path: `radio.channel_width: ...`, like the
            # paths the create body adds to the rules that compare fields.
            detail = f"{'.'.join(loc_parts)}: {msg}" if loc_parts else msg
        else:
            detail = "Request validation failed"
        return api_error_response(request, 422, detail)

    # Include API router
    app.include_router(api_router)

    # /api/v1 was removed in 4.0.0 (the contract changed): 404 for every method,
    # not 405 from the frontend catch-all. Nothing of v1 is kept.
    @app.api_route(
        "/api/v1/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    async def removed_api_v1(rest: str) -> None:
        raise StarletteHTTPException(status_code=404)

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
            # Unknown API paths, including the removed /api/v1, are a JSON 404.
            if is_api_path("/" + full_path):
                raise StarletteHTTPException(status_code=404)
            if (
                full_path == "docs"
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
        # Examples live next to their model or route (API-9); only the shared error
        # envelope is added here.
        document_errors(openapi_schema["paths"])
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app
