"""Unit tests for InstallationMonitor tracking Update entities and auto-cleanup timers."""

from __future__ import annotations

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
