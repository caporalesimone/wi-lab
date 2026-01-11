import os
import logging
import uvicorn
from ipaddress import IPv4Network
from wilab.config import load_config
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
    config = load_config(os.environ.get('CONFIG_PATH'))
    logger.info(f"Configuration loaded from {os.environ.get('CONFIG_PATH', 'default')}")
    logger.info(f"Managed networks: {[n.net_id for n in config.networks]}")

    # Log resolved subnets for each network (sequential /24 from dhcp_base_network)
    try:
        base_net = IPv4Network(config.dhcp_base_network, strict=False)
        octet2 = str(base_net.network_address).split('.')
        for idx, net in enumerate(config.networks):
            octets = octet2.copy()
            third = int(octets[2]) + idx
            if third > 255:
                raise SystemExit(f"Cannot allocate subnet for {net.net_id}: octet overflow")
            octets[2] = str(third)
            subnet = '.'.join(octets) + '/24'
            logger.info(f"Network {net.net_id} on {net.interface} -> subnet {subnet}")
    except Exception as exc:
        raise SystemExit(f"Failed to compute subnets: {exc}") from exc
    
    app = create_app()
    logger.info(f"Starting REST API server on 0.0.0.0:8080")
    logger.info("Visit http://localhost:8080/docs for Swagger UI")
    
    uvicorn.run(app, host="0.0.0.0", port=8080, server_header=False, headers=[("x-app-version", __version__)])


if __name__ == "__main__":
    main()

