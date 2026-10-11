"""HTTP Views for multipart firmware upload."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant

from .const import MAX_UPLOAD_SIZE
from .firmware import BinaryValidationError, inspect_binary

_LOGGER = logging.getLogger(__name__)


class FirmwareUploadView(HomeAssistantView):
    """View to handle manual multipart firmware binary uploads."""

    name = "api:esphome_ota:upload"
    url = "/api/esphome_ota/upload/{device_id}"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, manager: Any) -> None:
        self.hass = hass
        self.manager = manager

    @require_admin
    async def post(self, request: web.Request, device_id: str) -> web.Response:
        """Handle multipart firmware upload."""
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
        clean_device_id = device_id.removesuffix(".yaml")

        async with self.manager.device_manager.get_lock(clean_device_id):
            dev = self.manager.device_manager.get_device(clean_device_id)
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
                builder_device = self.manager.device_manager.get_builder_raw(
                    clean_device_id
                )
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
                artifacts = await self.manager.storage.async_load_artifacts()
                previous_artifact = artifacts.get(clean_device_id)
                if dev:
                    public_path = self.manager.publisher.www_dir / f"{dev.slug}.ota.bin"
                    previous_public_exists = public_path.is_file()
                    if previous_public_exists:
                        try:
                            if previous_artifact:
                                try:
                                    previous_public_blob = await self.manager.publisher.async_load_private_artifact(
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
                    if self.manager.monitor:
                        timer = self.manager.monitor._cleanup_timers.get(
                            clean_device_id
                        )
                        if timer:
                            previous_cleanup_delay = max(
                                0.0, timer.when() - self.hass.loop.time()
                            )
                if not dev:
                    # Validate the binary before persisting a newly discovered device.
                    dev = await self.manager.device_manager.async_register_or_update(
                        device_id=clean_device_id,
                        configuration=configuration,
                        name=name,
                        friendly_name=friendly_name,
                        target_platform=target_platform,
                    )
                    newly_registered = True
                published = await self.manager.publisher.async_publish(
                    device_id=dev.device_id,
                    configuration=dev.configuration,
                    slug=dev.slug,
                    blob=blob,
                    info=info,
                    title=dev.friendly_name,
                )
                await self.manager.storage.async_save_artifact(dev.device_id, published)
                await self.manager.device_manager.async_mark_published(
                    dev.device_id, published.version
                )
                if self.manager.monitor:
                    self.manager.monitor.schedule_cleanup(
                        dev.device_id, dev.slug, artifact_id=published.published_at
                    )
                    await self.manager.monitor.async_refresh_entity(dev.device_id)
                self.manager._dispatch_event(
                    "devices_updated",
                    {"devices": self.manager.device_manager.list_all()},
                )
                return web.json_response(
                    {
                        "success": True,
                        "version": published.version,
                        "size": published.size,
                        "chip_family": published.chip_family,
                        "md5": published.md5,
                    }
                )
            except BinaryValidationError as err:
                return web.json_response({"error": str(err)}, status=422)
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Failed processing manual firmware upload: %s", err)
                rollback_errors = []
                if published or newly_registered:
                    if self.manager.monitor:
                        self.manager.monitor.cancel_cleanup(dev.device_id)
                    restored_publication = None
                    if (
                        published
                        and previous_public_exists
                        and previous_public_blob
                        and previous_public_info
                    ):
                        try:
                            restored_publication = (
                                await self.manager.publisher.async_publish(
                                    device_id=dev.device_id,
                                    configuration=dev.configuration,
                                    slug=dev.slug,
                                    blob=previous_public_blob,
                                    info=previous_public_info,
                                    title=dev.friendly_name,
                                )
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
                            await self.manager.publisher.async_deactivate(
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
                                (
                                    self.manager.publisher.www_dir
                                    / f"{dev.slug}{suffix}"
                                ).unlink(missing_ok=True)
                            except OSError:
                                _LOGGER.exception(
                                    "Could not remove failed upload manifest for %s",
                                    clean_device_id,
                                )
                                rollback_errors.append(
                                    "could not remove a failed upload manifest"
                                )
                    try:
                        await self.manager.storage.async_restore_artifact(
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
                            await self.manager.storage.async_save_devices(
                                self.manager.device_manager._managed_devices
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
                            await self.manager.device_manager.async_remove_device(
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
                    if self.manager.monitor:
                        try:
                            if restored_publication:
                                self.manager.monitor.schedule_cleanup(
                                    dev.device_id,
                                    dev.slug,
                                    delay_seconds=previous_cleanup_delay,
                                    artifact_id=restored_publication.published_at,
                                )
                            elif previous_public_exists and published:
                                self.manager.monitor.schedule_cleanup(
                                    dev.device_id,
                                    dev.slug,
                                    delay_seconds=previous_cleanup_delay,
                                    artifact_id=published.published_at,
                                )
                            elif previous_artifact and not newly_registered:
                                self.manager.monitor.cancel_cleanup(dev.device_id)
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
