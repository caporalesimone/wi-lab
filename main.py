import os
import argparse
import logging
import uvicorn
from wilab import log
from wilab.api import create_app
from wilab.config import load_config
from wilab.version import __version__
from wilab.network.safety import log_host_impact_warning
from wilab.precheck import EXIT_PRECHECK_FAILED, log_findings, run_prechecks

# The only logging configuration of the service (ARCH-10).
log.setup()
logger = logging.getLogger(__name__)


def main():
    logger.info("Wi-Lab v%s starting...", __version__)

    # What the host must offer (NM-1). A fatal finding stops here with 78:
    # the unit does not restart on it (RestartPreventExitStatus=78).
    if log_findings(run_prechecks()):
        raise SystemExit(EXIT_PRECHECK_FAILED)

    # ⚠️ WARNING: Running with network_mode=host impacts the host system
    log_host_impact_warning()
    
    # Load configuration (exits with descriptive error on failure)
    config = load_config()
    logger.info("Configuration loaded from %s", os.environ.get("CONFIG_PATH", "default"))
    logger.info(
        "Wi-Fi adapters are added by device discovery (subnets from %s)", config.dhcp_base_network,
    )
    
    # The app's context uses this same config object (ARCH-5).
    app = create_app(config)
    logger.info("Starting REST API server on 0.0.0.0:%s", config.api_port)
    logger.info("Visit http://localhost:%s/docs for Swagger UI", config.api_port)
    
    # Requests still running at shutdown get 10 s, so the cleanup that follows
    # stays inside the unit's TimeoutStopSec (STAB-8).
    uvicorn.run(
        app, host="0.0.0.0", port=config.api_port, server_header=False,
        headers=[("x-app-version", __version__)], timeout_graceful_shutdown=10,
        log_config=None,   # uvicorn's loggers go through log.setup() (ARCH-10)
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

