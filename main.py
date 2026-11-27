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
    # Until here the level is INFO: the startup lines above are always written.
    log.set_level(log.level_of(config.log_level))
    logger.info("Configuration loaded from %s (log level %s)",
                os.environ.get("CONFIG_PATH", "default"), config.log_level)
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


# --reload-drivers refused because the service is running (ARCH-11 D1).
EXIT_SERVICE_RUNNING = 3


def reload_drivers_only(path: str | None) -> int:
    """Reload the driver of the adapters Wi-Lab would manage; the service must be stopped."""
    from wilab.config import load_config
    from wilab.wifi.discovery import default_route_interfaces, discover_radios
    from wilab.wifi.drivers import reload_drivers, service_is_running

    if service_is_running():
        print(
            "ERROR: Wi-Lab is running. Reloading a driver resets every adapter it drives, so every "
            "network must be off.\n       Stop the service ('make stop'), then run this again.",
        )
        return EXIT_SERVICE_RUNNING
    config = load_config(path)
    host = default_route_interfaces()
    if config.upstream_interface != "auto":
        host.add(config.upstream_interface)
    disabled = {a.interface for a in config.antennas if a.disable}
    radios = [r.interface for r in discover_radios(quiet=True) if r.interface not in host | disabled]
    if not radios:
        print("No Wi-Fi adapter to reload.")
        return 0
    failed = False
    for result in reload_drivers(radios, host):
        names = ", ".join(result.interfaces)
        if result.ok:
            print(f"OK      {result.module}: reloaded ({names})")
        else:
            failed = True
            print(f"FAILED  {result.module} ({names}): {result.error}")
    if not failed:
        print("Drivers reloaded. Start the service with 'make start'.")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wi-Lab access point manager")
    parser.add_argument("--validate-config", action="store_true", help="validate configuration without starting the service")
    parser.add_argument(
        "--reload-drivers", action="store_true",
        help="reload the kernel driver of the Wi-Fi adapters and exit (root, service stopped)",
    )
    parser.add_argument("--config", help="configuration file (with --validate-config or --reload-drivers)")
    args = parser.parse_args()
    if args.config and not (args.validate_config or args.reload_drivers):
        parser.error("--config requires --validate-config or --reload-drivers")
    if args.reload_drivers:
        raise SystemExit(reload_drivers_only(args.config))
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

