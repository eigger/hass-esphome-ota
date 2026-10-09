"""Device management, status tracking, and concurrency serialization."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import secrets
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    DEVICE_STATUS_INSTALLED,
    DEVICE_STATUS_NEEDS_INITIAL_INSTALL,
    DEVICE_STATUS_READY,
    DEVICE_STATUS_UNMANAGED,
    DEVICE_STATUS_UPDATE_AVAILABLE,
    YAML_MODE_INLINE_PACKAGE,
)
from .firmware import chip_family
from .models import DeviceNotFoundError, ManagedDevice
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    """Manages the inventory of ESPHome devices and their OTA statuses."""

    def __init__(self, hass: HomeAssistant, storage: StorageManager) -> None:
        self.hass = hass
        self.storage = storage
        self._managed_devices: dict[str, ManagedDevice] = {}
        self._builder_devices: list[dict[str, Any]] = []
        self._device_locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, device_id: str) -> asyncio.Lock:
        """Return a persistent asyncio.Lock for a specific device."""
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()
        return self._device_locks[device_id]

    async def async_load(self) -> None:
        """Load stored devices from storage."""
        self._managed_devices = await self.storage.async_load_devices()

    def update_builder_devices(self, devices: list[dict[str, Any]]) -> None:
        """Update cached raw devices from Builder."""
        self._builder_devices = devices

    def get_device(self, device_id: str) -> ManagedDevice | None:
        """Get managed device by ID."""
        return self._managed_devices.get(device_id)

    def list_all(self) -> list[dict[str, Any]]:
        """Combine Builder devices and managed records into a unified list."""
        results: list[dict[str, Any]] = []
        seen_configurations: set[str] = set()

        # Iterate over devices reported by Builder
        for raw in self._builder_devices:
            # Builder device dict usually contains "configuration" (e.g. "livingroom.yaml") and "name"
            cfg_file = raw.get("configuration", "")
            cfg_stem = cfg_file.replace(".yaml", "") if cfg_file.endswith(".yaml") else cfg_file
            if not cfg_stem:
                cfg_stem = raw.get("name", "")
            seen_configurations.add(cfg_stem)

            managed = self._managed_devices.get(cfg_stem)
            target_plat = raw.get("target_platform", "esp32")
            chip, _ = chip_family(target_plat)

            if managed:
                status = self._calculate_status(managed, raw)
                results.append(
                    {
                        "device_id": managed.device_id,
                        "configuration": managed.configuration,
                        "name": managed.name,
                        "friendly_name": managed.friendly_name,
                        "is_managed": True,
                        "token": managed.token,
                        "slug": managed.slug,
                        "target_platform": target_plat,
                        "chip_family": chip or managed.chip_family,
                        "yaml_mode": managed.yaml_mode,
                        "own_project_version": managed.own_project_version,
                        "managed_version": managed.managed_version,
                        "last_published_version": managed.last_published_version,
                        "last_installed_version": managed.last_installed_version,
                        "has_http_ota": managed.has_http_ota,
                        "status": status,
                        "update_entity_id": managed.update_entity_id,
                        "builder_present": True,
                    }
                )
            else:
                results.append(
                    {
                        "device_id": cfg_stem,
                        "configuration": cfg_stem,
                        "name": raw.get("name", cfg_stem),
                        "friendly_name": raw.get("friendly_name") or raw.get("name", cfg_stem),
                        "is_managed": False,
                        "token": "",
                        "slug": cfg_stem,
                        "target_platform": target_plat,
                        "chip_family": chip or "ESP32",
                        "yaml_mode": YAML_MODE_INLINE_PACKAGE,
                        "own_project_version": None,
                        "managed_version": "1.0.0",
                        "last_published_version": None,
                        "last_installed_version": raw.get("current_version"),
                        "has_http_ota": False,
                        "status": DEVICE_STATUS_UNMANAGED,
                        "update_entity_id": None,
                        "builder_present": True,
                    }
                )

        # Include managed devices whose YAML is not currently reported by Builder
        for dev_id, managed in self._managed_devices.items():
            if dev_id not in seen_configurations:
                results.append(
                    {
                        "device_id": managed.device_id,
                        "configuration": managed.configuration,
                        "name": managed.name,
                        "friendly_name": managed.friendly_name,
                        "is_managed": True,
                        "token": managed.token,
                        "slug": managed.slug,
                        "target_platform": managed.target_platform,
                        "chip_family": managed.chip_family,
                        "yaml_mode": managed.yaml_mode,
                        "own_project_version": managed.own_project_version,
                        "managed_version": managed.managed_version,
                        "last_published_version": managed.last_published_version,
                        "last_installed_version": managed.last_installed_version,
                        "has_http_ota": managed.has_http_ota,
                        "status": managed.status,
                        "update_entity_id": managed.update_entity_id,
                        "builder_present": False,
                    }
                )

        return results

    def _calculate_status(
        self,
        managed: ManagedDevice,
        raw_builder_info: dict[str, Any] | None = None,
    ) -> str:
        """Determine device OTA status."""
        if not managed.has_http_ota and not managed.last_installed_version:
            # Device has not received first HTTP OTA firmware installation yet
            return DEVICE_STATUS_NEEDS_INITIAL_INSTALL

        if managed.last_published_version:
            if not managed.last_installed_version:
                return DEVICE_STATUS_NEEDS_INITIAL_INSTALL
            if managed.last_published_version != managed.last_installed_version:
                return DEVICE_STATUS_UPDATE_AVAILABLE
            return DEVICE_STATUS_INSTALLED

        return DEVICE_STATUS_READY

    async def async_register_or_update(
        self,
        device_id: str,
        configuration: str,
        name: str,
        friendly_name: str,
        target_platform: str = "esp32",
        token: str | None = None,
        own_project_version: str | None = None,
        has_http_ota: bool = False,
    ) -> ManagedDevice:
        """Register a new managed device or update existing record."""
        existing = self._managed_devices.get(device_id)
        chip, _ = chip_family(target_platform)

        if existing:
            existing.configuration = configuration
            existing.name = name
            existing.friendly_name = friendly_name
            existing.target_platform = target_platform
            if chip:
                existing.chip_family = chip
            if own_project_version is not None:
                existing.own_project_version = own_project_version
            if has_http_ota:
                existing.has_http_ota = True
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            device = existing
        else:
            # Mint 32-char hex token for fresh device
            assigned_token = token if token is not None else secrets.token_hex(16)
            slug = f"{name}_{assigned_token}" if assigned_token else name
            device = ManagedDevice(
                device_id=device_id,
                configuration=configuration,
                name=name,
                friendly_name=friendly_name,
                token=assigned_token,
                slug=slug,
                target_platform=target_platform,
                chip_family=chip or "ESP32",
                own_project_version=own_project_version,
                has_http_ota=has_http_ota,
            )
            self._managed_devices[device_id] = device

        await self.storage.async_save_devices(self._managed_devices)
        return device

    async def async_mark_published(
        self,
        device_id: str,
        version: str,
    ) -> None:
        """Record successful firmware publication for device."""
        dev = self._managed_devices.get(device_id)
        if not dev:
            return
        dev.last_published_version = version
        dev.updated_at = datetime.now(timezone.utc).isoformat()
        await self.storage.async_save_devices(self._managed_devices)

    async def async_mark_installed(
        self,
        device_id: str,
        version: str,
    ) -> None:
        """Record verified device installation."""
        dev = self._managed_devices.get(device_id)
        if not dev:
            return
        dev.last_installed_version = version
        dev.has_http_ota = True
        dev.updated_at = datetime.now(timezone.utc).isoformat()
        await self.storage.async_save_devices(self._managed_devices)
