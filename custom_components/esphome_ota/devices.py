"""Device management, status tracking, and concurrency serialization."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import re
import secrets
from typing import Any

from homeassistant.core import HomeAssistant

from .config_patch import bump_patch_version
from .const import (
    DEVICE_STATUS_INSTALLED,
    DEVICE_STATUS_NEEDS_INITIAL_INSTALL,
    DEVICE_STATUS_READY,
    DEVICE_STATUS_UNMANAGED,
    DEVICE_STATUS_UPDATE_AVAILABLE,
    YAML_MODE_INLINE_PACKAGE,
)
from .firmware import chip_family
from .models import ManagedDevice
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)

# ESPHome Dashboard may append "(1)" when a config name collides.
_COPY_SUFFIX_RE = re.compile(r"\(\d+\)$")


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

    def get_builder_raw(self, device_id: str) -> dict[str, Any] | None:
        """Find raw Builder device info by device_id or configuration."""
        target = device_id.replace(".yaml", "")
        for raw in self._builder_devices:
            cfg_file = raw.get("configuration", "")
            cfg_stem = (
                cfg_file.replace(".yaml", "")
                if cfg_file.endswith(".yaml")
                else cfg_file
            )
            if cfg_stem == target or raw.get("name") == target or cfg_file == device_id:
                return raw
        return None

    def get_configuration(self, device_id: str) -> str:
        """Return the actual Builder YAML configuration filename with extension."""
        dev = self._managed_devices.get(device_id)
        if dev and dev.configuration:
            return (
                dev.configuration
                if dev.configuration.endswith(".yaml")
                else f"{dev.configuration}.yaml"
            )
        raw = self.get_builder_raw(device_id)
        if raw and raw.get("configuration"):
            cfg = raw["configuration"]
            return cfg if cfg.endswith(".yaml") else f"{cfg}.yaml"
        if device_id.endswith(".yaml"):
            return device_id
        return f"{device_id}.yaml"

    @staticmethod
    def _cfg_stem(configuration: str) -> str:
        """Normalize a configuration filename to its stem."""
        if configuration.endswith(".yaml"):
            return configuration[:-5]
        return configuration

    def resolve_legacy_configuration(
        self, node: str, token: str = ""
    ) -> tuple[str, str, dict[str, Any] | None, list[str]]:
        """Map a legacy registry node to the best Builder configuration.

        Returns (device_id, configuration, raw_builder_or_none, ambiguous_stems).
        Prefers the plain ``{node}.yaml`` over slug-named copies such as
        ``{node}_{token}(1).yaml`` so migration does not attach to duplicates.
        """
        scored: list[tuple[int, str, str, dict[str, Any]]] = []
        for raw in self._builder_devices:
            cfg_file = raw.get("configuration", "")
            if not cfg_file and raw.get("name"):
                cfg_file = f"{raw['name']}.yaml"
            if not cfg_file:
                continue
            stem = self._cfg_stem(cfg_file)
            base_stem = _COPY_SUFFIX_RE.sub("", stem)
            score = 0
            if stem == node:
                score = 100
            elif token and stem == f"{node}_{token}":
                score = 90
            elif token and base_stem == f"{node}_{token}":
                score = 85
            elif token and stem.startswith(f"{node}_") and token in stem:
                score = 70
            elif raw.get("name") == node:
                score = 60
            elif (raw.get("friendly_name") or "").strip() and (
                raw.get("friendly_name") or ""
            ).strip() == node:
                score = 50
            if score:
                scored.append(
                    (
                        score,
                        stem,
                        cfg_file if cfg_file.endswith(".yaml") else f"{cfg_file}.yaml",
                        raw,
                    )
                )

        if not scored:
            return node, f"{node}.yaml", None, []

        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score = scored[0][0]
        top = [item for item in scored if item[0] == best_score]
        # Prefer the shortest/plain stem when scores tie (node.yaml over node_token(1).yaml)
        top.sort(key=lambda item: (len(item[1]), item[1]))
        _, stem, cfg_file, raw = top[0]
        ambiguous = [item[1] for item in scored if item[1] != stem]
        return stem, cfg_file, raw, ambiguous

    def list_all(self) -> list[dict[str, Any]]:
        """Combine Builder devices and managed records into a unified list."""
        results: list[dict[str, Any]] = []
        seen_configurations: set[str] = set()

        # Iterate over devices reported by Builder
        for raw in self._builder_devices:
            # Builder device dict contains "configuration" (e.g. "livingroom.yaml") and "name"
            cfg_file = raw.get("configuration", "")
            cfg_stem = (
                cfg_file.replace(".yaml", "")
                if cfg_file.endswith(".yaml")
                else cfg_file
            )
            if not cfg_stem:
                cfg_stem = raw.get("name", "")
            if not cfg_file:
                cfg_file = f"{cfg_stem}.yaml" if cfg_stem else ""
            seen_configurations.add(cfg_stem)

            managed = self._managed_devices.get(cfg_stem)
            target_plat = raw.get("target_platform", "esp32")
            chip, _ = chip_family(target_plat)

            if managed:
                live_installed = managed.last_installed_version
                if not live_installed and managed.update_entity_id:
                    st = self.hass.states.get(managed.update_entity_id)
                    if st and st.state not in ("unavailable", "unknown"):
                        live_installed = st.attributes.get("installed_version")
                status = self._calculate_status(
                    managed, raw, live_installed_version=live_installed
                )
                results.append(
                    {
                        "device_id": managed.device_id,
                        "configuration": managed.configuration
                        if managed.configuration.endswith(".yaml")
                        else cfg_file,
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
                        "last_installed_version": live_installed,
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
                        "configuration": cfg_file,
                        "name": raw.get("name", cfg_stem),
                        "friendly_name": raw.get("friendly_name")
                        or raw.get("name", cfg_stem),
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
                live_installed = managed.last_installed_version
                if not live_installed and managed.update_entity_id:
                    st = self.hass.states.get(managed.update_entity_id)
                    if st and st.state not in ("unavailable", "unknown"):
                        live_installed = st.attributes.get("installed_version")
                status = self._calculate_status(
                    managed, None, live_installed_version=live_installed
                )
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
                        "last_installed_version": live_installed,
                        "has_http_ota": managed.has_http_ota,
                        "status": status,
                        "update_entity_id": managed.update_entity_id,
                        "builder_present": False,
                    }
                )

        return results

    def _calculate_status(
        self,
        managed: ManagedDevice,
        raw_builder_info: dict[str, Any] | None = None,
        live_installed_version: str | None = None,
    ) -> str:
        """Determine device OTA status."""
        installed_ver = live_installed_version or managed.last_installed_version
        if not installed_ver and managed.update_entity_id:
            st = self.hass.states.get(managed.update_entity_id)
            if st and st.state not in ("unavailable", "unknown"):
                installed_ver = st.attributes.get("installed_version")

        if not managed.has_http_ota and not installed_ver:
            # Device has not received first HTTP OTA firmware installation yet
            return DEVICE_STATUS_NEEDS_INITIAL_INSTALL

        if managed.last_published_version:
            if not installed_ver:
                return DEVICE_STATUS_NEEDS_INITIAL_INSTALL
            if managed.last_published_version != installed_ver:
                return DEVICE_STATUS_UPDATE_AVAILABLE
            return DEVICE_STATUS_INSTALLED

        if installed_ver:
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
        managed_version: str | None = None,
        yaml_mode: str | None = None,
    ) -> ManagedDevice:
        """Register a new managed device or update existing record."""
        clean_dev_id = device_id.replace(".yaml", "")
        clean_config = (
            configuration
            if configuration.endswith(".yaml")
            else f"{configuration}.yaml"
        )
        existing = self._managed_devices.get(clean_dev_id)
        chip, _ = chip_family(target_platform)

        if existing:
            existing.configuration = clean_config
            existing.name = name
            existing.friendly_name = friendly_name
            existing.target_platform = target_platform
            if chip:
                existing.chip_family = chip
            if own_project_version is not None:
                existing.own_project_version = own_project_version
            if managed_version is not None:
                existing.managed_version = managed_version
            if yaml_mode is not None:
                existing.yaml_mode = yaml_mode
            if token is not None:
                existing.token = token
                existing.slug = f"{name}_{token}" if token else name
            if has_http_ota:
                existing.has_http_ota = True
            existing.status = self._calculate_status(existing)
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            device = existing
        else:
            # Mint 32-char hex token for fresh device
            assigned_token = token if token is not None else secrets.token_hex(16)
            slug = f"{name}_{assigned_token}" if assigned_token else name
            device = ManagedDevice(
                device_id=clean_dev_id,
                configuration=clean_config,
                name=name,
                friendly_name=friendly_name,
                token=assigned_token,
                slug=slug,
                target_platform=target_platform,
                chip_family=chip or "ESP32",
                yaml_mode=yaml_mode or YAML_MODE_INLINE_PACKAGE,
                own_project_version=own_project_version,
                managed_version=managed_version or "1.0.0",
                has_http_ota=has_http_ota,
            )
            device.status = self._calculate_status(device)
            self._managed_devices[clean_dev_id] = device

        await self.storage.async_save_devices(self._managed_devices)
        return device

    async def async_mark_published(
        self,
        device_id: str,
        version: str,
    ) -> None:
        """Record successful firmware publication for device and advance next version."""
        dev = self._managed_devices.get(device_id)
        if not dev:
            return
        dev.last_published_version = version
        # Advance managed version for next build (legacy advance_registered_version behavior)
        nxt = bump_patch_version(version)
        dev.managed_version = nxt
        dev.status = self._calculate_status(dev)
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
        dev.status = self._calculate_status(dev)
        dev.updated_at = datetime.now(timezone.utc).isoformat()
        await self.storage.async_save_devices(self._managed_devices)

    async def async_remove_device(self, device_id: str) -> ManagedDevice | None:
        """Remove a managed device record from memory and storage."""
        clean_id = device_id.replace(".yaml", "")
        removed = self._managed_devices.pop(clean_id, None)
        if removed is None:
            return None
        await self.storage.async_save_devices(self._managed_devices)
        return removed
