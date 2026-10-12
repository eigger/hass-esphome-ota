"""Storage manager handling persistence of devices, jobs, artifacts, and migration records."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    STORAGE_KEY_ARTIFACTS,
    STORAGE_KEY_DEVICES,
    STORAGE_KEY_JOBS,
    STORAGE_KEY_MIGRATION,
    STORAGE_VERSION,
)
from .models import ManagedDevice, PipelineJob, PublishedArtifact

_LOGGER = logging.getLogger(__name__)


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
        self._migration_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_MIGRATION
        )
        self._artifact_lock: asyncio.Lock = asyncio.Lock()

    async def async_load_devices(self) -> dict[str, ManagedDevice]:
        """Load stored managed devices."""
        data = await self._device_store.async_load()
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
        await self._device_store.async_save(data)

    async def async_load_jobs(self) -> dict[str, PipelineJob]:
        """Load active or recorded pipeline jobs."""
        data = await self._job_store.async_load()
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
        await self._job_store.async_save(data)

    async def async_load_artifacts(self) -> dict[str, PublishedArtifact]:
        """Load published artifact records."""
        async with self._artifact_lock:
            data = await self._artifact_store.async_load()
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
            await self._artifact_store.async_save(data)

    async def async_save_artifact(
        self, device_id: str, artifact: PublishedArtifact
    ) -> None:
        """Atomically record or update a single device's published artifact in storage."""
        async with self._artifact_lock:
            data = await self._artifact_store.async_load()
            current: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
            current[device_id] = artifact.to_dict()
            await self._artifact_store.async_save(current)

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
            data = await self._artifact_store.async_load()
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
            await self._artifact_store.async_save(data)
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
            data = await self._artifact_store.async_load()
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
            await self._artifact_store.async_save(data)
            return PublishedArtifact.from_dict(raw_artifact)

    async def async_restore_artifact(
        self, device_id: str, artifact: PublishedArtifact | None
    ) -> None:
        """Atomically restore or remove one device's artifact record."""
        async with self._artifact_lock:
            data = await self._artifact_store.async_load()
            current: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
            if artifact is None:
                current.pop(device_id, None)
            else:
                current[device_id] = artifact.to_dict()
            await self._artifact_store.async_save(current)

    async def async_load_migration(self) -> dict[str, Any]:
        """Load migration status record."""
        data = await self._migration_store.async_load()
        return data if isinstance(data, dict) else {}

    async def async_save_migration(self, data: dict[str, Any]) -> None:
        """Save migration record."""
        await self._migration_store.async_save(data)
