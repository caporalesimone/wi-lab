"""Small helpers shared by test modules."""

from typing import Iterable, List

from wilab.reservation import DeviceSpec


def device_specs(device_ids: Iterable[str]) -> List[DeviceSpec]:
    """Capability-less DeviceSpecs in declaration order, for tests that ignore capabilities."""
    return [DeviceSpec(device_id=d, index=i) for i, d in enumerate(device_ids)]
