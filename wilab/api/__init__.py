from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from .routes import router
from ..version import __version__
from .dependencies import get_config, get_manager
from contextlib import asynccontextmanager


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
    app.include_router(router)

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
            
            # GET /interface/{net_id}/txpower response example
            txpower_get = paths.get("/api/v1/interface/{net_id}/txpower", {}).get("get", {})
            txpower_responses = txpower_get.get("responses", {})
            txpower_200 = txpower_responses.get("200", {})
            txpower_200_content = txpower_200.get("content", {})
            if "application/json" in txpower_200_content:
                txpower_200_content["application/json"]["example"] = {
                    "net_id": "ap-01",
                    "interface": "wlx782051245264",
                    "channel": 6,
                    "frequency_mhz": 2437,
                    "max_dbm": 20.0,
                    "levels_dbm": {
                        "1": 5.0,
                        "2": 10.0,
                        "3": 15.0,
                        "4": 20.0
                    },
                    "current_level": 2,
                    "current_dbm": 10.0,
                    "reported_dbm": 10.0,
                    "warning": None
                }
        except Exception:
            # If schema structure changes, skip injection silently
            pass

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi
    return app
