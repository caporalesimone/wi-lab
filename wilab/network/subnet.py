"""Read-only checks for conflicts with existing IPv4 routes."""

import json
import logging
from ipaddress import IPv4Network

from .commands import CommandError, execute_command

logger = logging.getLogger(__name__)


def warn_subnet_collisions(subnet: str, owned_routes: set[tuple[str, str, str]]) -> None:
    """Warn about overlapping routes, except known connected Wi-Lab AP routes."""
    try:
        routes = json.loads(execute_command(["ip", "-j", "-4", "route", "show", "table", "all"]))
        if not isinstance(routes, list):
            raise TypeError("route output is not a list")
        target = IPv4Network(subnet)
        for route in routes:
            if not isinstance(route, dict):
                raise TypeError("route entry is not an object")
            dst = route.get("dst", "default")
            if dst == "default" or route.get("type", "unicast") != "unicast":
                continue
            network = IPv4Network(dst, strict=False)
            if network.prefixlen == 0 or not target.overlaps(network):
                continue
            if (
                route.get("protocol") == "kernel"
                and (str(network), route.get("dev"), route.get("prefsrc")) in owned_routes
            ):
                continue
            logger.warning(
                "Wi-Lab subnet %s overlaps existing route %s (device %s); "
                "this may disrupt host connectivity",
                subnet, network, route.get("dev", "unknown"),
            )
    except (CommandError, ValueError, TypeError) as exc:
        logger.warning("Cannot check subnet %s against host routes: %s", subnet, exc)
