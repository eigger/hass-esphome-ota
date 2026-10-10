"""Unit tests for ESPHome OTA WebSocket API commands and subscription."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
        await manager.device_manager.async_register_or_update(
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


async def test_remove_ota_when_yaml_does_not_exist(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
) -> None:
    """When removing OTA and YAML does not exist, device should simply be dropped from list."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        await manager.device_manager.async_register_or_update(
            device_id="ghost_device",
            configuration="ghost_device.yaml",
            name="ghost_device",
            friendly_name="Ghost Device",
        )

        assert manager.device_manager.get_device("ghost_device") is not None

        ws = await hass_ws_client(hass)
        await ws.send_json(
            {"id": 10, "type": "esphome_ota/remove_ota", "device_id": "ghost_device"}
        )
        msg = await ws.receive_json()

        assert msg["success"] is True
        assert msg["result"]["yaml_removed"] is False
        assert manager.device_manager.get_device("ghost_device") is None
        await ws.close()


async def test_remove_ota_builder_conflict_or_timeout_must_fail(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Builder communication errors (timeout, conflict) must return error and NOT delete device."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        await manager.device_manager.async_register_or_update(
            device_id="conflict_node",
            configuration="conflict_node.yaml",
            name="conflict_node",
            friendly_name="Conflict Node",
        )

        mock_client = AsyncMock()
        mock_client.get_config.return_value = "packages:\n  esphome_ota:\n    ota_slug: abc\n"
        from custom_components.esphome_ota.models import (
            BuilderError,
            BuilderTimeoutError,
            ConfigConflictError,
        )

        mock_client.update_config.side_effect = ConfigConflictError("CAS mismatch")
        manager.resolver.active_client = mock_client

        ws = await hass_ws_client(hass)
        await ws.send_json(
            {"id": 20, "type": "esphome_ota/remove_ota", "device_id": "conflict_node"}
        )
        msg = await ws.receive_json()

        # Must fail and must NOT remove device!
        assert msg["success"] is False
        assert msg["error"]["code"] == "remove_failed"
        assert "CAS mismatch" in msg["error"]["message"]
        assert manager.device_manager.get_device("conflict_node") is not None

        # Also test Builder timeout
        mock_client.get_config.side_effect = BuilderTimeoutError("Command timed out")
        await ws.send_json(
            {"id": 21, "type": "esphome_ota/remove_ota", "device_id": "conflict_node"}
        )
        msg2 = await ws.receive_json()
        assert msg2["success"] is False
        assert msg2["error"]["code"] == "remove_failed"
        assert manager.device_manager.get_device("conflict_node") is not None

        # Permission denied or file open failure must fail and NOT delete device
        mock_client.get_config.side_effect = BuilderError(
            "Failed to open conflict_node.yaml: Permission denied"
        )
        await ws.send_json(
            {"id": 22, "type": "esphome_ota/remove_ota", "device_id": "conflict_node"}
        )
        msg_perm = await ws.receive_json()
        assert msg_perm["success"] is False
        assert msg_perm["error"]["code"] == "remove_failed"
        assert manager.device_manager.get_device("conflict_node") is not None

        # Python PermissionError must also fail
        mock_client.get_config.side_effect = PermissionError("Permission denied")
        await ws.send_json(
            {"id": 23, "type": "esphome_ota/remove_ota", "device_id": "conflict_node"}
        )
        msg_perm2 = await ws.receive_json()
        assert msg_perm2["success"] is False
        assert msg_perm2["error"]["code"] == "remove_failed"
        assert manager.device_manager.get_device("conflict_node") is not None

        # But if Builder explicitly returns file not found, then it should drop from list
        mock_client.get_config.side_effect = BuilderError(
            "Configuration conflict_node.yaml not found"
        )
        await ws.send_json(
            {"id": 24, "type": "esphome_ota/remove_ota", "device_id": "conflict_node"}
        )
        msg3 = await ws.receive_json()
        assert msg3["success"] is True
        assert manager.device_manager.get_device("conflict_node") is None

        await ws.close()


async def test_prepare_ota_includes_project_version_in_package(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Prepare OTA must inject esphome.project into packages.esphome_ota even when YAML has includes."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        manager = hass.data[DOMAIN]["manager"]
        mock_client = AsyncMock()
        mock_client.get_config.return_value = (
            "esphome:\n"
            "  name: bedroom\n"
            "packages:\n"
            "  custom_sensors: !include sensors.yaml\n"
        )
        mock_client.list_devices.return_value = [
            {"configuration": "bedroom.yaml", "name": "bedroom"}
        ]
        manager.resolver.active_client = mock_client

        ws = await hass_ws_client(hass)
        await ws.send_json(
            {"id": 30, "type": "esphome_ota/prepare_ota", "device_id": "bedroom"}
        )
        msg = await ws.receive_json()

        assert msg["success"] is True
        result = msg["result"]
        diff = result["diff"]
        assert "esphome_ota:" in diff
        assert "project:" in diff
        assert "local.bedroom" in diff
        assert result["target_version"] == "1.0.0"

        await ws.close()



