"""Unit tests for ESPHome OTA component setup, unloading, and options updating."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import DOMAIN
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_setup_and_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Test setting up and unloading config entry cleans up panel and connections."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert DOMAIN in hass.data
        manager = hass.data[DOMAIN]["manager"]
        assert manager is not None
        assert manager.panel_manager._panel_registered is True

        # Unload
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert DOMAIN not in hass.data
        assert manager.panel_manager._panel_registered is False


async def test_update_options_reloads_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Test changing options triggers reload."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        hass.config_entries.async_update_entry(
            mock_config_entry,
            options={
                "base_url": "https://new-url.duckdns.org",
                "auto_cleanup_hours": 24,
            },
        )
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        assert manager.base_url == "https://new-url.duckdns.org"
        assert manager.cleanup_hours == 24
