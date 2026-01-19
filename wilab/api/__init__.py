from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.openapi.utils import get_openapi
from .routes import router
from ..version import __version__
from .dependencies import get_config, get_manager
from contextlib import asynccontextmanager
import logging
import os

logger = logging.getLogger(__name__)


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
    app.include_router(router)
    
    # Serve static files (frontend) if directory exists
    # Try multiple possible locations (in order of preference)
    possible_paths = [
        "/opt/wilab-frontend",  # Standard location (recommended)
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "wilab-frontend"),  # Next to project
        os.path.expanduser("~/wi-lab/wilab-frontend"),  # User's home
        "/root/wi-lab/wilab-frontend",  # Root's home (if service runs as root)
    ]
    
    frontend_path = None
    for path in possible_paths:
        if os.path.exists(path) and os.path.isdir(path):
            frontend_path = path
            break
    
    if frontend_path:
        # Serve index.html for root
        @app.get("/")
        async def serve_index():
            index_path = os.path.join(frontend_path, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"error": "Frontend index.html not found"}
        
        # Serve frontend files and handle SPA routing
        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            # Don't interfere with API routes, docs, or openapi
            if (full_path.startswith("api/") or 
                full_path == "docs" or 
                full_path.startswith("docs/") or
                full_path == "openapi.json"):
                return None
            
            # Check if it's a file that exists (e.g., main-xxx.js, styles-xxx.css, favicon.ico)
            file_path = os.path.join(frontend_path, full_path)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                return FileResponse(file_path)
            
            # For Angular SPA routes (anything else), serve index.html
            index_path = os.path.join(frontend_path, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"error": "Frontend not found"}
        
        logger.info(f"Frontend static files served from {frontend_path}")
    else:
        logger.warning(f"Frontend directory not found. Tried: {', '.join(possible_paths)}. Skipping static file serving.")

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
