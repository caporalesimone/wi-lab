"""Device discovery: adds the Wi-Fi adapters found while the service runs."""

import logging
import threading

from .. import heartbeat
from ..config import AppConfig, scan_new_networks
from ..devices import Device, DeviceRegistry
from ..network.commands import CommandError
from ..network.unmanaged import exclude_from_host_managers
from ..precheck import warn_wpa_supplicant
from ..wifi.channels import ChannelManager
from ..wifi.interface import reset_interface

logger = logging.getLogger(__name__)

DISCOVERY_FAST_INTERVAL = 5.0
DISCOVERY_SLOW_INTERVAL = 30.0
# Longest wait for the discovery thread at shutdown (STAB-8).
DISCOVERY_JOIN_TIMEOUT = 10.0


class DeviceDiscovery:
    """Adds newly found Wi-Fi interfaces to the device registry.

    The registry is the allocatable pool: reservations, networks and the
    watchdog read it, so nothing else is told about a new device.
    """

    def __init__(self, config: AppConfig, devices: DeviceRegistry, channels: ChannelManager) -> None:
        self.config = config
        self.devices = devices
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

    def scan(self, *, quiet: bool = False) -> list[Device]:
        """Add newly found Wi-Fi interfaces to the allocatable pool."""
        with self._scan_lock:
            managed = self.devices.all()
            added = scan_new_networks(self.config, managed, quiet=quiet)
            if not added:
                return []
            exclude_from_host_managers(d.interface for d in [*managed, *added])
            warn_wpa_supplicant(d.interface for d in added)
            # Adding preserves the order used for reservations and subnet allocation;
            # the watchdog starts watching each device as it is added.
            for device in added:
                self.devices.add(device)
            for device in added:
                # Clean what a previous run left on the radio (STAB-4); nobody uses it yet.
                with device.lock:
                    reset_interface(device.interface)
            for device in added:
                logger.info(
                    "Added %s as %r (%s)", device.interface, device.display_name,
                    f"USB port {device.usb_port}" if device.usb_port else "non-USB",
                )
            threading.Thread(
                target=_warm_channels, args=(self.channels, [d.interface for d in added]),
                name="channel-cache-scan", daemon=True,
            ).start()
            return added

    def loop(self, stop: threading.Event) -> None:
        """Add antennas for the whole service lifetime.

        The first scan runs immediately. Scans repeat every 5 s while no antenna is
        managed, then every 30 s. Only the first scan logs configuration warnings.
        """
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
            if searching != (not self.devices):
                searching = not self.devices
                if searching:
                    logger.warning(
                        "No Wi-Fi adapter available; discovery runs every %.0f s", DISCOVERY_FAST_INTERVAL,
                    )
                else:
                    logger.info(
                        "%d Wi-Fi adapter(s) managed; discovery runs every %.0f s",
                        len(self.devices), DISCOVERY_SLOW_INTERVAL,
                    )
            interval = DISCOVERY_FAST_INTERVAL if searching else DISCOVERY_SLOW_INTERVAL


def _warm_channels(channels: ChannelManager, interfaces: list[str]) -> None:
    for interface in interfaces:
        try:
            channels.get_channels(interface)
        except (CommandError, ValueError) as exc:
            logger.warning("Failed to cache channels for %s: %s", interface, exc)
