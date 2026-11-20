"""Read IPv4 networks already in use on the host."""

import json
from ipaddress import IPv4Network

from .commands import CommandError, execute_command


def host_ipv4_networks() -> set[IPv4Network]:
    """Include host addresses and routed networks, but not the default route."""
    try:
        routes = json.loads(execute_command(["ip", "-j", "-4", "route", "show", "table", "all"], timeout=2))
        if not isinstance(routes, list):
            raise TypeError("route output is not a list")
        networks = set()
        for route in routes:
            if not isinstance(route, dict):
                raise TypeError("route entry is not an object")
            dst = route.get("dst", "default")
            if dst == "default" or route.get("type", "unicast") not in {"unicast", "local"}:
                continue
            network = IPv4Network(dst, strict=False)
            if network.prefixlen:
                networks.add(network)
        return networks
    except (CommandError, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot check AP subnet against host IPv4 routes: {exc}") from exc
