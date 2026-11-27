"""The managed Wi-Fi devices: one registry shared by every manager (ARCH-4).

Discovery adds devices, and retires one whose interface stayed gone while
nothing used it (WD-5). The configuration only holds the labels of config.yaml
(display names, disable, show_dfs_channels).
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from threading import RLock


@dataclass(eq=False)
class Device:
    """A managed Wi-Fi interface, as discovery found it."""

    interface: str
    display_name: str
    # Detected from sysfs; set only for USB adapters (USB recovery resets this port).
    usb_port: str | None = None
    # Kernel driver (mt7921u, rtw88_8822bu, ...): selects the watchdog budget of config.yaml.
    driver: str | None = None
    # DFS channels (5 GHz 52-144) are listed and accepted only when true.
    show_dfs_channels: bool = True
    # Serializes start, stop, status, cleanup, restore and USB recovery of this device.
    lock: RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def device_id(self) -> str:
        """Stable internal identifier: the interface name."""
        return self.interface


class DeviceRegistry:
    """The managed devices, in the order they were added (thread-safe).

    The order is the allocation order of reservations and of DHCP subnets.
    """

    def __init__(self, devices: Iterable[Device] = ()) -> None:
        self._guard = threading.RLock()
        self._devices: dict[str, Device] = {}
        # Locks handed out for interfaces not managed (yet); a device added later adopts its lock.
        self._unmanaged_locks: dict[str, RLock] = {}
        self._subscribers: list[Callable[[Device], None]] = []
        self._retire_subscribers: list[Callable[[Device], None]] = []
        for device in devices:
            self.add(device)

    def add(self, device: Device) -> None:
        """Manage *device* from now on; subscribers are told under the registry lock."""
        with self._guard:
            if device.interface in self._devices:
                raise ValueError(f"Device {device.interface} is already managed")
            lock = self._unmanaged_locks.pop(device.interface, None)
            if lock is not None:
                device.lock = lock
            self._devices[device.interface] = device
            for callback in self._subscribers:
                callback(device)

    def subscribe(self, callback: Callable[[Device], None]) -> None:
        """Call *callback* once for every device: those managed now and each one added later."""
        with self._guard:
            self._subscribers.append(callback)
            for device in self._devices.values():
                callback(device)

    def on_retire(self, callback: Callable[[Device], None]) -> None:
        """Call *callback* for each device retired from now on (under the registry lock)."""
        with self._guard:
            self._retire_subscribers.append(callback)

    def retire(self, interface: str) -> Device | None:
        """Stop managing *interface* (WD-5); the caller checked that nothing uses it.

        If the interface comes back, discovery adds it again as a new device.
        """
        with self._guard:
            device = self._devices.pop(interface, None)
            if device is not None:
                for callback in self._retire_subscribers:
                    callback(device)
            return device

    def get(self, interface: str) -> Device | None:
        with self._guard:
            return self._devices.get(interface)

    def all(self) -> list[Device]:
        with self._guard:
            return list(self._devices.values())

    def ids(self) -> list[str]:
        with self._guard:
            return list(self._devices)

    def lock(self, interface: str) -> RLock:
        """The lock that serializes every lifecycle operation of one device.

        An interface not managed gets a lock of its own too, which the device
        keeps if discovery adds it later.
        """
        with self._guard:
            device = self._devices.get(interface)
            if device is not None:
                return device.lock
            return self._unmanaged_locks.setdefault(interface, threading.RLock())

    def show_dfs_channels(self, interface: str) -> bool:
        """`show_dfs_channels` of a device; true for an interface not managed."""
        device = self.get(interface)
        return True if device is None else device.show_dfs_channels

    def __contains__(self, interface: object) -> bool:
        with self._guard:
            return interface in self._devices

    def __len__(self) -> int:
        with self._guard:
            return len(self._devices)
