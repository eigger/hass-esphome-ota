"""Device management, status tracking, and concurrency serialization."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .config_patch import bump_patch_version
from .const import (
    DEFAULT_PUBLISH_DIR,
    DEVICE_STATUS_INSTALLED,
    DEVICE_STATUS_NEEDS_INITIAL_INSTALL,
    DEVICE_STATUS_READY,
    DEVICE_STATUS_UNMANAGED,
    DEVICE_STATUS_UPDATE_AVAILABLE,
    YAML_MODE_INLINE_PACKAGE,
)
from .firmware import chip_family
from .models import ManagedDevice
from .packages import generate_token, is_valid_token, public_slug
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)

_PUBLIC_BIN_SUFFIX = ".ota.bin"
_PUBLIC_SCAN_SETTLE_NS = 3_000_000_000


class DeviceManager:
    """Manages the inventory of ESPHome devices and their OTA statuses."""

    def __init__(self, hass: HomeAssistant, storage: StorageManager) -> None:
        self.hass = hass
        self.storage = storage
        self._managed_devices: dict[str, ManagedDevice] = {}
        self._builder_devices: list[dict[str, Any]] = []
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._registration_lock = asyncio.Lock()
        # (dir inode/mtime/ctime, trusted, slugs) cache for public binary existence.
        self._public_scan: tuple[tuple[int, int, int], bool, set[str]] | None = None
        self._public_scan_task: asyncio.Task[None] | None = None
        self._scan_seq = 0
        # Called when a background rescan changed the public binary listing.
        self.public_scan_listener: Callable[[], None] | None = None

    def get_lock(self, device_id: str) -> asyncio.Lock:
        """Return a persistent asyncio.Lock for a specific device."""
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()
        return self._device_locks[device_id]

    async def async_load(self) -> None:
        """Load stored devices from storage."""
        self._managed_devices = await self.storage.async_load_devices()
        # Prime the public-binary cache off the event loop so the first
        # ``list_all`` already reports correct values.
        await self.async_refresh_public_scan()
        artifacts = await self.storage.async_load_artifacts()
        repaired = False
        for device_id, dev in self._managed_devices.items():
            artifact = artifacts.get(device_id)
            if (
                not dev.last_published_at
                and artifact
                and artifact.version == dev.last_published_version
            ):
                dev.last_published_at = artifact.published_at
                repaired = True
        if repaired:
            await self.storage.async_save_devices(self._managed_devices)

    def update_builder_devices(self, devices: list[dict[str, Any]]) -> None:
        """Update cached raw devices from Builder."""
        self._builder_devices = devices

    @property
    def managed_devices(self) -> dict[str, ManagedDevice]:
        """Live mapping of managed devices keyed by device id (do not rebind)."""
        return self._managed_devices

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
    def _scan_public_dir(pub_dir: Path) -> set[str] | None:
        """List public binary slugs in ``pub_dir`` (blocking; run in executor)."""
        slugs: set[str] = set()
        try:
            with os.scandir(pub_dir) as entries:
                for entry in entries:
                    if entry.name.endswith(_PUBLIC_BIN_SUFFIX) and entry.is_file():
                        slugs.add(entry.name[: -len(_PUBLIC_BIN_SUFFIX)])
        except Exception:  # noqa: BLE001
            return None
        return slugs

    def _public_dir(self) -> Path:
        """Return the public publish directory."""
        return Path(self.hass.config.path("www", DEFAULT_PUBLISH_DIR))

    @classmethod
    def _refresh_public_scan_sync(
        cls,
        pub_dir: Path,
        cached: tuple[tuple[int, int, int], bool, set[str]] | None,
    ) -> tuple[tuple[int, int, int], bool, set[str]] | None:
        """Stat and, when changed, rescan ``pub_dir`` (blocking; run in executor).

        Returns ``cached`` unchanged when the directory identity and mtime still
        match a settled listing, ``None`` when the directory is unavailable.
        """
        try:
            st = pub_dir.stat()
        except Exception:  # noqa: BLE001
            return None
        key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns)
        if cached is not None and cached[0] == key and cached[1]:
            return cached
        slugs = cls._scan_public_dir(pub_dir)
        if slugs is None:
            return None
        settled = time.time_ns() - st.st_mtime_ns > _PUBLIC_SCAN_SETTLE_NS
        return (key, settled, slugs)

    async def async_refresh_public_scan(self, *, force: bool = True) -> None:
        """Refresh the cached listing in the executor (never on the event loop).

        ``force`` rescans even when the directory looks unchanged.
        """
        self._scan_seq += 1
        seq = self._scan_seq
        result = await self.hass.async_add_executor_job(
            self._refresh_public_scan_sync,
            self._public_dir(),
            None if force else self._public_scan,
        )
        if seq != self._scan_seq:
            # A newer scan started meanwhile; its result supersedes this one.
            return
        self._public_scan = result

    def async_unload(self) -> None:
        """Cancel any in-flight background scan."""
        self.public_scan_listener = None
        task = self._public_scan_task
        self._public_scan_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _async_background_public_scan(self) -> None:
        """Refresh the cache and notify listeners when the result changed."""
        before = self._public_scan[2] if self._public_scan else set()
        try:
            await self.async_refresh_public_scan(force=False)
        finally:
            self._public_scan_task = None
        after = self._public_scan[2] if self._public_scan else set()
        if after != before and self.public_scan_listener is not None:
            self.public_scan_listener()

    def _public_binary_slugs(self) -> set[str]:
        """Return slugs with a public ``<slug>.ota.bin`` file.

        Never touches the filesystem on the event loop: the cached listing is
        returned and a background executor job re-stats the publish directory
        (and rescans it only when its mtime changed). ``public_scan_listener``
        fires when the listing changed, so callers that do not subscribe to it
        may see one stale read right after a change.
        """
        cached = self._public_scan
        task = self._public_scan_task
        # A task that already finished (eager start) must not block rescans.
        if task is None or task.done():
            task = self.hass.async_create_task(self._async_background_public_scan())
            # An eagerly started task may already have finished (and cleared
            # the attribute) before this assignment.
            if task.done():
                self._public_scan_task = None
                return self._public_scan[2] if self._public_scan else set()
            self._public_scan_task = task
        return cached[2] if cached is not None else set()

    def list_all(self) -> list[dict[str, Any]]:
        """Combine Builder devices and managed records into a unified list."""
        results: list[dict[str, Any]] = []
        seen_configurations: set[str] = set()

        public_slugs = self._public_binary_slugs()

        def _has_public_bin(slug: str) -> bool:
            return slug in public_slugs

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
                        "last_published_at": managed.last_published_at,
                        "last_installed_at": managed.last_installed_at,
                        "has_http_ota": managed.has_http_ota,
                        "has_public_binary": _has_public_bin(managed.slug),
                        "status": status,
                        "update_entity_id": managed.update_entity_id,
                        "auto_hide": managed.auto_hide,
                        "publication_cleanup_hours": managed.publication_cleanup_hours,
                        "expires_at": managed.expires_at,
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
                        "has_public_binary": False,
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
                        "last_published_at": managed.last_published_at,
                        "last_installed_at": managed.last_installed_at,
                        "has_http_ota": managed.has_http_ota,
                        "has_public_binary": _has_public_bin(managed.slug),
                        "status": status,
                        "update_entity_id": managed.update_entity_id,
                        "auto_hide": managed.auto_hide,
                        "publication_cleanup_hours": managed.publication_cleanup_hours,
                        "expires_at": managed.expires_at,
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
        async with self._registration_lock:
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
                if token is not None and is_valid_token(token):
                    existing.token = token
                elif not is_valid_token(existing.token):
                    existing.token = generate_token()
                # Every published slug carries a strong random token.
                existing.slug = public_slug(name, existing.token)
                if has_http_ota:
                    existing.has_http_ota = True
                existing.status = self._calculate_status(existing)
                existing.updated_at = datetime.now(timezone.utc).isoformat()
                device = existing
            else:
                # Every published slug carries a strong random token; a missing
                # or weak one is replaced.
                assigned_token = token if is_valid_token(token) else generate_token()
                slug = public_slug(name, assigned_token)
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
                # Persist a candidate mapping before exposing the newly-created
                # record in memory. A storage failure must not leave a phantom
                # device that later rollback code could mistake for an old record.
                candidate_devices = {**self._managed_devices, clean_dev_id: device}
                await self.storage.async_save_devices(candidate_devices)
                self._managed_devices[clean_dev_id] = device
                return device

            await self.storage.async_save_devices(self._managed_devices)
            return device

    async def async_mark_published(
        self,
        device_id: str,
        version: str,
        expires_at: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Record successful firmware publication for device and advance next version."""
        dev = self._managed_devices.get(device_id)
        if not dev:
            return
        dev.last_published_version = version
        dev.last_published_at = published_at or datetime.now(timezone.utc).isoformat()
        dev.expires_at = expires_at
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
        installed_at: str | None = None,
    ) -> None:
        """Record verified device installation."""
        dev = self._managed_devices.get(device_id)
        if not dev:
            return
        if dev.last_installed_version != version:
            # A version discovered after HA was offline has no reliable
            # installation timestamp; do not keep the previous version's date.
            dev.last_installed_at = installed_at
        elif installed_at:
            dev.last_installed_at = installed_at
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
