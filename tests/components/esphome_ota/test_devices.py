"""Unit tests for DeviceManager status tracking, token assignment, and serialization."""

from __future__ import annotations

import asyncio
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.const import (
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
