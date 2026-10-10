"""WebSocket API commands and event subscriptions for ESPHome OTA."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .config_patch import apply_ota_patch, remove_ota_patch
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register all WebSocket commands for esphome_ota."""
    # Check if already registered
    if "esphome_ota/status" in hass.data.get("websocket_api", {}).get("commands", {}):
        return

    websocket_api.async_register_command(hass, ws_status)
    websocket_api.async_register_command(hass, ws_devices)
    websocket_api.async_register_command(hass, ws_device_detail)
    websocket_api.async_register_command(hass, ws_prepare_ota)
    websocket_api.async_register_command(hass, ws_apply_ota)
    websocket_api.async_register_command(hass, ws_build)
    websocket_api.async_register_command(hass, ws_batch_build)
    websocket_api.async_register_command(hass, ws_republish)
    websocket_api.async_register_command(hass, ws_deactivate)
    websocket_api.async_register_command(hass, ws_remove_ota)
    websocket_api.async_register_command(hass, ws_cancel_job)
    websocket_api.async_register_command(hass, ws_select_builder)
    websocket_api.async_register_command(hass, ws_reconnect)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_migrate_preview)
    websocket_api.async_register_command(hass, ws_migrate_execute)


def _get_manager(hass: HomeAssistant) -> Any:
    """Retrieve active OtaManager instance."""
    entry_data = hass.data.get(DOMAIN)
    if not entry_data or "manager" not in entry_data:
        raise websocket_api.WebSocketError("not_loaded", "ESPHome OTA is not loaded")
    return entry_data["manager"]


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/status",
    }
)
@websocket_api.async_response
async def ws_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return status of Builder connection and general configuration."""
    manager = _get_manager(hass)
    builder_info = None
    if manager.resolver.active_candidate:
        c = manager.resolver.active_candidate
        builder_info = {
            "slug": c.slug,
            "name": c.name,
            "host": c.host,
            "port": c.port,
            "source": c.source,
            "is_running": c.is_running,
            "version": c.version,
        }

    connection.send_result(
        msg["id"],
        {
            "status": manager.resolver.status,
            "builder": builder_info,
            "base_url": manager.base_url,
            "candidates": [
                {
                    "slug": cand.slug,
                    "name": cand.name,
                    "host": cand.host,
                    "port": cand.port,
                    "source": cand.source,
                    "is_running": cand.is_running,
                }
                for cand in manager.resolver.candidates
            ],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/devices",
    }
)
@websocket_api.async_response
async def ws_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return list of all devices."""
    manager = _get_manager(hass)
    devices = manager.device_manager.list_all()
    connection.send_result(msg["id"], {"devices": devices})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/device_detail",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return detailed information, YAML content, and artifact history for device."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    managed = manager.device_manager.get_device(device_id)

    yaml_content = ""
    client = manager.resolver.active_client
    if client:
        try:
            yaml_content = await client.get_config(device_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not get YAML for %s: %s", device_id, err)

    artifacts = await manager.storage.async_load_artifacts()
    art = artifacts.get(device_id)

    connection.send_result(
        msg["id"],
        {
            "device": managed.to_dict() if managed else None,
            "yaml": yaml_content,
            "artifact": art.to_dict() if art else None,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/prepare_ota",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_prepare_ota(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Prepare YAML diff for adding OTA configuration."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    client = manager.resolver.active_client
    if not client:
        connection.send_error(msg["id"], "builder_disconnected", "ESPHome Builder is not connected")
        return

    config_file = manager.device_manager.get_configuration(device_id)
    raw_info = manager.device_manager.get_builder_raw(device_id)
    yaml_content = await client.get_config(config_file)
    dev = manager.device_manager.get_device(device_id)
    if not dev:
        dev_name = raw_info.get("name") if raw_info else device_id.replace(".yaml", "")
        friendly = (raw_info.get("friendly_name") or raw_info.get("name")) if raw_info else dev_name
        plat = raw_info.get("target_platform", "esp32") if raw_info else "esp32"
        dev = await manager.device_manager.async_register_or_update(
            device_id=device_id.replace(".yaml", ""),
            configuration=config_file,
            name=dev_name,
            friendly_name=friendly,
            target_platform=plat,
        )

    target_ver = dev.own_project_version or dev.managed_version or "1.0.0"
    diff_res = apply_ota_patch(
        yaml_content=yaml_content,
        base_url=manager.base_url,
        slug=dev.slug,
        target_version=target_ver,
        node=dev.name,
    )

    connection.send_result(
        msg["id"],
        {
            "diff": diff_res.diff,
            "modified": diff_res.modified,
            "target_version": diff_res.target_version,
            "own_version": diff_res.previous_version,
            "original": yaml_content,
            "expected": yaml_content,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/apply_ota",
        vol.Required("device_id"): str,
        vol.Required("content"): str,
        vol.Optional("expected"): str,
    }
)
@websocket_api.async_response
async def ws_apply_ota(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save modified YAML configuration to Builder with CAS."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    content = msg["content"]
    expected = msg.get("expected")

    client = manager.resolver.active_client
    if not client:
        connection.send_error(msg["id"], "builder_disconnected", "ESPHome Builder is not connected")
        return

    config_file = manager.device_manager.get_configuration(device_id)
    try:
        await client.update_config(config_file, content, expected)
        await manager.refresh_devices()
        await manager.monitor.async_refresh_monitoring()
        connection.send_result(msg["id"], {"success": True})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "apply_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/build",
        vol.Required("device_id"): str,
        vol.Optional("request_id"): str,
    }
)
@websocket_api.async_response
async def ws_build(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Start build & publish pipeline for a device."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    req_id = msg.get("request_id")

    client = manager.resolver.active_client
    if not client:
        connection.send_error(msg["id"], "builder_disconnected", "ESPHome Builder is not connected")
        return

    dev = manager.device_manager.get_device(device_id)
    if not dev:
        config_file = manager.device_manager.get_configuration(device_id)
        raw_info = manager.device_manager.get_builder_raw(device_id)
        dev_name = raw_info.get("name") if raw_info else device_id.replace(".yaml", "")
        friendly = (raw_info.get("friendly_name") or raw_info.get("name")) if raw_info else dev_name
        plat = raw_info.get("target_platform", "esp32") if raw_info else "esp32"
        dev = await manager.device_manager.async_register_or_update(
            device_id=device_id.replace(".yaml", ""),
            configuration=config_file,
            name=dev_name,
            friendly_name=friendly,
            target_platform=plat,
        )

    try:
        job_id = await manager.job_runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url=manager.base_url,
            request_id=req_id,
        )
        connection.send_result(msg["id"], {"job_id": job_id})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "build_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/batch_build",
        vol.Required("device_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_batch_build(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Queue batch builds for multiple devices."""
    manager = _get_manager(hass)
    device_ids = msg["device_ids"]
    client = manager.resolver.active_client
    if not client:
        connection.send_error(msg["id"], "builder_disconnected", "ESPHome Builder is not connected")
        return

    job_ids: dict[str, str] = {}
    for dev_id in device_ids:
        dev = manager.device_manager.get_device(dev_id)
        if not dev:
            config_file = manager.device_manager.get_configuration(dev_id)
            raw_info = manager.device_manager.get_builder_raw(dev_id)
            dev_name = raw_info.get("name") if raw_info else dev_id.replace(".yaml", "")
            friendly = (raw_info.get("friendly_name") or raw_info.get("name")) if raw_info else dev_name
            plat = raw_info.get("target_platform", "esp32") if raw_info else "esp32"
            dev = await manager.device_manager.async_register_or_update(
                device_id=dev_id.replace(".yaml", ""),
                configuration=config_file,
                name=dev_name,
                friendly_name=friendly,
                target_platform=plat,
            )
        try:
            j_id = await manager.job_runner.async_start_build_pipeline(
                device=dev, client=client, base_url=manager.base_url
            )
            job_ids[dev_id] = j_id
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Batch build error for %s: %s", dev_id, err)

    connection.send_result(msg["id"], {"jobs": job_ids})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/republish",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_republish(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Republish existing private artifact without re-building."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    dev = manager.device_manager.get_device(device_id)
    if not dev:
        connection.send_error(msg["id"], "device_not_found", "Device not found")
        return

    artifacts = await manager.storage.async_load_artifacts()
    art = artifacts.get(device_id)
    if not art:
        connection.send_error(msg["id"], "no_artifact", "No private artifact exists for this device")
        return

    try:
        published = await manager.job_runner.async_republish(dev, art)
        connection.send_result(msg["id"], {"success": True, "version": published.version})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "republish_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/deactivate",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_deactivate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Hide/remove public binary from /local."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    dev = manager.device_manager.get_device(device_id)
    if not dev:
        connection.send_error(msg["id"], "device_not_found", "Device not found")
        return

    removed = await manager.publisher.async_deactivate(dev.slug)
    connection.send_result(msg["id"], {"success": True, "removed": removed})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/remove_ota",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_ota(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove managed OTA config from YAML and drop the managed device record."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    dev = manager.device_manager.get_device(device_id)
    if not dev:
        connection.send_error(msg["id"], "device_not_found", "Device not found")
        return

    yaml_removed = False
    client = manager.resolver.active_client
    if client:
        config_file = manager.device_manager.get_configuration(device_id)
        try:
            yaml_content = await client.get_config(config_file)
            cleaned, yaml_removed = remove_ota_patch(yaml_content)
            if yaml_removed:
                await client.update_config(config_file, cleaned, expected=yaml_content)
        except Exception as err:  # noqa: BLE001
            connection.send_error(msg["id"], "remove_failed", str(err))
            return

    binary_removed = await manager.publisher.async_deactivate(dev.slug)

    artifacts = await manager.storage.async_load_artifacts()
    if device_id in artifacts or dev.device_id in artifacts:
        artifacts.pop(device_id, None)
        artifacts.pop(dev.device_id, None)
        await manager.storage.async_save_artifacts(artifacts)

    await manager.device_manager.async_remove_device(dev.device_id)
    await manager.refresh_devices()
    await manager.monitor.async_refresh_monitoring()
    manager._dispatch_event(
        "devices_updated",
        {"devices": manager.device_manager.list_all()},
    )
    connection.send_result(
        msg["id"],
        {
            "success": True,
            "yaml_removed": yaml_removed,
            "binary_removed": binary_removed,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/cancel_job",
        vol.Required("job_id"): str,
    }
)
@websocket_api.async_response
async def ws_cancel_job(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Cancel an active pipeline job."""
    manager = _get_manager(hass)
    job_id = msg["job_id"]
    client = manager.resolver.active_client
    await manager.job_runner.async_cancel_job(job_id, client)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/select_builder",
        vol.Required("slug"): str,
    }
)
@websocket_api.async_response
async def ws_select_builder(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Select a builder candidate, persist selection, and reconnect."""
    manager = _get_manager(hass)
    slug = msg["slug"]
    try:
        await manager.async_select_builder(slug)
        connection.send_result(
            msg["id"], {"status": manager.resolver.status, "selected": slug}
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "select_builder_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/reconnect",
        vol.Optional("slug"): str,
    }
)
@websocket_api.async_response
async def ws_reconnect(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force re-discovery and re-connection to Builder."""
    manager = _get_manager(hass)
    slug = msg.get("slug")
    try:
        if slug is not None:
            await manager.async_select_builder(slug)
        else:
            await manager.async_reconnect()
        connection.send_result(msg["id"], {"status": manager.resolver.status})
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "reconnect_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/subscribe",
    }
)
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to real-time events and receive initial snapshot."""
    manager = _get_manager(hass)

    @callback
    def _send_event(event_type: str, data: dict[str, Any]) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {"event": event_type, "data": data},
            )
        )

    unsub = manager.add_subscriber(_send_event)
    connection.subscriptions[msg["id"]] = unsub

    # Initial snapshot acknowledge
    snapshot_payload = {
        "status": manager.resolver.status,
        "devices": manager.device_manager.list_all(),
        "jobs": [j.to_dict() for j in manager.job_runner.list_jobs()],
    }
    connection.send_result(msg["id"], snapshot_payload)

    # Dispatch snapshot as an event so frontend subscribeMessage callbacks receive it
    _send_event("snapshot", snapshot_payload)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/migrate_preview",
    }
)
@websocket_api.async_response
async def ws_migrate_preview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Preview legacy add-on migration items."""
    manager = _get_manager(hass)
    preview = await manager.migration_manager.async_preview()
    connection.send_result(msg["id"], preview)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/migrate_execute",
    }
)
@websocket_api.async_response
async def ws_migrate_execute(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Execute migration from legacy add-on."""
    manager = _get_manager(hass)
    result = await manager.migration_manager.async_migrate()
    manager._dispatch_event(
        "devices_updated",
        {"devices": manager.device_manager.list_all()},
    )
    connection.send_result(msg["id"], result)
