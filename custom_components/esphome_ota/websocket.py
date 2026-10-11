"""WebSocket API commands and event subscriptions for ESPHome OTA."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .config_patch import apply_ota_patch, remove_ota_patch, set_package_ota_slug
from .const import DOMAIN
from .firmware import inspect_binary
from .models import (
    BuilderConnectionError,
    BuilderTimeoutError,
    ConfigConflictError,
)

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
    websocket_api.async_register_command(hass, ws_set_token)
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


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    """Return JSON-safe metadata for an ESPHome Builder candidate."""
    version = getattr(candidate, "version", None)
    slug = getattr(candidate, "slug", None)
    name = getattr(candidate, "name", None)
    host = getattr(candidate, "host", None)
    port = getattr(candidate, "port", None)
    source = getattr(candidate, "source", None)
    is_running = getattr(candidate, "is_running", None)
    return {
        "slug": slug if isinstance(slug, str) else None,
        "name": name if isinstance(name, str) else None,
        "host": host if isinstance(host, str) else None,
        "port": port if isinstance(port, int) and not isinstance(port, bool) else None,
        "source": source if isinstance(source, str) else None,
        "is_running": is_running if isinstance(is_running, bool) else None,
        "version": version if isinstance(version, str) else None,
    }


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
        builder_info = _candidate_payload(manager.resolver.active_candidate)

    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)

    connection.send_result(
        msg["id"],
        {
            "status": manager.resolver.status,
            "builder": builder_info,
            "base_url": manager.base_url,
            "candidates": [
                _candidate_payload(candidate)
                for candidate in manager.resolver.candidates
            ],
            "version": version,
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
        connection.send_error(
            msg["id"], "builder_disconnected", "ESPHome Builder is not connected"
        )
        return

    config_file = manager.device_manager.get_configuration(device_id)
    raw_info = manager.device_manager.get_builder_raw(device_id)
    yaml_content = await client.get_config(config_file)
    dev = manager.device_manager.get_device(device_id)
    if not dev:
        dev_name = raw_info.get("name") if raw_info else device_id.replace(".yaml", "")
        friendly = (
            (raw_info.get("friendly_name") or raw_info.get("name"))
            if raw_info
            else dev_name
        )
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
        connection.send_error(
            msg["id"], "builder_disconnected", "ESPHome Builder is not connected"
        )
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
        vol.Optional("target_version"): str,
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
    target_version = msg.get("target_version")

    client = manager.resolver.active_client
    if not client:
        connection.send_error(
            msg["id"], "builder_disconnected", "ESPHome Builder is not connected"
        )
        return

    if target_version is not None:
        target_version = str(target_version).strip()
        if not target_version:
            connection.send_error(
                msg["id"], "invalid_version", "Target version cannot be empty"
            )
            return

    dev = manager.device_manager.get_device(device_id)
    if not dev:
        config_file = manager.device_manager.get_configuration(device_id)
        raw_info = manager.device_manager.get_builder_raw(device_id)
        dev_name = raw_info.get("name") if raw_info else device_id.replace(".yaml", "")
        friendly = (
            (raw_info.get("friendly_name") or raw_info.get("name"))
            if raw_info
            else dev_name
        )
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
            target_version=target_version,
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
        connection.send_error(
            msg["id"], "builder_disconnected", "ESPHome Builder is not connected"
        )
        return

    job_ids: dict[str, str] = {}
    for dev_id in device_ids:
        dev = manager.device_manager.get_device(dev_id)
        if not dev:
            config_file = manager.device_manager.get_configuration(dev_id)
            raw_info = manager.device_manager.get_builder_raw(dev_id)
            dev_name = raw_info.get("name") if raw_info else dev_id.replace(".yaml", "")
            friendly = (
                (raw_info.get("friendly_name") or raw_info.get("name"))
                if raw_info
                else dev_name
            )
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
        connection.send_error(
            msg["id"], "no_artifact", "No private artifact exists for this device"
        )
        return

    try:
        published = await manager.job_runner.async_republish(dev, art)
        connection.send_result(
            msg["id"], {"success": True, "version": published.version}
        )
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
    manager.monitor.cancel_cleanup(device_id)
    connection.send_result(msg["id"], {"success": True, "removed": removed})
    manager._dispatch_event(
        "devices_updated",
        {"devices": manager.device_manager.list_all()},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/set_token",
        vol.Required("device_id"): str,
        vol.Required("token"): str,
    }
)
@websocket_api.async_response
async def ws_set_token(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update device token, synchronizing slug, YAML, and published files."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    new_token = msg["token"].strip()

    clean_dev_id = device_id.replace(".yaml", "")
    async with manager.device_manager.get_lock(clean_dev_id):
        dev = manager.device_manager.get_device(clean_dev_id)
        was_managed = dev is not None
        raw_info = manager.device_manager.get_builder_raw(clean_dev_id)
        if not dev and not raw_info:
            connection.send_error(msg["id"], "device_not_found", "Device not found")
            return

        name = dev.name if dev else (raw_info.get("name") or clean_dev_id)
        configuration = (
            dev.configuration
            if dev
            else manager.device_manager.get_configuration(clean_dev_id)
        )
        friendly_name = (
            dev.friendly_name if dev else (raw_info.get("friendly_name") or name)
        )
        target_platform = (
            dev.target_platform if dev else raw_info.get("target_platform", "esp32")
        )
        old_token = dev.token if dev else ""
        old_slug = dev.slug if dev else name
        new_slug = f"{name}_{new_token}" if new_token else name
        client = manager.resolver.active_client
        original_yaml = updated_yaml = None
        yaml_changed = False
        artifact = None
        new_artifact = None
        new_binary_published = False
        old_binary_deactivation_attempted = False
        cleanup_update_attempted = False
        firmware_blob = None
        binary_info = None
        old_binary_path = manager.publisher.www_dir / f"{old_slug}.ota.bin"
        old_cleanup_delay = None
        old_cleanup_artifact_id = manager.publisher.get_current_artifact_id(old_slug)
        if manager.monitor:
            timer = manager.monitor._cleanup_timers.get(clean_dev_id)
            if timer:
                old_cleanup_delay = max(0.0, timer.when() - hass.loop.time())

        try:
            artifacts = await manager.storage.async_load_artifacts()
            artifact = artifacts.get(clean_dev_id) if dev else None
            if old_slug != new_slug:
                new_binary_path = manager.publisher.www_dir / f"{new_slug}.ota.bin"
                new_md5_path = manager.publisher.www_dir / f"{new_slug}.ota.bin.md5"
                new_manifest_path = manager.publisher.www_dir / f"{new_slug}.json"
                new_ota_manifest_path = (
                    manager.publisher.www_dir / f"{new_slug}.ota.json"
                )
                if any(
                    path.exists()
                    for path in (
                        new_binary_path,
                        new_md5_path,
                        new_manifest_path,
                        new_ota_manifest_path,
                    )
                ):
                    raise RuntimeError(
                        f"The requested public slug '{new_slug}' already has published files; choose a different token."
                    )
                old_public_state_exists = artifact is not None or any(
                    path.exists()
                    for path in (
                        old_binary_path,
                        manager.publisher.www_dir / f"{old_slug}.ota.bin.md5",
                        manager.publisher.www_dir / f"{old_slug}.json",
                        manager.publisher.www_dir / f"{old_slug}.ota.json",
                    )
                )
                if old_public_state_exists and not client:
                    raise RuntimeError(
                        "Reconnect the ESPHome Builder before changing this token; "
                        "an existing firmware artifact or public URL must be synchronized."
                    )
                if old_binary_path.is_file():
                    if not artifact:
                        raise RuntimeError(
                            f"The current public slug '{old_slug}' has no stored artifact record; refusing to rotate the token."
                        )
                    try:
                        firmware_blob = (
                            await manager.publisher.async_load_private_artifact(
                                artifact.private_path
                            )
                        )
                    except Exception as artifact_err:  # noqa: BLE001
                        raise RuntimeError(
                            f"The current artifact for '{old_slug}' cannot be recovered; refusing to rotate the token."
                        ) from artifact_err
                    binary_info = inspect_binary(
                        blob=firmware_blob,
                        target_platform=target_platform,
                        expected_chip=artifact.chip_family,
                        reserved_version=artifact.version,
                    )

            # Prepare the YAML update and keep a rollback copy until all other
            # synchronized state has been updated successfully.
            if client and configuration:
                original_yaml = await client.get_config(configuration)
                updated_yaml, yaml_changed = set_package_ota_slug(
                    original_yaml, new_slug
                )
                already_configured = bool(
                    re.search(
                        rf"^[ \t]*ota_slug\s*:\s*(['\"]?){re.escape(new_slug)}\1\s*(?:#.*)?$",
                        original_yaml,
                        re.MULTILINE,
                    )
                )
                if old_slug != new_slug and not yaml_changed and not already_configured:
                    raise RuntimeError(
                        "Could not establish the requested ota_slug in the Builder YAML. "
                        "The setting may be absent or controlled by an included/external package."
                    )
                if yaml_changed:
                    await client.update_config(
                        configuration, updated_yaml, expected=original_yaml
                    )

            if old_slug != new_slug and artifact and old_binary_path.is_file():
                new_artifact = await manager.publisher.async_publish(
                    device_id=clean_dev_id,
                    configuration=configuration,
                    slug=new_slug,
                    blob=firmware_blob,
                    info=binary_info,
                    title=friendly_name,
                )
                new_binary_published = True
                await manager.storage.async_save_artifact(clean_dev_id, new_artifact)

                # Publish the replacement before hiding the old URL so a failed
                # publication can never leave the device without a working artifact.
                old_binary_deactivation_attempted = True
                if not await manager.publisher.async_deactivate(old_slug):
                    raise RuntimeError(
                        f"Could not deactivate previous public slug '{old_slug}'"
                    )

            if dev:
                dev.token = new_token
                dev.slug = new_slug
                await manager.storage.async_save_devices(
                    manager.device_manager._managed_devices
                )
            else:
                dev = await manager.device_manager.async_register_or_update(
                    device_id=clean_dev_id,
                    configuration=configuration,
                    name=name,
                    friendly_name=friendly_name,
                    target_platform=target_platform,
                    token=new_token,
                )
            if manager.monitor and old_slug != new_slug:
                cleanup_update_attempted = True
                if new_artifact:
                    manager.monitor.schedule_cleanup(
                        clean_dev_id,
                        new_slug,
                        delay_seconds=old_cleanup_delay,
                        artifact_id=new_artifact.published_at,
                    )
                else:
                    manager.monitor.cancel_cleanup(clean_dev_id)
            # Retire stale manifests only after the new state has been committed.
            if old_slug != new_slug:
                try:
                    (manager.publisher.www_dir / f"{old_slug}.json").unlink(
                        missing_ok=True
                    )
                    (manager.publisher.www_dir / f"{old_slug}.ota.json").unlink(
                        missing_ok=True
                    )
                except OSError as cleanup_err:
                    _LOGGER.warning(
                        "Could not remove stale manifests for %s: %s", name, cleanup_err
                    )
        except Exception as err:  # noqa: BLE001
            rollback_errors = []
            if new_binary_published:
                try:
                    await manager.publisher.async_deactivate(new_slug)
                    (manager.publisher.www_dir / f"{new_slug}.json").unlink(
                        missing_ok=True
                    )
                    (manager.publisher.www_dir / f"{new_slug}.ota.json").unlink(
                        missing_ok=True
                    )
                    if artifact:
                        await manager.storage.async_save_artifact(
                            clean_dev_id, artifact
                        )
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            restored_old_artifact = None
            if (
                old_binary_deactivation_attempted
                and artifact
                and firmware_blob
                and binary_info
            ):
                try:
                    restored_old_artifact = await manager.publisher.async_publish(
                        device_id=clean_dev_id,
                        configuration=configuration,
                        slug=old_slug,
                        blob=firmware_blob,
                        info=binary_info,
                        title=friendly_name,
                    )
                    await manager.storage.async_save_artifact(
                        clean_dev_id, restored_old_artifact
                    )
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            if manager.monitor and (
                old_binary_deactivation_attempted or cleanup_update_attempted
            ):
                try:
                    restored_artifact_id = (
                        restored_old_artifact.published_at
                        if restored_old_artifact
                        else artifact.published_at
                        if artifact
                        else old_cleanup_artifact_id
                    )
                    if restored_artifact_id:
                        manager.monitor.schedule_cleanup(
                            clean_dev_id,
                            old_slug,
                            delay_seconds=old_cleanup_delay,
                            artifact_id=restored_artifact_id,
                        )
                    else:
                        manager.monitor.cancel_cleanup(clean_dev_id)
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            if was_managed and dev and (dev.token != old_token or dev.slug != old_slug):
                dev.token = old_token
                dev.slug = old_slug
                try:
                    await manager.storage.async_save_devices(
                        manager.device_manager._managed_devices
                    )
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            elif not was_managed and dev:
                try:
                    await manager.device_manager.async_remove_device(clean_dev_id)
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            if (
                yaml_changed
                and client
                and original_yaml is not None
                and updated_yaml is not None
            ):
                try:
                    await client.update_config(
                        configuration, original_yaml, expected=updated_yaml
                    )
                except Exception as rollback_err:  # noqa: BLE001
                    rollback_errors.append(str(rollback_err))
            detail = str(err)
            if rollback_errors:
                detail += f" (rollback also failed: {'; '.join(rollback_errors)})"
            connection.send_error(msg["id"], "token_update_failed", detail)
            return

        manager._dispatch_event(
            "devices_updated", {"devices": manager.device_manager.list_all()}
        )
        connection.send_result(
            msg["id"], {"success": True, "token": dev.token, "slug": dev.slug}
        )


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

    config_file = manager.device_manager.get_configuration(device_id)
    esphome_file = Path(hass.config.path("esphome", config_file))
    local_file_exists = await hass.async_add_executor_job(esphome_file.is_file)
    client = manager.resolver.active_client

    yaml_removed = False

    if client:
        # Step 1: Query YAML content from Builder
        try:
            yaml_content = await client.get_config(config_file)
        except Exception as err:  # noqa: BLE001
            err_msg = str(err).lower()
            # Explicit read / permission / I/O errors indicate access failure, NOT file absence
            is_permission_or_read_err = isinstance(err, PermissionError) or any(
                term in err_msg
                for term in (
                    "permission denied",
                    "permission",
                    "access denied",
                    "eacces",
                    "eperm",
                    "read error",
                    "io error",
                    "input/output error",
                )
            )
            # ONLY consider file missing if Builder explicitly confirms file absence.
            # Timeout, connection loss, conflict, permission/access errors, etc. MUST fail and not delete records silently!
            is_file_not_found = (
                not is_permission_or_read_err
                and not isinstance(
                    err,
                    (
                        BuilderConnectionError,
                        BuilderTimeoutError,
                        asyncio.TimeoutError,
                        ConfigConflictError,
                    ),
                )
                and (
                    isinstance(err, FileNotFoundError)
                    or any(
                        term in err_msg
                        for term in (
                            "not found",
                            "does not exist",
                            "no such file",
                            "404",
                            "config_not_found",
                        )
                    )
                )
            )
            if is_file_not_found:
                _LOGGER.info(
                    "YAML %s confirmed missing on builder for %s; removing device record directly: %s",
                    config_file,
                    device_id,
                    err,
                )
                yaml_content = None
            else:
                _LOGGER.warning(
                    "Failed fetching YAML %s from builder for %s: %s",
                    config_file,
                    device_id,
                    err,
                )
                connection.send_error(msg["id"], "remove_failed", str(err))
                return

        # Step 2: If YAML exists on Builder, patch it and update config via CAS
        if yaml_content is not None:
            cleaned, yaml_removed = remove_ota_patch(yaml_content)
            if yaml_removed:
                try:
                    await client.update_config(
                        config_file, cleaned, expected=yaml_content
                    )
                except Exception as err:  # noqa: BLE001
                    # Update config errors (e.g. CAS conflict, timeout) must NEVER be ignored!
                    _LOGGER.warning(
                        "Failed updating YAML %s on builder for %s: %s",
                        config_file,
                        device_id,
                        err,
                    )
                    connection.send_error(msg["id"], "remove_failed", str(err))
                    return

    elif local_file_exists:
        try:
            orig_content = await hass.async_add_executor_job(
                esphome_file.read_text, "utf-8"
            )
            cleaned, yaml_removed = remove_ota_patch(orig_content)
            if yaml_removed:
                await hass.async_add_executor_job(
                    esphome_file.write_text, cleaned, "utf-8"
                )
        except Exception as err:  # noqa: BLE001
            connection.send_error(msg["id"], "remove_failed", str(err))
            return
    else:
        # Neither builder client is connected nor local file exists
        _LOGGER.info(
            "YAML %s does not exist for %s; removing device from managed list directly",
            config_file,
            device_id,
        )
        yaml_removed = False

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
@websocket_api.async_response
async def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to real-time events and receive initial snapshot."""
    manager = _get_manager(hass)
    integration = await async_get_integration(hass, DOMAIN)

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
        "builder": _candidate_payload(manager.resolver.active_candidate)
        if manager.resolver.active_candidate
        else None,
        "base_url": manager.base_url,
        "candidates": [
            _candidate_payload(candidate) for candidate in manager.resolver.candidates
        ],
        "version": str(integration.version),
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
