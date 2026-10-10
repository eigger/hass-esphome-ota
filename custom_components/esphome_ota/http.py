"""HTTP Views for multipart firmware upload."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.core import HomeAssistant

from .const import MAX_UPLOAD_SIZE
from .firmware import BinaryValidationError, inspect_binary
from .models import ManagedDevice

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
            return web.json_response({"error": "No file field found in multipart request"}, status=400)

        size = 0
        chunks: list[bytes] = []

        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                return web.json_response(
                    {"error": f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE} bytes"},
                    status=413,
                )
            chunks.append(chunk)

        blob = b"".join(chunks)

        dev = self.manager.device_manager.get_device(device_id)
        if not dev:
            # Check if device is in builder devices
            dev = await self.manager.device_manager.async_register_or_update(
                device_id=device_id,
                configuration=device_id,
                name=device_id,
                friendly_name=device_id,
            )

        try:
            info = inspect_binary(
                blob=blob,
                target_platform=dev.target_platform,
                expected_chip=dev.chip_family,
                reserved_version=dev.managed_version,
            )
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
            return web.json_response({"error": str(err)}, status=500)
