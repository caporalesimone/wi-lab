"""WiFi channel information manager with in-memory caching.

Queries ``iw phy`` to build a per-interface list of supported channels,
separated by band (2.4 GHz / 5 GHz).  Results are cached in memory so
that the underlying ``iw`` command is executed at most once per physical
interface.

Design decision – disabled channels:
    ``iw`` reports some channels as ``(disabled)`` without a power value.
    For simplicity these entries are stored with ``max_power_dbm = 0.0``
    and ``disabled = True``.  This avoids optional-float gymnastics while
    keeping the information queryable.  Consumers should check the
    ``disabled`` flag before using ``max_power_dbm``.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..network.commands import execute_iw

logger = logging.getLogger(__name__)

# ---- Data classes ----

_BAND_2_4_MAX_FREQ = 2500  # MHz – everything below is 2.4 GHz
_BAND_5_MIN_FREQ = 5000    # MHz – everything at or above is 5 GHz


@dataclass(frozen=True)
class ChannelInfo:
    """A single WiFi channel."""
    channel: int
    frequency_mhz: int
    max_power_dbm: float
    disabled: bool


@dataclass
class InterfaceChannels:
    """All supported channels for one physical interface, split by band."""
    interface: str
    channels_24ghz: List[ChannelInfo] = field(default_factory=list)
    channels_5ghz: List[ChannelInfo] = field(default_factory=list)


# ---- Manager ----

class ChannelManager:
    """Resolves and caches WiFi channel information per interface.

    Thread-safe: the internal cache is protected by a lock so that
    concurrent API requests don't trigger duplicate ``iw`` queries.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, InterfaceChannels] = {}
        self._lock = threading.Lock()

    # -- public API --

    def get_channels(self, interface: str) -> InterfaceChannels:
        """Return channel info for *interface*, querying ``iw`` only on first call."""
        with self._lock:
            if interface in self._cache:
                return self._cache[interface]

        # Resolve outside lock to avoid blocking other interfaces.
        channels = self._resolve_channels(interface)

        with self._lock:
            # Another thread may have filled the cache in the meantime.
            if interface not in self._cache:
                self._cache[interface] = channels
            return self._cache[interface]

    def invalidate(self, interface: Optional[str] = None) -> None:
        """Drop cached data.  If *interface* is ``None``, flush everything."""
        with self._lock:
            if interface is None:
                self._cache.clear()
            else:
                self._cache.pop(interface, None)

    # -- internals --

    @staticmethod
    def _get_phy_for_interface(interface: str) -> str:
        """Determine the wiphy index for *interface* via ``iw <dev> info``."""
        info = execute_iw([interface, "info"])
        for line in info.splitlines():
            if "wiphy" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    return parts[1]
        raise ValueError(f"Cannot determine wiphy for interface {interface}")

    @staticmethod
    def _parse_iw_phy_output(output: str) -> List[ChannelInfo]:
        """Parse the output of ``iw phy<N> info`` into a list of channels.

        Handles two formats reported by ``iw``:
        - Active:   ``* 2412.0 MHz [1] (20.0 dBm)``
        - Disabled: ``* 2484.0 MHz [14] (disabled)``
        """
        # Matches both active (with dBm) and disabled lines
        pattern = re.compile(
            r"\*\s+([\d.]+)\s+MHz\s+\[(\d+)\]"
            r"\s+\((?:([\d.]+)\s+dBm|disabled)\)"
        )
        channels: List[ChannelInfo] = []
        for line in output.splitlines():
            m = pattern.search(line)
            if not m:
                continue
            freq = int(float(m.group(1)))
            chan = int(m.group(2))
            if m.group(3) is not None:
                max_dbm = float(m.group(3))
                disabled = False
            else:
                max_dbm = 0.0
                disabled = True
            channels.append(ChannelInfo(
                channel=chan,
                frequency_mhz=freq,
                max_power_dbm=max_dbm,
                disabled=disabled,
            ))
        return channels

    def _resolve_channels(self, interface: str) -> InterfaceChannels:
        """Query ``iw`` and split results into 2.4 GHz / 5 GHz bands."""
        phy = self._get_phy_for_interface(interface)
        output = execute_iw(["phy" + phy, "info"])
        all_channels = self._parse_iw_phy_output(output)

        ch_24: List[ChannelInfo] = []
        ch_5: List[ChannelInfo] = []
        for ch in all_channels:
            if ch.frequency_mhz < _BAND_2_4_MAX_FREQ:
                ch_24.append(ch)
            elif ch.frequency_mhz >= _BAND_5_MIN_FREQ:
                ch_5.append(ch)
            # Anything in between is ignored (unlikely).

        result = InterfaceChannels(
            interface=interface,
            channels_24ghz=ch_24,
            channels_5ghz=ch_5,
        )
        logger.info(
            "Resolved %d channels for %s (2.4 GHz: %d, 5 GHz: %d)",
            len(all_channels), interface, len(ch_24), len(ch_5),
        )
        return result
