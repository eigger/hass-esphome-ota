"""Storage manager handling persistence of devices, jobs and artifacts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    STAGE_CANCELLED,
    STAGE_FAILED,
    STAGE_PUBLISHED,
    STORAGE_KEY_ARTIFACTS,
    STORAGE_KEY_DEVICES,
    STORAGE_KEY_JOBS,
    STORAGE_KEY_MIGRATION,
    STORAGE_VERSION,
)
from .models import ManagedDevice, PipelineJob, PublishedArtifact

_LOGGER = logging.getLogger(__name__)


STORAGE_CACHE_KEY = "esphome_ota_storage_cache"
_TERMINAL_STAGES = (STAGE_PUBLISHED, STAGE_FAILED, STAGE_CANCELLED)
TERMINAL_LOG_TAIL_LINES = 50


class StorageManager:
    """Manages Home Assistant Storage operations with schema versioning."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._device_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_DEVICES
        )
        self._job_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_JOBS
        )
        self._artifact_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_ARTIFACTS
        )
        # Only kept to delete the record of the removed legacy add-on import.
        self._migration_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_MIGRATION
        )
        self._artifact_lock: asyncio.Lock = asyncio.Lock()
        # Every write goes through this class, so the last loaded or saved
        # payload per store key is authoritative (memory is the source of
        # truth; HA Store only schedules the disk write). The cache lives in
        # hass.data so StorageManager instances share the same values; it does
        # not make read-modify-write sequences atomic across instances.
        self._cache: dict[str, Any] = hass.data.setdefault(STORAGE_CACHE_KEY, {})

    async def _async_load(self, store: Store[dict[str, Any]]) -> Any:
        """Load a store once, then serve independent copies from memory."""
        key = store.key
        if key not in self._cache:
            data = await store.async_load()
            # A concurrent save may have populated the cache while we were
            # reading the disk; never overwrite that newer value.
            self._cache.setdefault(key, deepcopy(data))
        return deepcopy(self._cache[key])

    async def _async_save(self, store: Store[dict[str, Any]], data: Any) -> None:
        """Save a store and refresh the in-memory copy.

        HA's Store does not raise on disk write failures (it only schedules the
        write), so the cache is authoritative. If an exception does propagate
        (e.g. cancellation), the entry is dropped and re-read from disk.
        """
        key = store.key
        self._cache[key] = deepcopy(data)
        try:
            await store.async_save(data)
        except BaseException:
            self._cache.pop(key, None)
            raise

    async def async_load_devices(self) -> dict[str, ManagedDevice]:
        """Load stored managed devices."""
        data = await self._async_load(self._device_store)
        if not data or not isinstance(data, dict):
            return {}
        result: dict[str, ManagedDevice] = {}
        for dev_id, item in data.items():
            if isinstance(item, dict):
                result[dev_id] = ManagedDevice.from_dict(item)
        return result

    async def async_save_devices(self, devices: dict[str, ManagedDevice]) -> None:
        """Save managed devices to storage."""
        data = {dev_id: dev.to_dict() for dev_id, dev in devices.items()}
        await self._async_save(self._device_store, data)

    async def async_load_jobs(self) -> dict[str, PipelineJob]:
        """Load active or recorded pipeline jobs."""
        data = await self._async_load(self._job_store)
        if not data or not isinstance(data, dict):
            return {}
        result: dict[str, PipelineJob] = {}
        for job_id, item in data.items():
            if isinstance(item, dict):
                result[job_id] = PipelineJob.from_dict(item)
        return result

    async def async_save_jobs(self, jobs: dict[str, PipelineJob]) -> None:
        """Save pipeline jobs to storage."""
        data = {job_id: job.to_dict() for job_id, job in jobs.items()}
        for item in data.values():
            # Finished jobs only need a short log in storage.
            if item.get("stage") in _TERMINAL_STAGES:
                item["log_tail"] = item["log_tail"][-TERMINAL_LOG_TAIL_LINES:]
        await self._async_save(self._job_store, data)

    async def async_load_artifacts(self) -> dict[str, PublishedArtifact]:
        """Load published artifact records."""
        async with self._artifact_lock:
            data = await self._async_load(self._artifact_store)
            if not data or not isinstance(data, dict):
                return {}
            result: dict[str, PublishedArtifact] = {}
            for key, item in data.items():
                if isinstance(item, dict):
                    result[key] = PublishedArtifact.from_dict(item)
            return result

    async def async_save_artifacts(
        self, artifacts: dict[str, PublishedArtifact]
    ) -> None:
        """Save published artifact records to storage."""
        async with self._artifact_lock:
            data = {key: art.to_dict() for key, art in artifacts.items()}
            await self._async_save(self._artifact_store, data)

    async def async_save_artifact(
        self, device_id: str, artifact: PublishedArtifact
    ) -> None:
        """Atomically record or update a single device's published artifact in storage."""
        async with self._artifact_lock:
            data = await self._async_load(self._artifact_store)
            current: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
            current[device_id] = artifact.to_dict()
            await self._async_save(self._artifact_store, current)

    async def async_deactivate_artifact_if_current(
        self,
        device_id: str,
        expected_published_at: str,
        deactivate: Callable[[], Awaitable[bool]],
        *,
        expected_expires_at: str | None = None,
    ) -> bool:
        """Deactivate and mark private atomically against policy changes."""
        async with self._artifact_lock:
            data = await self._async_load(self._artifact_store)
            if not isinstance(data, dict):
                return False
            raw_artifact = data.get(device_id)
            if (
                not isinstance(raw_artifact, dict)
                or raw_artifact.get("published_at") != expected_published_at
                or not raw_artifact.get("is_public")
                or (
                    expected_expires_at is not None
                    and raw_artifact.get("expires_at") != expected_expires_at
                )
            ):
                return False
            if expected_expires_at is not None:
                try:
                    expiry = datetime.fromisoformat(expected_expires_at)
                except ValueError:
                    return False
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry > datetime.now(timezone.utc):
                    return False
            # Keep policy updates from extending or disabling this publication
            # between deadline validation and its file removal.
            if not await deactivate():
                return False
            raw_artifact["is_public"] = False
            raw_artifact["public_bin_path"] = None
            await self._async_save(self._artifact_store, data)
            return True

    async def async_update_artifact_policy_if_current(
        self,
        device_id: str,
        expected_published_at: str,
        *,
        cleanup_hours: int,
        expires_at: str | None,
        auto_hide: bool,
    ) -> PublishedArtifact | None:
        """Update policy without overwriting concurrent visibility changes."""
        async with self._artifact_lock:
            data = await self._async_load(self._artifact_store)
            if not isinstance(data, dict):
                return None
            raw_artifact = data.get(device_id)
            if (
                not isinstance(raw_artifact, dict)
                or raw_artifact.get("published_at") != expected_published_at
            ):
                return None
            raw_artifact["cleanup_hours"] = cleanup_hours
            raw_artifact["expires_at"] = expires_at
            raw_artifact["auto_hide"] = auto_hide
            await self._async_save(self._artifact_store, data)
            return PublishedArtifact.from_dict(raw_artifact)

    async def async_restore_artifact(
        self, device_id: str, artifact: PublishedArtifact | None
    ) -> None:
        """Atomically restore or remove one device's artifact record."""
        async with self._artifact_lock:
            data = await self._async_load(self._artifact_store)
            current: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
            if artifact is None:
                current.pop(device_id, None)
            else:
                current[device_id] = artifact.to_dict()
            await self._async_save(self._artifact_store, current)

    async def async_remove_migration_record(self) -> None:
        """Delete the record left by the removed legacy add-on import."""
        self._cache.pop(STORAGE_KEY_MIGRATION, None)
        await self._migration_store.async_remove()
