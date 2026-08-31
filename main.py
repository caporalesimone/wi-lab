import argparse
import logging
import os
import sys
from ipaddress import IPv4Network

from wilab.version import __version__

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Exit codes for --validate-config. Distinguishing 2 from 1 lets a CI job tell
# "you forgot to mount the config" from "the config is wrong".
EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wi-lab",
        description="Wi-Lab WiFi Access Point manager.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to config.yaml (default: $CONFIG_PATH, else ./config.yaml)",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate the configuration and exit, without starting the server",
    )
    parser.add_argument(
        "--check-hardware",
        action="store_true",
        help="With --validate-config, also verify interfaces and host routes "
             "(always done when starting normally)",
    )
    return parser


def resolve_config_path(cli_path: str | None) -> str:
    return cli_path or os.environ.get("CONFIG_PATH") or os.path.join(os.getcwd(), "config.yaml")


def validate_only(config_path: str, check_hardware: bool) -> int:
    """Run the validator and report. Constructs nothing and starts nothing.

    Deliberately calls the validator directly rather than load_config(): validating a
    configuration must be safe to do on a production host at any time.
    """
    from wilab.config_validation import validate_config_file

    report = validate_config_file(config_path, check_hardware=check_hardware)
    print(report.render(), end="")
    if report.unreadable:
        return EXIT_UNREADABLE
    return EXIT_OK if report.ok else EXIT_INVALID


def run_server(config_path: str) -> int:
    # Imported here so that --validate-config needs neither fastapi nor uvicorn: a config
    # can be checked on a machine that does not have the full runtime installed.
    import uvicorn

    from wilab.api import create_app
    from wilab.config import load_config
    from wilab.network.safety import check_existing_wilab_rules, log_host_impact_warning

    logger.info(f"Wi-Lab v{__version__} starting...")

    # ⚠️ WARNING: Running with network_mode=host impacts the host system
    log_host_impact_warning()

    # Check for existing rules from previous runs
    check_existing_wilab_rules()

    # Load configuration (validates first; exits with the full report on failure)
    config = load_config(config_path)
    logger.info(f"Configuration loaded from {config_path}")
    logger.info(f"Managed networks: {[n.device_id for n in config.networks]}")

    # Log resolved subnets for each network (sequential /24 from dhcp_base_network)
    try:
        base_net = IPv4Network(config.dhcp_base_network, strict=False)
        octet2 = str(base_net.network_address).split('.')
        for idx, net in enumerate(config.networks):
            octets = octet2.copy()
            third = int(octets[2]) + idx
            if third > 255:
                raise SystemExit(f"Cannot allocate subnet for {net.device_id}: octet overflow")
            octets[2] = str(third)
            subnet = '.'.join(octets) + '/24'
            logger.info(f"Network {net.device_id} on {net.interface} -> subnet {subnet}")
    except Exception as exc:
        raise SystemExit(f"Failed to compute subnets: {exc}") from exc

    app = create_app()
    logger.info("Starting REST API server on 0.0.0.0:8080")
    logger.info("Visit http://localhost:8080/docs for Swagger UI")

    uvicorn.run(
        app, host="0.0.0.0", port=8080,
        server_header=False, headers=[("x-app-version", __version__)],
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = resolve_config_path(args.config)

    if args.validate_config:
        return validate_only(config_path, check_hardware=args.check_hardware)

    # Propagate an explicit --config to the FastAPI dependency layer, which resolves the
    # configuration from the environment.
    os.environ["CONFIG_PATH"] = config_path
    return run_server(config_path)


if __name__ == "__main__":
    sys.exit(main())
