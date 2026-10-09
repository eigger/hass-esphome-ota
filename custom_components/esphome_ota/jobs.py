"""Pipeline job runner managing compile, download, verify, and publish lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Callable
import uuid

from homeassistant.core import HomeAssistant

from .builder.client import BuilderClient
from .config_patch import apply_ota_patch, bump_patch_version, own_project_version
from .const import (
    MAX_LOG_TAIL_LINES,
    STAGE_BUILDING,
    STAGE_CANCELLED,
    STAGE_CANCELLING,
    STAGE_DOWNLOADING,
    STAGE_FAILED,
    STAGE_PREPARING,
    STAGE_PUBLISHED,
    STAGE_PUBLISHING,
    STAGE_QUEUED,
    STAGE_RECOVERY_REQUIRED,
    STAGE_SUBMITTING,
    STAGE_VALIDATING,
    STAGE_VERIFYING,
)
from .devices import DeviceManager
from .firmware import inspect_binary
from .models import (
    BinaryValidationError,
    BuilderError,
    EsphomeOtaError,
    JobCancelledError,
    ManagedDevice,
    PipelineJob,
    PublishedArtifact,
)
from .publisher import ArtifactPublisher
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)


class JobRunner:
    """Orchestrates build and publish pipeline jobs with checkpoints and recovery."""

    def __init__(
        self,
        hass: HomeAssistant,
        storage: StorageManager,
        device_manager: DeviceManager,
        publisher: ArtifactPublisher,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.hass = hass
        self.storage = storage
        self.device_manager = device_manager
        self.publisher = publisher
        self.event_callback = event_callback
        self._active_jobs: dict[str, PipelineJob] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._in_flight_requests: set[str] = set()

    async def async_load(self) -> None:
        """Load stored pipeline jobs."""
        self._active_jobs = await self.storage.async_load_jobs()

    def get_job(self, job_id: str) -> PipelineJob | None:
        """Get job by ID."""
        return self._active_jobs.get(job_id)

    def list_jobs(self) -> list[PipelineJob]:
        """Return list of all jobs."""
        return list(self._active_jobs.values())

    def _notify_job_update(self, job: PipelineJob) -> None:
        """Emit job update event."""
        if self.event_callback:
            self.event_callback("job_updated", job.to_dict())

    async def _update_stage(
        self,
        job: PipelineJob,
        stage: str,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """Update job stage and persist checkpoint."""
        job.stage = stage
        job.updated_at = datetime.now(timezone.utc).isoformat()
        if checkpoint_data:
            job.checkpoint.update(checkpoint_data)
        self._active_jobs[job.job_id] = job
        await self.storage.async_save_jobs(self._active_jobs)
        self._notify_job_update(job)

    async def async_start_build_pipeline(
        self,
        device: ManagedDevice,
        client: BuilderClient,
        base_url: str,
        request_id: str | None = None,
    ) -> str:
        """Start an asynchronous compile-download-verify-publish pipeline.

        Returns job_id immediately.
        """
        req_id = request_id or str(uuid.uuid4())
        device_req_key = f"{device.device_id}:{req_id}"

        if device_req_key in self._in_flight_requests:
            raise EsphomeOtaError(f"Duplicate request already in progress for {device.device_id}")

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        self._in_flight_requests.add(device_req_key)

        # Version allocation
        if device.own_project_version:
            target_version = device.own_project_version
        elif device.last_published_version:
            target_version = bump_patch_version(device.last_published_version)
        else:
            target_version = device.managed_version or "1.0.0"

        job = PipelineJob(
            job_id=job_id,
            device_id=device.device_id,
            configuration=device.configuration,
            request_id=req_id,
            stage=STAGE_PREPARING,
            reserved_version=target_version,
        )
        self._active_jobs[job_id] = job
        await self.storage.async_save_jobs(self._active_jobs)
        self._notify_job_update(job)

        task = asyncio.create_task(
            self._run_pipeline(job, device, client, base_url, device_req_key)
        )
        self._active_tasks[job_id] = task
        return job_id

    async def _run_pipeline(
        self,
        job: PipelineJob,
        device: ManagedDevice,
        client: BuilderClient,
        base_url: str,
        device_req_key: str,
    ) -> None:
        """Execute the pipeline steps under device lock."""
        lock = self.device_manager.get_lock(device.device_id)

        try:
            async with lock:
                # 1. Preparing YAML configuration and managing version
                await self._update_stage(job, STAGE_PREPARING)
                current_yaml = await client.get_config(device.configuration)
                own_ver = own_project_version(current_yaml)
                if own_ver:
                    job.reserved_version = own_ver
                    device.own_project_version = own_ver
                else:
                    device.own_project_version = None
                    diff_res = apply_ota_patch(
                        yaml_content=current_yaml,
                        base_url=base_url,
                        slug=device.slug,
                        target_version=job.reserved_version,
                        node=device.name,
                    )
                    if diff_res.modified != current_yaml:
                        _LOGGER.info(
                            "Updating YAML for %s to version %s prior to compile",
                            device.configuration,
                            job.reserved_version,
                        )
                        await client.update_config(
                            configuration=device.configuration,
                            content=diff_res.modified,
                            expected=current_yaml,
                        )
                    device.managed_version = job.reserved_version

                await self.storage.async_save_devices(self.device_manager._managed_devices)

                # 2. Validating configuration
                await self._update_stage(job, STAGE_VALIDATING)
                await client.validate_config(device.configuration)

                # 3. Submitting compile job to Builder
                await self._update_stage(job, STAGE_SUBMITTING)
                b_job_id = await client.start_compile(device.configuration)
                job.builder_job_id = b_job_id
                await self._update_stage(
                    job, STAGE_QUEUED, {"builder_job_id": b_job_id}
                )

                # 4. Following and streaming compile progress
                await self._update_stage(job, STAGE_BUILDING)

                def _append_log(line: str) -> None:
                    job.log_tail.append(line)
                    if len(job.log_tail) > MAX_LOG_TAIL_LINES:
                        job.log_tail = job.log_tail[-MAX_LOG_TAIL_LINES:]
                    self._notify_job_update(job)

                await client.wait_for_compile_completion(
                    configuration=device.configuration,
                    job_id=b_job_id,
                    on_output=_append_log,
                )

                # 5. Downloading firmware binary
                await self._update_stage(job, STAGE_DOWNLOADING)
                blob = await client.download_ota(device.configuration)

                # 6. Verifying binary structure and chip family
                await self._update_stage(job, STAGE_VERIFYING)
                info = inspect_binary(
                    blob=blob,
                    target_platform=device.target_platform,
                    expected_chip=device.chip_family,
                    reserved_version=job.reserved_version,
                )
                if job.reserved_version and info.authoritative_version != job.reserved_version:
                    raise BinaryValidationError(
                        f"Compiled binary version '{info.authoritative_version}' does not match expected version '{job.reserved_version}'"
                    )
                job.binary_version = info.authoritative_version
                job.chip_family = info.chip_family
                job.size = info.size
                job.md5 = info.md5
                job.sha256 = info.sha256

                # 7. Publishing artifact atomically
                await self._update_stage(job, STAGE_PUBLISHING)
                published = await self.publisher.async_publish(
                    device_id=device.device_id,
                    configuration=device.configuration,
                    slug=device.slug,
                    blob=blob,
                    info=info,
                    title=device.friendly_name,
                )

                # Record successful publish in storage and devices
                artifacts = await self.storage.async_load_artifacts()
                artifacts[device.device_id] = published
                await self.storage.async_save_artifacts(artifacts)
                await self.device_manager.async_mark_published(
                    device.device_id, published.version
                )

                await self._update_stage(job, STAGE_PUBLISHED)
                _LOGGER.info(
                    "Pipeline succeeded for %s: published version %s",
                    device.configuration,
                    published.version,
                )

        except asyncio.CancelledError:
            _LOGGER.info("Pipeline job %s was cancelled", job.job_id)
            if job.builder_job_id:
                await client.cancel_job(job.builder_job_id)
            await self._update_stage(job, STAGE_CANCELLED)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Pipeline job %s failed: %s", job.job_id, err)
            job.error = str(err)
            await self._update_stage(job, STAGE_FAILED, {"error": str(err)})
        finally:
            self._in_flight_requests.discard(device_req_key)
            self._active_tasks.pop(job.job_id, None)

    async def async_cancel_job(
        self,
        job_id: str,
        client: BuilderClient | None = None,
    ) -> None:
        """Cancel a running pipeline job."""
        job = self._active_jobs.get(job_id)
        if not job:
            return

        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()

        if client and job.builder_job_id:
            await client.cancel_job(job.builder_job_id)

        await self._update_stage(job, STAGE_CANCELLED)

    async def async_republish(
        self,
        device: ManagedDevice,
        artifact: PublishedArtifact,
    ) -> PublishedArtifact:
        """Republish an existing private artifact without re-compiling."""
        blob = await self.publisher.async_load_private_artifact(artifact.private_path)
        info = inspect_binary(
            blob=blob,
            target_platform=device.target_platform,
            expected_chip=artifact.chip_family,
            reserved_version=artifact.version,
        )
        published = await self.publisher.async_publish(
            device_id=device.device_id,
            configuration=device.configuration,
            slug=device.slug,
            blob=blob,
            info=info,
            title=device.friendly_name,
        )
        artifacts = await self.storage.async_load_artifacts()
        artifacts[device.device_id] = published
        await self.storage.async_save_artifacts(artifacts)
        await self.device_manager.async_mark_published(device.device_id, published.version)
        return published
