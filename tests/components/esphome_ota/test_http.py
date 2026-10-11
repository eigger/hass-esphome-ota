"""Unit tests for multipart firmware upload endpoint."""

from __future__ import annotations

from unittest.mock import patch

from aiohttp import FormData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import DOMAIN
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_manual_firmware_upload(
    hass: HomeAssistant,
    hass_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Test manual multipart binary upload endpoint."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        await manager.device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom.yaml",
            name="livingroom",
            friendly_name="Living Room",
            target_platform="esp32",
        )

        client = await hass_client()

        # 1. Valid binary upload
        form = FormData()
        form.add_field(
            "file",
            mock_builder.binary_blob,
            filename="firmware.ota.bin",
            content_type="application/octet-stream",
        )

        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert data["version"] == "1.0.0"
        assert data["chip_family"] == "ESP32"

        # 2. Corrupted binary upload returns 422
        form_bad = FormData()
        form_bad.add_field(
            "file",
            b"corrupted_binary",
            filename="corrupt.bin",
            content_type="application/octet-stream",
        )
        resp_bad = await client.post("/api/esphome_ota/upload/livingroom", data=form_bad)
        assert resp_bad.status == 422
