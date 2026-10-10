"""Storage manager handling persistence of devices, jobs, artifacts, and migration records."""

from __future__ import annotations

import asyncio
import logging
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
            current: dict[str, Any] = data if isinstance(data, dict) else {}
            current[device_id] = artifact.to_dict()
            await self._artifact_store.async_save(current)

    async def async_load_migration(self) -> dict[str, Any]:
        """Load migration status record."""
        data = await self._migration_store.async_load()
        return data if isinstance(data, dict) else {}

    async def async_save_migration(self, data: dict[str, Any]) -> None:
        """Save migration record."""
        await self._migration_store.async_save(data)
