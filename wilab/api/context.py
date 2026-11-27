"""The service's long-lived objects, built once and started in a fixed order (ARCH-5)."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .. import heartbeat
from ..config import AppConfig
from ..devices import Device, DeviceRegistry
from ..network.captive import remove_stale_captive_rules
from ..network.host_guard import remove_stale_guards
from ..network.qos import QosManager
from ..network.qos_profile import QosProfileManager
from ..reservation import ReservationManager
from ..runtime_cleanup import cleanup_runtime
from ..wifi.channels import ChannelManager, set_regulatory_domain
from ..wifi.manager import NetworkManager
from .discovery import DeviceDiscovery

logger = logging.getLogger(__name__)

QOS_CATALOGUE_DIR = Path(__file__).resolve().parent.parent / "data" / "qos-profiles"


def _initial_devices(config: AppConfig) -> list[Device]:
    """Devices managed right after the build: none, the discovery service adds them.

    Kept as a seam so tests can start with the configured interfaces.
    """
    return []


@dataclass
class AppContext:
    """Every singleton of the service, wired explicitly.

    `build` only constructs (no thread, no host command); `start` and `stop` run
    the background work in a fixed order.
    """

    config: AppConfig
    devices: DeviceRegistry
    channels: ChannelManager
    qos: QosManager
    qos_profiles: QosProfileManager
    manager: NetworkManager
    reservations: ReservationManager
    discovery: DeviceDiscovery
    _stop_health: threading.Event = field(default_factory=threading.Event, repr=False)
    _stop_notify: threading.Event = field(default_factory=threading.Event, repr=False)

    @classmethod
    def build(cls, config: AppConfig) -> "AppContext":
        # The one list of managed devices (ARCH-4): discovery adds to it, every
        # manager reads it, and each device carries its own lock.
        devices = DeviceRegistry(_initial_devices(config))
        # One channel cache for the whole service (BUG-4).
        channels = ChannelManager(show_dfs_channels=devices.show_dfs_channels)
        qos = QosManager()
        qos_profiles = QosProfileManager(str(QOS_CATALOGUE_DIR))
        manager = NetworkManager(config, devices, channel_manager=channels)
        manager.qos_manager = qos
        manager.qos_profile_manager = qos_profiles
        reservations = ReservationManager(
            devices, cleanup=manager.release_device,
            cleanup_due=manager.cleanup_due,
            cleanup_wait=manager.cleanup_wait, before_release=manager.cancel_start,
            on_expiry=manager.forget_finished_start,
        )
        manager.expire_reservations = reservations.expire
        devices.on_retire(manager.forget_device)
        discovery = DeviceDiscovery(
            config, devices, channels, retire=lambda device: reservations.retire(device, manager.unused),
        )
        return cls(
            config=config, devices=devices, channels=channels, qos=qos, qos_profiles=qos_profiles,
            manager=manager, reservations=reservations, discovery=discovery,
        )

    def start(self) -> None:
        """Clean up a previous run, then start every background loop; READY=1 last."""
        self.manager.nat_manager.remove_stale_rules()
        remove_stale_captive_rules()
        remove_stale_guards()
        # Processes, runtime files and QoS devices of a previous unclean run (STAB-4).
        cleanup_runtime()

        # Set regulatory domain before any channel query
        set_regulatory_domain(self.config.country_code)

        self.manager.start()  # expiry loop
        self.manager.watchdog.start(self.reservations)
        self.manager.recovery.start_reprobe(self.reservations)

        # Antennas are added by discovery; their channel cache is warmed when added.
        self.discovery.start()

        # Host-command health checks in the background: /status only reads them.
        threading.Thread(
            target=self.manager.health.loop, args=(self._stop_health,), name="health-checks", daemon=True,
        ).start()

        # systemd watchdog (STAB-1): restart only when a loop stalled and Wi-Lab is idle.
        if heartbeat.watchdog_enabled():
            threading.Thread(
                target=heartbeat.notify_loop, args=(self._stop_notify, self.reservations.is_idle),
                name="systemd-watchdog", daemon=True,
            ).start()
        heartbeat.sd_notify("READY=1")

    def stop(self) -> None:
        """Stop the loops in reverse order, then release every antenna (STAB-8)."""
        self._stop_notify.set()
        self._stop_health.set()
        heartbeat.sd_notify("STOPPING=1")
        self.discovery.stop()
        # Gracefully stop any active networks; also ends the watchdog, re-probe and expiry loops.
        try:
            self.manager.shutdown_all()
        except Exception:
            # Never block the teardown, but never hide why the cleanup failed (STAB-8).
            logger.exception("Shutdown cleanup failed")
