"""Unit tests for ESPHome OTA WebSocket API commands and subscription."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import DOMAIN
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_websocket_api_commands(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Test authenticated admin WebSocket command handlers."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        # Manually register a device for testing
        dev = await manager.device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom",
            name="livingroom",
            friendly_name="Living Room",
        )

        ws = await hass_ws_client(hass)

        # 1. status
        await ws.send_json({"id": 1, "type": "esphome_ota/status"})
        msg = await ws.receive_json()
        assert msg["success"] is True
        assert "status" in msg["result"]
        assert msg["result"]["base_url"] == "https://my-ha.duckdns.org"

        # 2. devices
        await ws.send_json({"id": 2, "type": "esphome_ota/devices"})
        msg = await ws.receive_json()
        assert msg["success"] is True
        devices = msg["result"]["devices"]
        assert len(devices) >= 1
        assert any(d["device_id"] == "livingroom" for d in devices)

        # 3. device_detail
        await ws.send_json(
            {"id": 3, "type": "esphome_ota/device_detail", "device_id": "livingroom"}
        )
        msg = await ws.receive_json()
        assert msg["success"] is True
        assert msg["result"]["device"]["name"] == "livingroom"

        # 4. subscribe
        await ws.send_json({"id": 4, "type": "esphome_ota/subscribe"})
        msg = await ws.receive_json()
        assert msg["success"] is True
        assert "devices" in msg["result"]
        assert "status" in msg["result"]

        # Initial snapshot event
        event_msg = await ws.receive_json()
        assert event_msg["type"] == "event"
        assert event_msg["event"]["event"] == "snapshot"
        assert "devices" in event_msg["event"]["data"]

        # 5. migrate_preview
        await ws.send_json({"id": 5, "type": "esphome_ota/migrate_preview"})
        msg = await ws.receive_json()
        assert msg["success"] is True

        # 6. deactivate
        await ws.send_json(
            {"id": 6, "type": "esphome_ota/deactivate", "device_id": "livingroom"}
        )
        msg = await ws.receive_json()
        assert msg["success"] is True

        await ws.close()
