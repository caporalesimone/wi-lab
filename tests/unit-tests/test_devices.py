"""DeviceRegistry: the one list of managed devices (Fable ARCH-4)."""

import pytest

from wilab.devices import Device, DeviceRegistry


def test_devices_keep_the_order_they_were_added():
    registry = DeviceRegistry([Device("wlx-b", "B")])
    registry.add(Device("wlx-a", "A", usb_port="2-1"))

    assert registry.ids() == ["wlx-b", "wlx-a"]
    assert [d.display_name for d in registry.all()] == ["B", "A"]
    assert "wlx-a" in registry and "wlx-c" not in registry
    assert len(registry) == 2
    assert registry.get("wlx-a").usb_port == "2-1"
    assert registry.get("wlx-c") is None


def test_a_device_is_added_once():
    registry = DeviceRegistry([Device("wlx-a", "A")])
    with pytest.raises(ValueError):
        registry.add(Device("wlx-a", "again"))


def test_subscribers_hear_of_every_device_once():
    registry = DeviceRegistry([Device("wlx-a", "A")])
    seen: list[str] = []
    registry.subscribe(lambda device: seen.append(device.interface))
    registry.add(Device("wlx-b", "B"))

    assert seen == ["wlx-a", "wlx-b"]


def test_each_device_has_its_own_lock_and_a_later_device_keeps_its_early_lock():
    registry = DeviceRegistry([Device("wlx-a", "A"), Device("wlx-b", "B")])
    assert registry.lock("wlx-a") is registry.get("wlx-a").lock
    assert registry.lock("wlx-a") is not registry.lock("wlx-b")

    early = registry.lock("wlx-late")   # asked for before discovery adds it
    registry.add(Device("wlx-late", "Late"))
    assert registry.lock("wlx-late") is early


def test_show_dfs_channels_defaults_to_true_for_an_unknown_interface():
    registry = DeviceRegistry([Device("wlx-a", "A", show_dfs_channels=False)])
    assert registry.show_dfs_channels("wlx-a") is False
    assert registry.show_dfs_channels("wlx-other") is True
