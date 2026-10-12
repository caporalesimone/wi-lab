"""Small helpers shared by test modules."""

from typing import Iterable, List

from wilab.config import Capability
from wilab.reservation import DeviceSpec


def device_specs(device_ids: Iterable[str]) -> List[DeviceSpec]:
    """Identical dual-band DeviceSpecs in declaration order, for tests that ignore capabilities.

    Reservations must now name at least one capability, so the devices have to provide some.
    """
    both = frozenset({Capability.BAND_24GHZ, Capability.BAND_5GHZ})
    return [DeviceSpec(device_id=d, capabilities=both, index=i) for i, d in enumerate(device_ids)]
