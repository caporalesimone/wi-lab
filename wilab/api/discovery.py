"""Device discovery: adds the Wi-Fi adapters found while the service runs."""

import logging
import threading

from .. import heartbeat
from ..config import AppConfig, NetworkEntry, scan_new_networks
from ..network.commands import CommandError
from ..network.unmanaged import exclude_from_host_managers
from ..precheck import warn_wpa_supplicant
from ..reservation import ReservationManager
from ..wifi.channels import ChannelManager
from ..wifi.interface import reset_interface
from ..wifi.manager import NetworkManager

logger = logging.getLogger(__name__)

DISCOVERY_FAST_INTERVAL = 5.0
DISCOVERY_SLOW_INTERVAL = 30.0
# Longest wait for the discovery thread at shutdown (STAB-8).
DISCOVERY_JOIN_TIMEOUT = 10.0


class DeviceDiscovery:
    """Adds newly found Wi-Fi interfaces to the allocatable pool."""

    def __init__(
        self, config: AppConfig, manager: NetworkManager, reservations: ReservationManager,
        channels: ChannelManager,
    ) -> None:
        self.config = config
        self.manager = manager
        self.reservations = reservations
        self.channels = channels
        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the discovery thread; the first scan runs at once."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self.loop, args=(self._stop,), name="device-discovery", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = DISCOVERY_JOIN_TIMEOUT) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def scan(self, *, quiet: bool = False) -> list[NetworkEntry]:
        """Add newly found Wi-Fi interfaces to the allocatable pool."""
        config = self.config
        with self._scan_lock:
            added = scan_new_networks(config, quiet=quiet)
            if not added:
                return []
            # Appending preserves the order used for subnet allocation.
            config.antennas = [*config.antennas, *added]
            exclude_from_host_managers(n.interface for n in config.antennas)
            warn_wpa_supplicant(n.interface for n in added)
            self.reservations.add_devices([n.device_id for n in added])
            manager = self.manager
            for net in added:
                # Clean what a previous run left on the radio (STAB-4); nobody uses it yet.
                with manager.device_lock(net.device_id):
                    reset_interface(net.interface)
            manager.watchdog.watch([n.device_id for n in added])
            for net in added:
                logger.info(
                    "Added %s as %r (%s)", net.interface, net.display_name,
                    f"USB port {net.usb_recovery_port}" if net.usb_recovery_port else "non-USB",
                )
            threading.Thread(
                target=_warm_channels, args=(self.channels, [n.interface for n in added]),
                name="channel-cache-scan", daemon=True,
            ).start()
            return added

    def loop(self, stop: threading.Event) -> None:
        """Add antennas for the whole service lifetime.

        The first scan runs immediately. Scans repeat every 5 s while no antenna is
        managed, then every 30 s. Only the first scan logs configuration warnings.
        """
        config = self.config
        interval = 0.0
        first = True
        searching: bool | None = None
        last_error: str | None = None
        while not stop.wait(interval):
            heartbeat.beat("discovery")
            try:
                self.scan(quiet=not first)
            except Exception as exc:  # this loop must survive anything (WD-9)
                if str(exc) != last_error:
                    logger.exception("Device discovery failed")
                last_error = str(exc)
            else:
                last_error = None
            first = False
            if searching != (not config.antennas):
                searching = not config.antennas
                if searching:
                    logger.warning(
                        "No Wi-Fi adapter available; discovery runs every %.0f s", DISCOVERY_FAST_INTERVAL,
                    )
                else:
                    logger.info(
                        "%d Wi-Fi adapter(s) managed; discovery runs every %.0f s",
                        len(config.antennas), DISCOVERY_SLOW_INTERVAL,
                    )
            interval = DISCOVERY_FAST_INTERVAL if searching else DISCOVERY_SLOW_INTERVAL


def _warm_channels(channels: ChannelManager, interfaces: list[str]) -> None:
    for interface in interfaces:
        try:
            channels.get_channels(interface)
        except (CommandError, ValueError) as exc:
            logger.warning("Failed to cache channels for %s: %s", interface, exc)
