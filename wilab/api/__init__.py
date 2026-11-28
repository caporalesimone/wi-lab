import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import log
from ..config import AppConfig, load_config
from ..reservation import DeviceBusyError
from ..version import __version__
from ..wifi.manager import NetworkNotActive
from .context import AppContext
from .errors import (
    DEVICE_BUSY_RETRY_AFTER,
    ApiErrorCode,
    api_error_response,
    document_errors,
    domain_error,
)
from .docs_page import swagger_ui_page
from .routes import is_api_path
from .routes import router as api_router
from .routes.recovery_responses import device_busy_detail

logger = logging.getLogger(__name__)

# The reservation in a request path, for the log context (ARCH-10).
_RESERVATION_PATH = re.compile(r"^/api/v\d+/reservations/([0-9a-f]+)(?:/|$)")

API_DESCRIPTION = """
## Reservation and network lifecycle

Authenticate with a Bearer token. Reserve an adapter with
`POST /api/v2/reservations` (for example `{"duration_seconds": 120}`),
then pass the returned `reservation_id` to the network endpoints. The create
is asynchronous: `POST /access-point/{reservation_id}` answers `202` with `runtime_state:
starting`; poll `GET /access-point/{reservation_id}` until `runtime_state` is `null` (the AP is
up), `start_failed` (see `error`) or the answer is `404` (see `detail.reason`).
Release with `DELETE /api/v2/reservations/{reservation_id}` when finished; this
also stops the network, or cancels a start in progress, and always answers `200`.

Set `"captive_portal": {"enabled": true}` when creating a network to hold each
client behind a simulated captive portal until it presses **Sign in** on the
portal page; see the network creation operation. Omitted, it is disabled.

Request bodies take only the JSON types they document: a number sent as a
string (`"6"`), `true` for a number, or a number for a boolean is a `422`.

**Not stable in 4.1.** `radio.tx_power_level` is applied once at creation, but
the MT7921U ignores it in AP mode (it always transmits at its calibrated
maximum) and `radio.tx_power.reported_dbm` is not a measurement. **QoS
Profiles** is experimental and untested. Both may change in
any release: do not build client logic on them.

Operations under **Maintenance** are not part of the client workflow. Each one
requires the `X-Confirm-Password` header matching `protected_commands_password`
in the server configuration, and is disabled when that setting is missing.
`DELETE /api/v2/reservations/all` releases every reservation, including
other clients'.

Every API error body has a `detail` object with an integer `code` and a
stable `reason`. Generic errors use the HTTP status as their code and
include a human-readable `message`. Use the HTTP status and `detail.code`,
not the message, for control flow. Every code is listed in `docs/error-codes.md`.

| Operation and response | Client action |
|---|---|
| Create `202` | Start accepted (also the same body while it runs): poll `GET /access-point/{reservation_id}`. |
| Create `200` | The same body on a network already running with it: done. |
| Create `409`, `detail.code: 1008` | A network with different settings runs or is starting on this reservation; read it with `GET /access-point/{reservation_id}`. |
| Create `409`, `detail.code: 1012` | The last stop on this reservation did not complete: repeat `DELETE /access-point/{reservation_id}` until `200`, then the create. |
| Create `409`, `detail.code: 1009` | The watchdog is repairing this network: poll `GET /access-point/{reservation_id}` until `runtime_state` is `null`. |
| Polling: `runtime_state: start_failed` | Non-radio failure, `error.code` 1013 with `error.stage`. The reservation is still valid: no automatic retry; release it if no longer needed. |
| `404` on any call with a reservation ID | `detail.reason` (stable): `reservation_invalidated` (every start failed, antenna quarantined) or `reservation_expired`: reserve again, never release the ID. `reservation_released` or `reservation_not_found`: nothing to do. |
| Reserve `409`, `detail.code: 1005` | Ordinary contention. Use `detail.next_available_in` as an estimate, not a guarantee. |
| Reserve `503`, `detail.code: 1002` | Retry the **reservation** POST after `Retry-After` (10 seconds, a polling interval). |
| Reserve `503`, `detail.code: 1003` | All adapters are quarantined and none is recovering. No automatic retry. |
| Release `200` | Always, even if the cleanup failed: the server then keeps the adapter out of the pool and repeats the cleanup itself (`GET /status`: `cleanup_failed`). |
| `409`, `detail.code: 1007` | The reservation is valid but has no running network (Internet, QoS profile, stop). Create a network first. A `404` always means the reservation itself is gone. |
| `409`, `detail.code: 1010` / `1011` | A QoS profile is already running / no QoS profile is running. |
| `503`, `detail.code: 1006` | Adapter busy: another operation on it (for example a network start) still held it after 5 s. Nothing changed; repeat the same request after `Retry-After` (2 seconds). Never on a release; on the create only when the same body finds the network already running (the `200` case). |

A transport timeout is not a recovery code. For a lost create response, send
the same create again (same ID and body) or poll `GET /access-point/{reservation_id}`: the same
body never starts a second AP. A lost reservation response may already have
allocated an adapter: do not blindly repeat it.

### Service health and quarantined adapters

Poll `GET /api/v2/status` to know whether the service is fully usable.
Its `service` has `health` (`good` or `degraded`), `free_antennas` (how many
antennas a reservation would get now), `degraded_reasons` and `restart_required`. `degraded` means an adapter is
quarantined, a reserved network is being repaired or lost DHCP, or a health check failed
while networks are active: `service.degraded_reasons` lists each cause with a stable
`code`, and `checks` gives the detail of every check. Show it
to the user with the affected adapter: fewer adapters may be allocatable than
are listed.

`GET /api/v2/antennas` lists the antennas, the same `free_antennas` and the
reservation limits (`reservation_policy`). Each entry of its `antennas[]` shows
the state of one adapter:

| `antennas[]` field | Value | Client action |
|---|---|---|
| `recovery_state` | `recovering` | Adapter quarantined, USB recovery in progress. It may return by itself; do not count it as allocatable. |
| `recovery_state` | `unavailable` | Adapter quarantined, no USB reset running. Wi-Lab re-probes it periodically (30 s, backing off to 15 min) and returns it to the pool when it works. Not allocatable meanwhile; report it if it persists. |
| `runtime_state` | `restoring_ap`, `restoring_dhcp` | The owner's network is being repaired. Wait; do not send a create. |
| `runtime_state` | `dhcp_failed` | DHCP could not be repaired alone; within 5 s the watchdog restarts the whole network (`restoring_ap`). Wait. |
| `runtime_state` | `restore_failed` | AP down: the restart failed and the watchdog retries (15 s, 30 s, 60 s, 120 s, then every 5 min). Wait, or `DELETE /access-point/{reservation_id}` to stop the retries, or create a new network. |

`GET /api/v2/antennas` distinguishes quarantined adapters (`recovery_state`)
from reserved networks being repaired (`runtime_state`). `reservation: null`
does not make a quarantined adapter allocatable. During
`restoring_ap` or `restoring_dhcp`, poll `GET /access-point/{reservation_id}` instead of sending a new
create. `dhcp_failed` is brief: the watchdog then restarts the whole network.
"""

OPENAPI_TAGS = [
    {"name": "System", "description": "Service health and the detail of the health checks: poll status."},
    {"name": "Reservation", "description": "Allocate or release an adapter. Use the returned reservation ID for device operations."},
    {"name": "Antennas", "description": "The antennas with their state, how many are free and the "
     "reservation limits; one antenna with its repair health; what an access point on it can use (encryptions, "
     "Wi-Fi generations, channel widths, channels): fill a create form from here. No reservation needed."},
    {"name": "Access point", "description": "Create, stop and inspect the access point of a reservation, "
     "and turn its Internet access on and off. "
     "The create is asynchronous: poll `GET /access-point/{reservation_id}` for the outcome."},
    {"name": "QoS Profiles", "description": "**Experimental, not stable:** untested, may change in any "
     "release. Inspect and manage traffic shaping profiles for a reserved network."},
    {"name": "Maintenance", "description": "Operator-only commands, not for clients; they may be "
     "removed in the future. Every one requires the X-Confirm-Password header matching "
     "protected_commands_password, besides the token. The detailed health checks are in "
     "`checks` of GET /status (System)."},
]


def _candidate_frontend_paths() -> list[Path]:
    project_root = Path(__file__).resolve().parents[2]
    return [
        project_root / "frontend" / "dist" / "wi-lab-frontend" / "browser",  # Docker build output
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The context was built with the app (no thread yet): start it in its fixed
    # order, and stop it at shutdown (ARCH-5).
    context: AppContext = app.state.context
    context.start()
    yield
    context.stop()


def _keep_example_nulls(paths: dict, routes: list) -> None:
    """Put back the null values of the routes' own response examples.

    FastAPI builds the schema with exclude_none, which also drops every null
    from the examples: `service.restart_required: null` or `reservation: null` vanished
    from Swagger although the API always sends them. The examples are the
    route's own, copied as written; nothing is added.
    """
    from fastapi import routing
    from fastapi.openapi.utils import _get_api_route_for_openapi

    # The same walk as FastAPI's get_openapi (routers are included lazily).
    for context in routing.iter_route_contexts(routes):
        route = _get_api_route_for_openapi(context)
        if route is None:
            continue
        for method in route.methods or ():
            operation = paths.get(route.path_format, {}).get(method.lower())
            if operation is None:
                continue
            for code, response in (route.responses or {}).items():
                media = response.get("content", {}).get("application/json", {})
                target = operation.get("responses", {}).get(str(code), {}).get("content", {}).get("application/json")
                if target is None:
                    continue
                if "example" in media:
                    target["example"] = media["example"]
                for name, entry in media.get("examples", {}).items():
                    if "value" in entry and name in target.get("examples", {}):
                        target["examples"][name]["value"] = entry["value"]


def create_app(config: AppConfig | None = None) -> FastAPI:
    """The application and its AppContext, built from *config* (default: load_config()).

    Nothing runs until the lifespan starts the context.
    """
    if config is None:
        config = load_config()
    app = FastAPI(
        title="Wi-Lab", version=__version__, lifespan=lifespan,
        description=API_DESCRIPTION, openapi_tags=OPENAPI_TAGS,
        docs_url=None,   # served below, with the token masked in the cURL box
    )

    @app.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return swagger_ui_page(app.openapi_url or "/openapi.json", app.title)
    app.state.context = AppContext.build(config)

    @app.exception_handler(StarletteHTTPException)
    async def api_http_exception(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if not is_api_path(path) or exc.status_code < 400:
            return await http_exception_handler(request, exc)
        return api_error_response(request, exc.status_code, exc.detail, headers=exc.headers)

    @app.middleware("http")
    async def log_context(request: Request, call_next):
        """Every record written for a request on a reservation carries it and its antenna (ARCH-10)."""
        match = _RESERVATION_PATH.match(request.url.path)
        if match is None:
            return await call_next(request)
        reservation_id = match[1]
        antenna = next((
            device for device, reservation in app.state.context.reservations.snapshot().items()
            if reservation.reservation_id == reservation_id
        ), None)
        with log.context(antenna=antenna, reservation=reservation_id):
            return await call_next(request)

    @app.middleware("http")
    async def answer_unexpected_errors(request: Request, call_next):
        """Answer an unexpected exception here, keeping the connection open.

        An `Exception` handler would run in Starlette's outermost middleware,
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

    @app.exception_handler(NetworkNotActive)
    async def access_point_not_active_handler(request: Request, exc: NetworkNotActive) -> JSONResponse:
        # API-2: one answer for "valid reservation, no network", distinct from 404.
        return api_error_response(
            request, 409, domain_error(ApiErrorCode.ACCESS_POINT_NOT_ACTIVE, str(exc)),
        )

    @app.exception_handler(DeviceBusyError)
    async def device_busy_exception_handler(request: Request, exc: DeviceBusyError) -> JSONResponse:
        # RACE-1: never park a request thread behind a slow operation on the same adapter.
        return api_error_response(
            request, 503, device_busy_detail(),
            headers={"Retry-After": str(DEVICE_BUSY_RETRY_AFTER)},
        )

    # Configure CORS if origins are specified in config
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Retry-After"],
        )
        logger.info("CORS enabled for origins: %s", config.cors_origins)
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
        frontend_root = frontend_path.resolve()

        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_path = frontend_root / "index.html"
            if index_path.is_file():
                return FileResponse(index_path)
            return {"error": "Frontend index.html not found"}

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str):
            # Unknown API paths, including the removed /api/v1, and the paths of the
            # API documentation are never the frontend: a 404.
            if is_api_path("/" + full_path) or full_path.split("/", 1)[0] in {"docs", "redoc", "openapi.json"}:
                raise StarletteHTTPException(status_code=404)

            # Never serve anything outside the frontend directory (SEC-1): an absolute
            # path (`GET //etc/shadow`, no frontend URL starts with "//") or `..`
            # segments that leave it are a 404, not even the page.
            candidate = (frontend_root / full_path).resolve()
            if full_path.startswith("/") or not candidate.is_relative_to(frontend_root):
                raise StarletteHTTPException(status_code=404)
            if candidate.is_file():
                return FileResponse(candidate)

            index_path = frontend_root / "index.html"
            if index_path.is_file():
                return FileResponse(index_path)
            return {"error": "Frontend not found"}

        logger.info("Frontend static files served from %s", frontend_path)
    else:
        tried = ", ".join(str(path) for path in frontend_candidates)
        logger.warning("Frontend directory not found. Tried: %s. Skipping static file serving.", tried)

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
        _keep_example_nulls(openapi_schema["paths"], app.routes)
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app
