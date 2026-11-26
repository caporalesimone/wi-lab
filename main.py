import os
import argparse
import logging
import uvicorn
from wilab.api.dependencies import get_config
from wilab.api import create_app
from wilab.version import __version__
from wilab.network.safety import log_host_impact_warning, check_existing_wilab_rules

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    logger.info(f"Wi-Lab v{__version__} starting...")
    
    # ⚠️ WARNING: Running with network_mode=host impacts the host system
    log_host_impact_warning()
    
    # Check for existing rules from previous runs
    check_existing_wilab_rules()
    
    # Load configuration (exits with descriptive error on failure)
    config = get_config()
    logger.info(f"Configuration loaded from {os.environ.get('CONFIG_PATH', 'default')}")
    logger.info(
        "Wi-Fi adapters are added by device discovery (subnets from %s)", config.dhcp_base_network,
    )
    
    app = create_app()
    logger.info("Starting REST API server on 0.0.0.0:%s", config.api_port)
    logger.info("Visit http://localhost:%s/docs for Swagger UI", config.api_port)
    
    # Requests still running at shutdown get 10 s, so the cleanup that follows
    # stays inside the unit's TimeoutStopSec (STAB-8).
    uvicorn.run(
        app, host="0.0.0.0", port=config.api_port, server_header=False,
        headers=[("x-app-version", __version__)], timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wi-Lab access point manager")
    parser.add_argument("--validate-config", action="store_true", help="validate configuration without starting the service")
    parser.add_argument("--config", help="configuration file (only with --validate-config)")
    args = parser.parse_args()
    if args.config and not args.validate_config:
        parser.error("--config requires --validate-config")
    if args.validate_config:
        from wilab.config import config_path
        from wilab.config_validation import validate_config_file

        errors, warnings = validate_config_file(config_path(args.config))
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}")
        if errors:
            raise SystemExit(1)
        print("Configuration is valid.")
    else:
        main()

