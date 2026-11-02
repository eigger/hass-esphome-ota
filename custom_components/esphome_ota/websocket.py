"""WebSocket API commands and event subscriptions for ESPHome OTA."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .config_patch import apply_ota_patch, remove_ota_patch, set_package_ota_slug
from .const import DOMAIN
from .firmware import ensure_supported_platform, inspect_binary
from .manager import get_loaded_manager
from .models import (
    BuilderConnectionError,
    BuilderTimeoutError,
    ConfigConflictError,
    UnsupportedPlatformError,
)
from .packages import NODE_RE, TOKEN_RE, VERSION_RE, is_valid_device_id
from .publisher import (
    async_any_path_exists,
    async_path_exists,
    async_path_is_file,
    async_unlink_paths,
)
from .redaction import install_redaction

_LOGGER = logging.getLogger(__name__)
install_redaction(_LOGGER)


def _device_id(value: Any) -> str:
    """Validate a device ID."""
    if not isinstance(value, str) or not is_valid_device_id(value):
        raise vol.Invalid("invalid device_id")
    return value


DEVICE_ID = _device_id
TOKEN = vol.All(str, vol.Strip, vol.Match(TOKEN_RE))
TARGET_VERSION = vol.All(str, vol.Strip, vol.Match(VERSION_RE))


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
    websocket_api.async_register_command(hass, ws_set_publication_policy)
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
    manager = get_loaded_manager(hass)
    if manager is None:
        raise websocket_api.WebSocketError("not_loaded", "ESPHome OTA is not loaded")
    return manager


def _ensure_platform_supported(manager: Any, device_id: str) -> None:
    """Raise UnsupportedPlatformError before registering or touching an RP device."""
    dev = manager.device_manager.get_device(device_id)
    if dev:
        ensure_supported_platform(dev.target_platform)
        return
    raw_info = manager.device_manager.get_builder_raw(device_id)
    if raw_info:
        ensure_supported_platform(raw_info.get("target_platform") or "")


async def _async_ensure_managed_device(manager: Any, device_id: str) -> Any | None:
    """Return the managed device, registering it from Builder info if needed.

    Returns None when the device is unknown to the Builder or its name is not a
    valid node name, so arbitrary IDs are never registered as managed devices.
    """
    dev = manager.device_manager.get_device(device_id)
    if dev:
        return dev
    raw_info = manager.device_manager.get_builder_raw(device_id)
    if not raw_info:
        return None
    dev_name = raw_info.get("name")
    if not isinstance(dev_name, str) or not NODE_RE.match(dev_name):
        return None
    return await manager.device_manager.async_register_or_update(
        device_id=device_id.replace(".yaml", ""),
        configuration=manager.device_manager.get_configuration(device_id),
        name=dev_name,
        friendly_name=raw_info.get("friendly_name") or dev_name,
        target_platform=raw_info.get("target_platform", "esp32"),
    )


def _www_path(www_dir: Path, filename: str) -> Path:
    """Return a path inside the public directory or raise ValueError."""
    path = www_dir / filename
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError(f"Path escapes the public directory: {filename}")
    return path


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
        vol.Required("type"): "esphome_ota/set_publication_policy",
        vol.Required("device_id"): DEVICE_ID,
        vol.Required("cleanup_hours"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=168)
        ),
        vol.Required("auto_hide"): bool,
        vol.Optional("save_as_default", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_set_publication_policy(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply visibility policy to the active publication and optionally save its default."""
    manager = _get_manager(hass)
    device_id = msg["device_id"]
    async with manager.device_manager.get_lock(device_id):
        dev = manager.device_manager.get_device(device_id)
        if not dev:
            connection.send_error(msg["id"], "device_not_found", "Device not found")
            return
        cleanup_hours = msg["cleanup_hours"]
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(hours=cleanup_hours)).isoformat()
            if cleanup_hours > 0
            else None
        )
        artifacts = await manager.storage.async_load_artifacts()
        art = artifacts.get(device_id)
        if msg.get("save_as_default"):
            dev.publication_cleanup_hours = cleanup_hours
            dev.auto_hide = msg["auto_hide"]
            dev.updated_at = datetime.now(timezone.utc).isoformat()
        saved = False
        try:
            if art:
                # The artifact-store lock serializes this policy update with expiry
                # transitions while preserving whichever visibility state won.
                latest = await manager.storage.async_update_artifact_policy_if_current(
                    device_id,
                    art.published_at,
                    cleanup_hours=cleanup_hours,
                    expires_at=expires_at,
                    auto_hide=msg["auto_hide"],
                )
                if not latest:
                    connection.send_error(
                        msg["id"],
                        "publication_changed",
                        "The publication changed; reload and try again.",
                    )
                    return
                if manager.monitor:
                    if latest.is_public:
                        manager.monitor.schedule_cleanup(
                            device_id,
                            dev.slug,
                            artifact_id=latest.published_at,
                            expires_at=expires_at,
                            cleanup_hours=cleanup_hours,
                        )
                    else:
                        manager.monitor.cancel_cleanup(device_id)
            if msg.get("save_as_default") or art:
                dev.expires_at = expires_at
                await manager.storage.async_save_devices(
                    manager.device_manager.managed_devices
                )
                saved = True
        finally:
            if msg.get("save_as_default") and not saved:
                # Defaults are already applied in memory; persist them even
                # when the publication update is aborted or raises.
                await manager.storage.async_save_devices(
                    manager.device_manager.managed_devices
                )
    connection.send_result(msg["id"], {"success": True, "expires_at": expires_at})
    manager.dispatch_event(
        "devices_updated", {"devices": manager.device_manager.list_all()}
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
        vol.Required("device_id"): DEVICE_ID,
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
            "default_cleanup_hours": manager.cleanup_hours,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/prepare_ota",
        vol.Required("device_id"): DEVICE_ID,
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

    try:
        _ensure_platform_supported(manager, device_id)
    except UnsupportedPlatformError as err:
        connection.send_error(msg["id"], "unsupported_platform", str(err))
        return
    dev = await _async_ensure_managed_device(manager, device_id)
    if not dev:
        connection.send_error(msg["id"], "device_not_found", "Device not found")
        return
    config_file = manager.device_manager.get_configuration(device_id)
    yaml_content = await client.get_config(config_file)

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
        vol.Required("device_id"): DEVICE_ID,
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

    try:
        _ensure_platform_supported(manager, device_id)
    except UnsupportedPlatformError as err:
        connection.send_error(msg["id"], "unsupported_platform", str(err))
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
        vol.Required("device_id"): DEVICE_ID,
        vol.Optional("request_id"): str,
        vol.Optional("target_version"): TARGET_VERSION,
        vol.Optional("cleanup_hours"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=168)
        ),
        vol.Optional("auto_hide"): bool,
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

    try:
        _ensure_platform_supported(manager, device_id)
    except UnsupportedPlatformError as err:
        connection.send_error(msg["id"], "unsupported_platform", str(err))
        return
    dev = await _async_ensure_managed_device(manager, device_id)
    if not dev:
        connection.send_error(msg["id"], "device_not_found", "Device not found")
        return

    try:
        job_id = await manager.job_runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url=manager.base_url,
            request_id=req_id,
            target_version=target_version,
            cleanup_hours=msg.get("cleanup_hours"),
            auto_hide=msg.get("auto_hide"),
        )
        connection.send_result(msg["id"], {"job_id": job_id})
    except UnsupportedPlatformError as err:
        connection.send_error(msg["id"], "unsupported_platform", str(err))
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "build_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/batch_build",
        vol.Required("device_ids"): [DEVICE_ID],
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
    errors: dict[str, str] = {}
    for dev_id in device_ids:
        try:
            _ensure_platform_supported(manager, dev_id)
        except UnsupportedPlatformError as err:
            _LOGGER.warning("Batch build skipped %s: %s", dev_id, err)
            errors[dev_id] = "unsupported_platform"
            continue
        dev = await _async_ensure_managed_device(manager, dev_id)
        if not dev:
            _LOGGER.warning("Batch build skipped unknown device %s", dev_id)
            continue
        try:
            j_id = await manager.job_runner.async_start_build_pipeline(
                device=dev, client=client, base_url=manager.base_url
            )
            job_ids[dev_id] = j_id
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Batch build error for %s: %s", dev_id, err)

    result: dict[str, Any] = {"jobs": job_ids}
    if errors:
        result["errors"] = errors
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/republish",
        vol.Required("device_id"): DEVICE_ID,
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
            msg["id"],
            {
                "success": True,
                "version": published.version,
                "expires_at": published.expires_at,
                "cleanup_hours": published.cleanup_hours,
                "auto_hide": published.auto_hide,
            },
        )
    except Exception as err:  # noqa: BLE001
        connection.send_error(msg["id"], "republish_failed", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/deactivate",
        vol.Required("device_id"): DEVICE_ID,
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
    async with manager.device_manager.get_lock(device_id):
        dev = manager.device_manager.get_device(device_id)
        if not dev:
            connection.send_error(msg["id"], "device_not_found", "Device not found")
            return

        artifacts = await manager.storage.async_load_artifacts()
        art = artifacts.get(device_id)
        removed = await manager.publisher.async_deactivate(
            dev.slug,
            expected_artifact_id=art.published_at if art else None,
        )
        public_bin = (
            Path(art.public_bin_path)
            if art and art.public_bin_path
            else manager.publisher.www_dir / f"{dev.slug}.ota.bin"
        )
        if not await async_path_exists(hass, public_bin):
            public_bin = manager.publisher.www_dir / f"{dev.slug}.ota.bin"
        is_private = removed or not await async_path_exists(hass, public_bin)
        if is_private and manager.monitor:
            manager.monitor.cancel_cleanup(device_id)
        if art and is_private:
            art.is_public = False
            art.public_bin_path = None
            await manager.storage.async_save_artifact(device_id, art)
        if is_private:
            dev.expires_at = None
            await manager.storage.async_save_devices(
                manager.device_manager.managed_devices
            )
    connection.send_result(msg["id"], {"success": True, "removed": removed})
    manager.dispatch_event(
        "devices_updated",
        {"devices": manager.device_manager.list_all()},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/set_token",
        vol.Required("device_id"): DEVICE_ID,
        vol.Required("token"): TOKEN,
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
        if not isinstance(name, str) or not NODE_RE.match(name):
            connection.send_error(msg["id"], "invalid_name", "Invalid device name")
            return
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
        www_dir = manager.publisher.www_dir
        try:
            old_binary_path = _www_path(www_dir, f"{old_slug}.ota.bin")
            old_md5_path = _www_path(www_dir, f"{old_slug}.ota.bin.md5")
            old_manifest_path = _www_path(www_dir, f"{old_slug}.json")
            old_ota_manifest_path = _www_path(www_dir, f"{old_slug}.ota.json")
        except ValueError:
            connection.send_error(
                msg["id"], "invalid_stored_slug", "Stored device slug is invalid"
            )
            return
        try:
            new_binary_path = _www_path(www_dir, f"{new_slug}.ota.bin")
            new_md5_path = _www_path(www_dir, f"{new_slug}.ota.bin.md5")
            new_manifest_path = _www_path(www_dir, f"{new_slug}.json")
            new_ota_manifest_path = _www_path(www_dir, f"{new_slug}.ota.json")
        except ValueError:
            connection.send_error(msg["id"], "invalid_name", "Invalid device name")
            return
        old_cleanup_artifact_id = manager.publisher.get_current_artifact_id(old_slug)

        try:
            artifacts = await manager.storage.async_load_artifacts()
            artifact = artifacts.get(clean_dev_id) if dev else None
            if old_slug != new_slug:
                if await async_any_path_exists(
                    hass,
                    new_binary_path,
                    new_md5_path,
                    new_manifest_path,
                    new_ota_manifest_path,
                ):
                    raise RuntimeError(
                        f"The requested public slug '{new_slug}' already has published files; choose a different token."
                    )
                old_public_state_exists = artifact is not None or (
                    await async_any_path_exists(
                        hass,
                        old_binary_path,
                        old_md5_path,
                        old_manifest_path,
                        old_ota_manifest_path,
                    )
                )
                if old_public_state_exists and not client:
                    raise RuntimeError(
                        "Reconnect the ESPHome Builder before changing this token; "
                        "an existing firmware artifact or public URL must be synchronized."
                    )
                if await async_path_is_file(hass, old_binary_path):
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
                    binary_info = await hass.async_add_executor_job(
                        partial(
                            inspect_binary,
                            blob=firmware_blob,
                            target_platform=target_platform,
                            expected_chip=artifact.chip_family,
                            reserved_version=artifact.version,
                        )
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

            if (
                old_slug != new_slug
                and artifact
                and await async_path_is_file(hass, old_binary_path)
            ):
                cleanup_hours = (
                    artifact.cleanup_hours
                    if artifact.cleanup_hours is not None
                    else manager.cleanup_hours
                )
                new_artifact = await manager.publisher.async_publish(
                    device_id=clean_dev_id,
                    configuration=configuration,
                    slug=new_slug,
                    blob=firmware_blob,
                    info=binary_info,
                    title=friendly_name,
                    cleanup_hours=cleanup_hours,
                    auto_hide=artifact.auto_hide,
                )
                # A token rotation changes the URL only; preserve the current
                # publication's original deadline instead of extending it.
                new_artifact.cleanup_hours = cleanup_hours
                new_artifact.expires_at = artifact.expires_at
                new_artifact.auto_hide = artifact.auto_hide
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
                if new_artifact:
                    dev.expires_at = new_artifact.expires_at
                await manager.storage.async_save_devices(
                    manager.device_manager.managed_devices
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
                        artifact_id=new_artifact.published_at,
                        expires_at=new_artifact.expires_at,
                        cleanup_hours=new_artifact.cleanup_hours,
                    )
                else:
                    manager.monitor.cancel_cleanup(clean_dev_id)
            # Retire stale manifests only after the new state has been committed.
            if old_slug != new_slug:
                try:
                    await async_unlink_paths(
                        hass,
                        old_manifest_path,
                        old_ota_manifest_path,
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
                    await async_unlink_paths(
                        hass,
                        new_manifest_path,
                        new_ota_manifest_path,
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
                        cleanup_hours=(
                            artifact.cleanup_hours
                            if artifact.cleanup_hours is not None
                            else manager.cleanup_hours
                        ),
                        auto_hide=artifact.auto_hide,
                    )
                    restored_old_artifact.cleanup_hours = artifact.cleanup_hours
                    restored_old_artifact.expires_at = artifact.expires_at
                    restored_old_artifact.auto_hide = artifact.auto_hide
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
                            artifact_id=restored_artifact_id,
                            expires_at=(
                                restored_old_artifact.expires_at
                                if restored_old_artifact
                                else artifact.expires_at
                                if artifact
                                else None
                            ),
                            cleanup_hours=(
                                restored_old_artifact.cleanup_hours
                                if restored_old_artifact
                                else artifact.cleanup_hours
                                if artifact
                                else None
                            ),
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
                        manager.device_manager.managed_devices
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

        manager.dispatch_event(
            "devices_updated", {"devices": manager.device_manager.list_all()}
        )
        connection.send_result(
            msg["id"], {"success": True, "token": dev.token, "slug": dev.slug}
        )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "esphome_ota/remove_ota",
        vol.Required("device_id"): DEVICE_ID,
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

    # Stop in-flight builds first (they hold the device lock while running),
    # then serialize the removal against other mutations of this device.
    # Cancelling before the YAML step is intentional: the build would otherwise
    # hold the lock and could publish a binary for a device being removed, so
    # a later failure of the removal leaves those jobs cancelled.
    await manager.job_runner.async_cancel_device_jobs(
        dev.device_id, manager.resolver.active_client
    )
    async with manager.device_manager.get_lock(dev.device_id):
        await _remove_ota_locked(hass, connection, msg, manager, dev)


async def _remove_ota_locked(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    manager: Any,
    dev: Any,
) -> None:
    """Remove managed OTA config while holding the device lock."""
    # Jobs queued behind the lock before we acquired it are not holding it, so
    # cancelling them again here cannot deadlock.
    await manager.job_runner.async_cancel_device_jobs(
        dev.device_id, manager.resolver.active_client
    )
    device_id = msg["device_id"]
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

    manager.monitor.cancel_cleanup(dev.device_id)
    binary_removed = await manager.publisher.async_deactivate(dev.slug)
    await manager.publisher.async_delete_private_artifacts(dev.device_id)

    artifacts = await manager.storage.async_load_artifacts()
    if device_id in artifacts or dev.device_id in artifacts:
        artifacts.pop(device_id, None)
        artifacts.pop(dev.device_id, None)
        await manager.storage.async_save_artifacts(artifacts)

    await manager.device_manager.async_remove_device(dev.device_id)
    await manager.refresh_devices()
    await manager.monitor.async_refresh_monitoring()
    manager.dispatch_event(
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
    manager.dispatch_event(
        "devices_updated",
        {"devices": manager.device_manager.list_all()},
    )
    connection.send_result(msg["id"], result)
