"""The ESPHome OTA custom integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .http import FirmwareUploadView
from .manager import OtaConfigEntry, OtaManager
from .storage import STORAGE_CACHE_KEY
from .websocket import async_register_websocket_commands

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the ESPHome OTA component."""
    async_register_websocket_commands(hass)
    # Registered once per HA run; the view resolves the current manager per request
    # so unloading/reloading the entry never leaves a stale manager serving uploads.
    if getattr(hass, "http", None) is not None:
        hass.http.register_view(FirmwareUploadView(hass))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OtaConfigEntry) -> bool:
    """Set up ESPHome OTA from a config entry."""
    manager = OtaManager(hass, entry)
    entry.runtime_data = manager

    try:
        await manager.async_setup()
    except BaseException:
        # Partial setup must not leave the reconnect task, monitor or panel running.
        try:
            await manager.async_unload()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed cleaning up after ESPHome OTA setup error")
        raise

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OtaConfigEntry) -> bool:
    """Unload an ESPHome OTA config entry."""
    await entry.runtime_data.async_unload()
    # Drop cached storage so a reload re-reads from disk.
    hass.data.pop(STORAGE_CACHE_KEY, None)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: OtaConfigEntry) -> None:
    """Reload config entry when options are updated."""
    manager = getattr(entry, "runtime_data", None)
    if manager and manager.should_suppress_reload():
        return
    await hass.config_entries.async_reload(entry.entry_id)
