"""TX power of a running network: four levels from the channel's maximum (ARCH-1)."""

import logging
import re
import time

from ..models import NetworkTxPower
from ..network.commands import CommandError, execute_iw
from .channels import ChannelManager

logger = logging.getLogger(__name__)


class TxPowerMismatchError(Exception):
    """Raised when reported TX power does not match the requested level."""


class TxPowerControl:
    """Sets and reads the TX power of an interface with `iw`."""

    def __init__(self, channel_manager: ChannelManager) -> None:
        self._channel_manager = channel_manager

    def read_dbm(self, interface: str) -> float | None:
        """Read current TX power from interface in dBm. Returns None if unavailable."""
        try:
            output = execute_iw(["dev", interface, "info"])
            # Look for: txpower 20.00 dBm or txpower 5.00 dBm
            pattern = re.compile(r"txpower\s+([\d.]+)\s+dBm")
            for line in output.splitlines():
                m = pattern.search(line)
                if m:
                    return float(m.group(1))
        except Exception as e:
            logger.warning(f"Failed to read current txpower for {interface}: {e}")
        return None

    def channel_capabilities(self, interface: str, channel: int) -> dict:
        info = self._channel_manager.get_channels(interface)
        for ch in info.channels_24ghz + info.channels_5ghz:
            if ch.channel == channel:
                return {"frequency_mhz": ch.frequency_mhz, "max_dbm": ch.max_power_dbm}
        raise ValueError(f"Channel {channel} not supported on interface {interface}")

    @staticmethod
    def levels_dbm(max_dbm: float) -> dict[int, float]:
        # Linearly split max power into four steps
        levels = {
            1: round(max_dbm * 0.25, 1),
            2: round(max_dbm * 0.50, 1),
            3: round(max_dbm * 0.75, 1),
            4: round(max_dbm, 1),
        }
        # Ensure monotonic and at least 1 dBm for lower steps
        levels[1] = max(1.0, levels[1])
        levels[2] = max(levels[1], levels[2])
        levels[3] = max(levels[2], levels[3])
        levels[4] = max(levels[3], levels[4])
        return levels

    @staticmethod
    def reported_level(levels_dbm: dict[int, float], reported_dbm: float | None) -> int | None:
        if reported_dbm is None:
            return None
        return min(levels_dbm, key=lambda lvl: abs(levels_dbm[lvl] - reported_dbm))

    def set_level(self, interface: str, level: int, channel: int, verify_change: bool = False) -> dict:
        """
        Set TX power for interface.

        Args:
            interface: WiFi interface
            level: Power level 1-4
            channel: WiFi channel
            verify_change: If True, wait 3s and verify power actually changed

        Returns:
            Dict with tx power info
        """
        if level not in [1, 2, 3, 4]:
            raise ValueError("TX power level must be 1-4")
        caps = self.channel_capabilities(interface, channel)
        levels_dbm = self.levels_dbm(caps["max_dbm"])
        desired_dbm = levels_dbm[level]
        desired_mbm = int(round(desired_dbm * 100))

        try:
            # Some drivers (mt7921u) do not support it: the caller logs one warning.
            execute_iw(["dev", interface, "set", "txpower", "fixed", str(desired_mbm)], quiet=True)
        except CommandError as e:
            raise ValueError(f"Failed to set txpower: {e}") from e

        power_after = None
        if verify_change:
            # Wait for driver to apply change
            time.sleep(3)
            power_after = self.read_dbm(interface)

            # Compare requested vs reported directly.
            if power_after is not None and abs(power_after - desired_dbm) > 0.5:
                logger.warning(
                    f"{interface}: TX power mismatch (requested={desired_dbm}, reported={power_after})"
                )
                raise TxPowerMismatchError("Interface does not support dynamic power change.")

        result = {
            "interface": interface,
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "tx_power": {
                "requested_level": level,
                "reported_level": self.reported_level(levels_dbm, power_after),
                "reported_dbm": power_after,
            },
        }
        return result

    def info(self, device_id: str, interface: str, channel: int, level: int) -> dict:
        """Requested *level* next to what the interface reports (GET .../txpower)."""
        # Get channel capabilities and compute levels
        caps = self.channel_capabilities(interface, channel)
        levels_dbm = self.levels_dbm(caps["max_dbm"])
        expected_dbm = levels_dbm[level]

        # Read actual current power from interface
        reported_dbm = self.read_dbm(interface)

        # Keep mismatch as server-side observability; GET payload no longer exposes warning.
        if reported_dbm is not None and abs(reported_dbm - expected_dbm) > 0.5:
            logger.info(f"{device_id}: Power mismatch - expected {expected_dbm} dBm, reported {reported_dbm} dBm")

        result = {
            "interface": interface,
            "max_dbm": caps["max_dbm"],
            "levels_dbm": levels_dbm,
            "tx_power": {
                "requested_level": level,
                "reported_level": self.reported_level(levels_dbm, reported_dbm),
                "reported_dbm": reported_dbm,
            },
        }
        return result

    def status(
        self, device_id: str, interface: str, channel: int | None, requested_level: int,
    ) -> NetworkTxPower:
        """The `tx_power` section of a network status; reported values None if unreadable."""
        reported_level: int | None = None
        reported_dbm: float | None = None
        if channel is not None:
            try:
                caps = self.channel_capabilities(interface, channel)
                levels_dbm = self.levels_dbm(caps["max_dbm"])
                reported_dbm = self.read_dbm(interface)
                if reported_dbm is not None:
                    reported_level = min(
                        levels_dbm,
                        key=lambda lvl: abs(levels_dbm[lvl] - reported_dbm),  # type: ignore[operator]
                    )
            except Exception as exc:
                logger.warning(f"Failed to build tx_power status for {device_id}: {exc}")

        return NetworkTxPower(
            requested_level=requested_level,
            reported_level=reported_level,
            reported_dbm=reported_dbm,
        )
