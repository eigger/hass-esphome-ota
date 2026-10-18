"""HTTP Views for multipart firmware upload."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant

from .redaction import install_redaction
from .const import DEFAULT_AUTO_CLEANUP_HOURS, DOMAIN, MAX_UPLOAD_SIZE
from .publisher import async_path_is_file, async_unlink_paths
from .firmware import BinaryValidationError, inspect_binary

_LOGGER = logging.getLogger(__name__)
install_redaction(_LOGGER)


class FirmwareUploadView(HomeAssistantView):
    """View to handle manual multipart firmware binary uploads."""

    name = "api:esphome_ota:upload"
    url = "/api/esphome_ota/upload/{device_id}"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    @require_admin
    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Handle multipart firmware upload."""
        # The view is registered once; resolve the current manager per request so
        # a reloaded entry never serves uploads through a stale manager.
        manager: Any = self.hass.data.get(DOMAIN, {}).get("manager")
        if (
            manager is None
            or getattr(manager, "_unloaded", False)
            or not getattr(manager, "ready", True)
        ):
            return web.json_response({"error": "ESPHome OTA is not loaded"}, status=503)
        if not request.can_read_body:
            return web.json_response({"error": "No body in request"}, status=400)

        reader = await request.multipart()
        field = await reader.next()
        if not field:
            return web.json_response(
                {"error": "No file field found in multipart request"}, status=400
            )

        size = 0
        chunks: list[bytes] = []

        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                return web.json_response(
                    {
                        "error": f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE} bytes"
                    },
                    status=413,
                )
            chunks.append(chunk)

        blob = b"".join(chunks)
        cleanup_hours_override = None
        auto_hide_override = None
        while True:
            metadata = await reader.next()
            if metadata is None:
                break
            value = await metadata.text()
            if metadata.name == "cleanup_hours":
                try:
                    cleanup_hours_override = int(value)
                except ValueError:
                    return web.json_response(
                        {"error": "Invalid cleanup period"}, status=400
                    )
                if not 0 <= cleanup_hours_override <= 168:
                    return web.json_response(
                        {"error": "Cleanup period must be from 0 to 168 hours"},
                        status=400,
                    )
            elif metadata.name == "auto_hide":
                if value.lower() not in ("true", "false"):
                    return web.json_response(
                        {"error": "Invalid hide-after-install setting"}, status=400
                    )
                auto_hide_override = value.lower() == "true"
        clean_device_id = device_id.removesuffix(".yaml")

        # Reject obviously non-firmware payloads before resolving the device. The
        # full platform/chip validation still runs once a known target is found.
        if len(blob) < 1024 or blob[0] != 0xE9:
            return web.json_response(
                {
                    "error": "Invalid firmware binary structure: missing ESP image header"
                },
                status=422,
            )

        async with manager.device_manager.get_lock(clean_device_id):
            dev = manager.device_manager.get_device(clean_device_id)
            newly_registered = False
            published = None
            previous_artifact = None
            previous_public_blob = None
            previous_public_info = None
            previous_public_exists = False
            previous_device = deepcopy(dev) if dev else None
            previous_cleanup_delay = None
            builder_device = None
            if not dev:
                builder_device = manager.device_manager.get_builder_raw(clean_device_id)
                if not builder_device:
                    return web.json_response(
                        {"error": f"Unknown ESPHome device: {clean_device_id}"},
                        status=404,
                    )
                configuration = (
                    builder_device.get("configuration") or f"{clean_device_id}.yaml"
                )
                name = builder_device.get("name") or clean_device_id
                friendly_name = builder_device.get("friendly_name") or name
                target_platform = builder_device.get("target_platform", "esp32")
            else:
                configuration = dev.configuration
                name = dev.name
                friendly_name = dev.friendly_name
                target_platform = dev.target_platform

            try:
                info = inspect_binary(
                    blob=blob,
                    target_platform=target_platform,
                    expected_chip=dev.chip_family if dev else None,
                    reserved_version=dev.managed_version if dev else None,
                )
                artifacts = await manager.storage.async_load_artifacts()
                previous_artifact = artifacts.get(clean_device_id)
                if dev:
                    public_path = manager.publisher.www_dir / f"{dev.slug}.ota.bin"
                    previous_public_exists = await async_path_is_file(
                        self.hass, public_path
                    )
                    if previous_public_exists:
                        try:
                            if previous_artifact:
                                try:
                                    previous_public_blob = await manager.publisher.async_load_private_artifact(
                                        previous_artifact.private_path
                                    )
                                except Exception:  # noqa: BLE001
                                    previous_public_blob = (
                                        await self.hass.async_add_executor_job(
                                            public_path.read_bytes
                                        )
                                    )
                            else:
                                previous_public_blob = (
                                    await self.hass.async_add_executor_job(
                                        public_path.read_bytes
                                    )
                                )
                            previous_public_info = inspect_binary(
                                blob=previous_public_blob,
                                target_platform=dev.target_platform,
                                expected_chip=dev.chip_family,
                                reserved_version=(
                                    previous_artifact.version
                                    if previous_artifact
                                    else None
                                ),
                            )
                        except Exception as backup_err:  # noqa: BLE001
                            return web.json_response(
                                {
                                    "error": (
                                        "Cannot safely replace the active firmware because its "
                                        f"previous binary cannot be recovered: {backup_err}"
                                    )
                                },
                                status=409,
                            )
                    if manager.monitor:
                        timer = manager.monitor._cleanup_timers.get(clean_device_id)
                        if timer:
                            previous_cleanup_delay = max(
                                0.0, timer.when() - self.hass.loop.time()
                            )
                if not dev:
                    # Validate the binary before persisting a newly discovered device.
                    dev = await manager.device_manager.async_register_or_update(
                        device_id=clean_device_id,
                        configuration=configuration,
                        name=name,
                        friendly_name=friendly_name,
                        target_platform=target_platform,
                    )
                    newly_registered = True
                published = await manager.publisher.async_publish(
                    device_id=dev.device_id,
                    configuration=dev.configuration,
                    slug=dev.slug,
                    blob=blob,
                    info=info,
                    title=dev.friendly_name,
                    cleanup_hours=(
                        cleanup_hours_override
                        if cleanup_hours_override is not None
                        else dev.publication_cleanup_hours
                        if dev.publication_cleanup_hours is not None
                        else getattr(
                            manager,
                            "cleanup_hours",
                            DEFAULT_AUTO_CLEANUP_HOURS,
                        )
                    ),
                    auto_hide=dev.auto_hide
                    if auto_hide_override is None
                    else auto_hide_override,
                )
                await manager.storage.async_save_artifact(dev.device_id, published)
                await manager.device_manager.async_mark_published(
                    dev.device_id,
                    published.version,
                    published.expires_at,
                    published.published_at,
                )
                if manager.monitor:
                    manager.monitor.schedule_cleanup(
                        dev.device_id,
                        dev.slug,
                        artifact_id=published.published_at,
                        expires_at=published.expires_at,
                        cleanup_hours=published.cleanup_hours,
                    )
                    await manager.monitor.async_refresh_entity(dev.device_id)
                manager._dispatch_event(
                    "devices_updated",
                    {"devices": manager.device_manager.list_all()},
                )
                return web.json_response(
                    {
                        "success": True,
                        "version": published.version,
                        "size": published.size,
                        "chip_family": published.chip_family,
                        "md5": published.md5,
                        "expires_at": published.expires_at,
                        "cleanup_hours": published.cleanup_hours,
                        "auto_hide": published.auto_hide,
                    }
                )
            except BinaryValidationError as err:
                return web.json_response({"error": str(err)}, status=422)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Failed processing manual firmware upload: %s", err)
                rollback_errors = []
                if published or newly_registered:
                    if manager.monitor:
                        manager.monitor.cancel_cleanup(dev.device_id)
                    restored_publication = None
                    if (
                        published
                        and previous_public_exists
                        and previous_public_blob
                        and previous_public_info
                    ):
                        try:
                            restored_publication = (
                                await manager.publisher.async_publish(
                                    device_id=dev.device_id,
                                    configuration=dev.configuration,
                                    slug=dev.slug,
                                    blob=previous_public_blob,
                                    info=previous_public_info,
                                    title=dev.friendly_name,
                                    cleanup_hours=(
                                        previous_artifact.cleanup_hours
                                        if previous_artifact
                                        and previous_artifact.cleanup_hours is not None
                                        else manager.cleanup_hours
                                    ),
                                    auto_hide=previous_artifact.auto_hide
                                    if previous_artifact
                                    else dev.auto_hide,
                                )
                            )
                            if previous_artifact:
                                restored_publication.cleanup_hours = (
                                    previous_artifact.cleanup_hours
                                )
                                restored_publication.expires_at = (
                                    previous_artifact.expires_at
                                )
                                restored_publication.auto_hide = (
                                    previous_artifact.auto_hide
                                )
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "Could not restore previous firmware for %s",
                                clean_device_id,
                            )
                            rollback_errors.append(
                                "could not restore the previous public firmware"
                            )
                    elif published:
                        try:
                            await manager.publisher.async_deactivate(
                                dev.slug, expected_artifact_id=published.published_at
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "Could not deactivate failed upload for %s",
                                clean_device_id,
                            )
                            rollback_errors.append(
                                "could not deactivate the failed public firmware"
                            )
                        for suffix in (".json", ".ota.json"):
                            try:
                                await async_unlink_paths(
                                    self.hass,
                                    manager.publisher.www_dir / f"{dev.slug}{suffix}",
                                )
                            except OSError:
                                _LOGGER.exception(
                                    "Could not remove failed upload manifest for %s",
                                    clean_device_id,
                                )
                                rollback_errors.append(
                                    "could not remove a failed upload manifest"
                                )
                    try:
                        await manager.storage.async_restore_artifact(
                            dev.device_id, restored_publication or previous_artifact
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception(
                            "Could not restore artifact storage for %s", clean_device_id
                        )
                        rollback_errors.append("could not restore the artifact record")
                    if previous_device:
                        try:
                            dev.__dict__.update(deepcopy(previous_device.__dict__))
                            await manager.storage.async_save_devices(
                                manager.device_manager._managed_devices
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "Could not restore device storage for %s",
                                clean_device_id,
                            )
                            rollback_errors.append(
                                "could not restore the device record"
                            )
                    elif newly_registered:
                        try:
                            await manager.device_manager.async_remove_device(
                                clean_device_id
                            )
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "Could not remove failed upload device record %s",
                                clean_device_id,
                            )
                            rollback_errors.append(
                                "could not remove the newly registered device record"
                            )
                    if manager.monitor:
                        try:
                            if restored_publication:
                                manager.monitor.schedule_cleanup(
                                    dev.device_id,
                                    dev.slug,
                                    artifact_id=restored_publication.published_at,
                                    expires_at=restored_publication.expires_at,
                                    cleanup_hours=restored_publication.cleanup_hours,
                                )
                            elif previous_public_exists and published:
                                manager.monitor.schedule_cleanup(
                                    dev.device_id,
                                    dev.slug,
                                    delay_seconds=previous_cleanup_delay,
                                    artifact_id=published.published_at,
                                )
                            elif previous_artifact and not newly_registered:
                                manager.monitor.cancel_cleanup(dev.device_id)
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "Could not restore cleanup timer for %s",
                                clean_device_id,
                            )
                            rollback_errors.append(
                                "could not restore the automatic cleanup timer"
                            )
                error_message = str(err)
                if rollback_errors:
                    error_message += (
                        " (rollback incomplete: " + "; ".join(rollback_errors) + ")"
                    )
                return web.json_response({"error": error_message}, status=500)
