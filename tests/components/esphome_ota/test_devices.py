"""Unit tests for DeviceManager status tracking, token assignment, and serialization."""

from __future__ import annotations

import asyncio
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.const import (
    DEFAULT_PUBLISH_DIR,
    DEVICE_STATUS_INSTALLED,
    DEVICE_STATUS_NEEDS_INITIAL_INSTALL,
    DEVICE_STATUS_UPDATE_AVAILABLE,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.storage import StorageManager


async def test_device_registration_and_token(hass: HomeAssistant) -> None:
    """Test registering a device mints a 32-char token and stable slug."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)

    dev = await manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )

    assert dev.device_id == "livingroom"
    assert len(dev.token) == 32
    assert dev.slug == f"livingroom_{dev.token}"

    # Updating preserves the minted token
    dev2 = await manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room Renamed",
    )
    assert dev2.token == dev.token


async def test_legacy_device_token_preservation(hass: HomeAssistant) -> None:
    """Test legacy devices without a token retain empty token and un-suffixed slug."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)

    dev = await manager.async_register_or_update(
        device_id="legacy_node",
        configuration="legacy_node",
        name="legacy_node",
        friendly_name="Legacy Node",
        token="",
    )
    assert dev.token == ""
    assert dev.slug == "legacy_node"


async def test_device_status_transitions(hass: HomeAssistant) -> None:
    """Test status transitions: needs_initial_install -> update_available -> installed."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)

    dev = await manager.async_register_or_update(
        device_id="test_node",
        configuration="test_node",
        name="test_node",
        friendly_name="Test Node",
    )

    # 1. Unmanaged / Needs initial install
    assert dev.has_http_ota is False
    assert manager._calculate_status(dev) == DEVICE_STATUS_NEEDS_INITIAL_INSTALL

    # 2. Published 1.0.0, but device hasn't reported installation yet -> still needs initial install
    await manager.async_mark_published(dev.device_id, "1.0.0")
    assert manager._calculate_status(dev) == DEVICE_STATUS_NEEDS_INITIAL_INSTALL

    # 3. Device installs 1.0.0
    await manager.async_mark_installed(dev.device_id, "1.0.0")
    assert manager._calculate_status(dev) == DEVICE_STATUS_INSTALLED

    # 4. New version 1.0.1 published -> update_available
    await manager.async_mark_published(dev.device_id, "1.0.1")
    assert manager._calculate_status(dev) == DEVICE_STATUS_UPDATE_AVAILABLE


async def test_resolve_legacy_configuration_prefers_plain_yaml(
    hass: HomeAssistant,
) -> None:
    """Prefer {node}.yaml over slug-named Builder copies during migration matching."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)
    token = "66538f8029a9436117254bea079c279e"
    manager.update_builder_devices(
        [
            {
                "configuration": f"esp-colorado-tab5_{token}(1).yaml",
                "name": "esp-colorado-tab5",
                "friendly_name": "ESP Colorado TAB5",
                "target_platform": "esp32",
            },
            {
                "configuration": "esp-colorado-tab5.yaml",
                "name": "esp-colorado-tab5",
                "friendly_name": "ESP Colorado TAB5",
                "target_platform": "esp32",
            },
        ]
    )

    device_id, configuration, raw, ambiguous = manager.resolve_legacy_configuration(
        "esp-colorado-tab5", token
    )
    assert device_id == "esp-colorado-tab5"
    assert configuration == "esp-colorado-tab5.yaml"
    assert raw is not None
    assert f"esp-colorado-tab5_{token}(1)" in ambiguous


async def test_resolve_legacy_configuration_falls_back_to_slug_copy(
    hass: HomeAssistant,
) -> None:
    """When only a slug-named copy exists, bind migration to that config."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)
    token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
    manager.update_builder_devices(
        [
            {
                "configuration": f"livingroom_{token}(1).yaml",
                "name": "livingroom",
                "friendly_name": "Living Room",
                "target_platform": "esp32",
            }
        ]
    )

    device_id, configuration, raw, ambiguous = manager.resolve_legacy_configuration(
        "livingroom", token
    )
    assert device_id == f"livingroom_{token}(1)"
    assert configuration == f"livingroom_{token}(1).yaml"
    assert raw is not None
    assert ambiguous == []


async def test_async_remove_device(hass: HomeAssistant) -> None:
    """Removing a managed device clears it from storage-backed inventory."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)
    await manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    removed = await manager.async_remove_device("livingroom")
    assert removed is not None
    assert manager.get_device("livingroom") is None


async def test_device_lock_concurrency(hass: HomeAssistant) -> None:
    """Test device lock serializes concurrent access."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)

    lock1 = manager.get_lock("livingroom")
    lock2 = manager.get_lock("livingroom")
    assert lock1 is lock2

    execution_order: list[int] = []

    async def _worker(worker_id: int, delay: float) -> None:
        async with lock1:
            execution_order.append(worker_id)
            await asyncio.sleep(delay)

    await asyncio.gather(_worker(1, 0.05), _worker(2, 0.01))
    assert execution_order == [1, 2]


async def test_list_all_has_public_binary(hass: HomeAssistant) -> None:
    """Device list_all accurately reports has_public_binary reflecting filesystem state."""
    storage = StorageManager(hass)
    manager = DeviceManager(hass, storage)

    dev = await manager.async_register_or_update(
        device_id="office",
        configuration="office.yaml",
        name="office",
        friendly_name="Office Sensor",
    )

    # 1. Without public binary file
    devices = manager.list_all()
    dev_entry = next(d for d in devices if d["device_id"] == "office")
    assert dev_entry["has_public_binary"] is False

    # 2. When public binary file exists in www/DEFAULT_PUBLISH_DIR
    pub_dir = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    pub_dir.mkdir(parents=True, exist_ok=True)
    bin_file = pub_dir / f"{dev.slug}.ota.bin"
    bin_file.write_bytes(b"dummy")

    devices = manager.list_all()
    dev_entry = next(d for d in devices if d["device_id"] == "office")
    assert dev_entry["has_public_binary"] is True

    # 3. When binary is deactivated / removed
    bin_file.unlink()
    devices = manager.list_all()
    dev_entry = next(d for d in devices if d["device_id"] == "office")
    assert dev_entry["has_public_binary"] is False
