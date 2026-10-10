"""Unit tests for InstallationMonitor tracking Update entities and auto-cleanup timers."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.monitor import InstallationMonitor
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager


async def test_installation_state_change_tracking(hass: HomeAssistant) -> None:
    """Test monitor marks device installed when update entity matches published version."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_test")

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )
    await device_manager.async_mark_published("livingroom", "2.0.0")

    events: list[dict] = []
    monitor = InstallationMonitor(
        hass,
        device_manager,
        publisher,
        cleanup_hours=12,
        event_callback=lambda e, d: events.append(d),
    )

    # Register an update entity in HA entity registry
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="livingroom_ota_update",
        suggested_object_id="livingroom_firmware",
    )

    await monitor.async_setup()

    # 1. State change to in_progress=True (flashing) -> not installed yet
    hass.states.async_set(
        "update.livingroom_firmware",
        "on",
        {"installed_version": "1.0.0", "latest_version": "2.0.0", "in_progress": True},
    )
    await hass.async_block_till_done()
    updated_dev = device_manager.get_device("livingroom")
    assert updated_dev.last_installed_version is None

    # 2. State change to unavailable -> ignored
    hass.states.async_set(
        "update.livingroom_firmware",
        "unavailable",
        {},
    )
    await hass.async_block_till_done()

    # 3. State change to installed_version == 2.0.0 and in_progress=False -> installation verified!
    hass.states.async_set(
        "update.livingroom_firmware",
        "off",
        {"installed_version": "2.0.0", "latest_version": "2.0.0", "in_progress": False},
    )
    await hass.async_block_till_done()

    verified_dev = device_manager.get_device("livingroom")
    assert verified_dev.last_installed_version == "2.0.0"
    assert verified_dev.has_http_ota is True
    assert verified_dev.update_entity_id == "update.livingroom_firmware"
    assert any(e.get("version") == "2.0.0" for e in events)

    monitor.async_unload()


async def test_auto_cleanup_timer_scheduling(hass: HomeAssistant) -> None:
    """Test scheduling and cancelling cleanup timer."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_test")
    monitor = InstallationMonitor(hass, device_manager, publisher, cleanup_hours=1)

    monitor.schedule_cleanup("livingroom", "livingroom_slug")
    assert "livingroom" in monitor._cleanup_timers

    monitor.cancel_cleanup("livingroom")
    assert "livingroom" not in monitor._cleanup_timers

    monitor.async_unload()


async def test_refresh_entity_triggers_service_call(hass: HomeAssistant) -> None:
    """Test async_refresh_entity triggers homeassistant.update_entity service."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_test")

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )

    monitor = InstallationMonitor(hass, device_manager, publisher)

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="livingroom_ota_update",
        suggested_object_id="livingroom_firmware",
    )

    calls: list[Any] = []

    async def mock_service_call(call) -> None:
        calls.append(call.data)

    hass.services.async_register("homeassistant", "update_entity", mock_service_call)

    await monitor.async_refresh_entity("livingroom")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0] == {"entity_id": "update.livingroom_firmware"}

    monitor.async_unload()


async def test_immediate_sync_of_preexisting_installed_version(hass: HomeAssistant) -> None:
    """Test that an existing update entity in HA states immediately syncs installed version."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_test")

    await device_manager.async_register_or_update(
        device_id="bedroom",
        configuration="bedroom",
        name="bedroom",
        friendly_name="Bedroom Light",
    )

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="bedroom_ota_update",
        suggested_object_id="bedroom_firmware",
    )

    # Entity is already in states before monitor setup
    hass.states.async_set(
        "update.bedroom_firmware",
        "off",
        {"installed_version": "1.2.3", "latest_version": "1.2.3", "in_progress": False},
    )

    monitor = InstallationMonitor(hass, device_manager, publisher)
    await monitor.async_setup()
    await hass.async_block_till_done()

    dev = device_manager.get_device("bedroom")
    assert dev.last_installed_version == "1.2.3"
    assert dev.status == "installed"
    devices = device_manager.list_all()
    b_dev = next(d for d in devices if d["device_id"] == "bedroom")
    assert b_dev["last_installed_version"] == "1.2.3"
    assert b_dev["status"] == "installed"

    monitor.async_unload()


async def test_state_change_without_published_version_updates_installed(hass: HomeAssistant) -> None:
    """Test device reporting an installed version without prior publication records it."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_test")

    await device_manager.async_register_or_update(
        device_id="kitchen",
        configuration="kitchen",
        name="kitchen",
        friendly_name="Kitchen",
    )

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="kitchen_ota_update",
        suggested_object_id="kitchen_firmware",
    )

    monitor = InstallationMonitor(hass, device_manager, publisher)
    await monitor.async_setup()

    # Device comes online and reports installed_version = 1.0.0
    hass.states.async_set(
        "update.kitchen_firmware",
        "off",
        {"installed_version": "1.0.0", "in_progress": False},
    )
    await hass.async_block_till_done()

    dev = device_manager.get_device("kitchen")
    assert dev.last_installed_version == "1.0.0"
    assert dev.status == "installed"

    monitor.async_unload()

