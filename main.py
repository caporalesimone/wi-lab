import os
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
    
    uvicorn.run(app, host="0.0.0.0", port=config.api_port, server_header=False, headers=[("x-app-version", __version__)])


if __name__ == "__main__":
    main()

