"""Unit tests for diagnostics redaction and output."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import DOMAIN
from custom_components.esphome_ota.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_diagnostics_redacts_tokens(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Test diagnostics output redacts secret tokens and confidential URLs."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        await manager.device_manager.async_register_or_update(
            device_id="secret_node",
            configuration="secret_node",
            name="secret_node",
            friendly_name="Secret Node",
            token="super_secret_token_1234567890abcdef",
        )

        diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
        assert "devices" in diag
        assert len(diag["devices"]) >= 1

        sec_dev = next(d for d in diag["devices"] if d["device_id"] == "secret_node")
        assert sec_dev["has_token"] is True
        assert "super_secret_token" not in str(diag)
