"""The /24 of each antenna's AP network, from the configured base network (ARCH-1)."""

import threading
from ipaddress import IPv4Network
from itertools import islice

from ..config import AppConfig
from ..devices import DeviceRegistry
from .subnet import host_ipv4_networks


class SubnetAllocator:
    """Gives each antenna a /24 that overlaps neither another antenna's nor the host's.

    Reads the devices from *devices* and `dhcp_base_network` from *config* on
    each call: discovery adds devices while the service runs. Subnets follow the
    order in which the devices were added.
    """

    def __init__(self, config: AppConfig, devices: DeviceRegistry) -> None:
        self._config = config
        self._devices = devices
        self._lock = threading.Lock()
        self._assigned: dict[str, IPv4Network] = {}

    def assigned(self, device_id: str) -> IPv4Network | None:
        """The subnet last given to *device_id*, None before its first start."""
        return self._assigned.get(device_id)

    def allocate(self, device_id: str) -> str:
        """Allocate or reuse a non-overlapping /24 before a new AP start.

        *device_id* must be a managed device (the caller checks it).
        """
        devices = self._devices.ids()
        base_net = IPv4Network(self._config.dhcp_base_network, strict=False)
        if base_net.prefixlen != 24:
            raise ValueError("dhcp_base_network must be a /24 network")

        with self._lock:
            host_networks = host_ipv4_networks()
            previous = self._assigned.get(device_id)
            if previous is not None and not any(previous.overlaps(route) for route in host_networks):
                return str(previous)

            assigned = set(self._assigned.values())
            candidates = (
                subnet for subnet in base_net.supernet(new_prefix=16).subnets(new_prefix=24)
                if subnet >= base_net and subnet not in assigned
                and not any(subnet.overlaps(route) for route in host_networks)
            )
            # Preserve pool order even when a later antenna starts first.
            earlier_unassigned = sum(
                device not in self._assigned for device in devices[:devices.index(device_id)]
            )
            subnet = next(islice(candidates, earlier_unassigned, None), None)
            if subnet is None:
                raise ValueError(f"No available /24 AP subnet for {device_id} from {base_net}")
            self._assigned[device_id] = subnet
            return str(subnet)
