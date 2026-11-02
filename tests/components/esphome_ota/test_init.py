"""Unit tests for ESPHome OTA component setup, unloading, and options updating."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import DOMAIN
from custom_components.esphome_ota.diagnostics import (
    async_get_config_entry_diagnostics,
)
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

        assert hass.config_entries.async_entries(DOMAIN)[0].runtime_data is not None
        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        assert manager is not None
        assert manager.panel_manager._panel_registered is True

        # Unload
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert not hasattr(mock_config_entry, "runtime_data")
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

        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        assert manager.base_url == "https://new-url.duckdns.org"
        assert manager.cleanup_hours == 24


_DISCOVERY = "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all"
_FLOW_DISCOVERY = (
    "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all"
)


async def test_manager_reachable_during_setup_and_gone_after_unload(
    hass: HomeAssistant,
    hass_client,
    mock_config_entry: MockConfigEntry,
) -> None:
    """WS sees the manager while setup runs; HTTP stays 503 until it is ready."""
    from custom_components.esphome_ota.manager import OtaManager, get_loaded_manager
    from custom_components.esphome_ota.websocket import _get_manager

    mock_config_entry.add_to_hass(hass)
    original = OtaManager.async_setup
    seen: dict = {}

    async def _setup(self) -> None:
        client = await hass_client()
        seen["state"] = mock_config_entry.state
        seen["ws"] = _get_manager(hass) is self
        seen["ready"] = self.ready
        resp = await client.post("/api/esphome_ota/upload/x", data=b"")
        seen["http"] = resp.status
        await original(self)

    with (
        patch(_DISCOVERY, return_value=[]),
        patch.object(OtaManager, "async_setup", _setup),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert seen["state"] is ConfigEntryState.SETUP_IN_PROGRESS
    assert seen["ws"] is True
    assert seen["ready"] is False
    assert seen["http"] == 503

    manager = mock_config_entry.runtime_data
    events: list[str] = []
    manager.add_subscriber(lambda event, data: events.append(event))
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert events == ["unloaded"]
    assert get_loaded_manager(hass) is None
    assert (await async_get_config_entry_diagnostics(hass, mock_config_entry)) == {
        "status": "unloaded"
    }


async def test_failed_setup_reports_unloaded(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """After a failed setup the cleaned-up manager is neither served nor diagnosed."""
    from custom_components.esphome_ota.manager import get_loaded_manager

    mock_config_entry.add_to_hass(hass)
    with (
        patch(_DISCOVERY, return_value=[]),
        patch(
            "custom_components.esphome_ota.manager.InstallationMonitor.async_setup",
            side_effect=RuntimeError("boom"),
        ),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert get_loaded_manager(hass) is None
    assert (await async_get_config_entry_diagnostics(hass, mock_config_entry)) == {
        "status": "unloaded"
    }


async def test_options_save_reloads_once_and_not_when_unchanged(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A real options save reloads the loaded entry once; an identical save never."""
    mock_config_entry.add_to_hass(hass)
    with patch(_DISCOVERY, return_value=[]):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        async def _save(hours: int) -> None:
            with patch(_FLOW_DISCOVERY, return_value=[]):
                result = await hass.config_entries.options.async_init(
                    mock_config_entry.entry_id
                )
                await hass.config_entries.options.async_configure(
                    result["flow_id"],
                    {
                        "base_url": "https://my-ha.duckdns.org",
                        "auto_cleanup_hours": hours,
                        "builder_slug": "auto",
                    },
                )
            await hass.async_block_till_done()

        with patch.object(
            hass.config_entries,
            "async_reload",
            wraps=hass.config_entries.async_reload,
        ) as reload_mock:
            await _save(7)
            assert reload_mock.call_count == 1
            await _save(7)
            assert reload_mock.call_count == 1
