"""Pipeline job runner managing compile, download, verify, and publish lifecycle."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import re

from homeassistant.core import HomeAssistant

from .builder.client import BuilderClient
from .config_patch import (
    apply_ota_patch,
    bump_patch_version,
    has_unclear_project_ownership,
    own_project_version,
    set_project_version,
)
from .const import (
    MAX_LOG_TAIL_LINES,
    STAGE_BUILDING,
    STAGE_CANCELLED,
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
    BuilderConnectionError,
    BuilderError,
    EsphomeOtaError,
    ManagedDevice,
    PipelineJob,
    PublishedArtifact,
)
from .publisher import ArtifactPublisher
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)


def _is_unresolved_version(version: str | None) -> bool:
    """Return whether a version still contains an ESPHome substitution template."""
    return bool(version and ("$" in version or "{" in version or "}" in version))


# Mirrors legacy server.py _ANSI_RE: strip ANSI and CSI escape sequences from logs
_ANSI_STRIP_RE = re.compile(r"(\x1b|\033|\\033)\[[0-?]*[ -/]*[@-~]")


def _clean_log_line(line: str) -> str:
    """Sanitize build output line by removing ANSI escape sequences and tofu characters."""
    if not line:
        return ""
    cleaned = _ANSI_STRIP_RE.sub("", line)
    cleaned = cleaned.replace("\ufffd", "").replace("\x1b", "")
    return cleaned.rstrip("\r\n")


def _parse_iso_or_timestamp(val: Any) -> float | None:
    """Parse ISO formatted timestamp or numeric unix timestamp to float seconds."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val_str = val.strip()
        try:
            dt = datetime.fromisoformat(val_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
        try:
            return float(val_str)
        except (ValueError, TypeError):
            pass
    return None


class JobRunner:
    """Orchestrates build and publish pipeline jobs with checkpoints and recovery."""

    def __init__(
        self,
        hass: HomeAssistant,
        storage: StorageManager,
        device_manager: DeviceManager,
        publisher: ArtifactPublisher,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        monitor: Any | None = None,
    ) -> None:
        self.hass = hass
        self.storage = storage
        self.device_manager = device_manager
        self.publisher = publisher
        self.event_callback = event_callback
        self.monitor = monitor
        self._active_jobs: dict[str, PipelineJob] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._in_flight_requests: set[str] = set()
        self._cancelled_jobs: set[str] = set()
        self._unloaded = False

    async def async_unload(self) -> None:
        """Cancel and clean up all active pipeline tasks on integration unload."""
        self._unloaded = True
        for job_id in list(self._active_tasks):
            self._cancelled_jobs.add(job_id)
        tasks = list(self._active_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()
        self._in_flight_requests.clear()

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
        if self._unloaded:
            return
        if self.event_callback:
            self.event_callback("job_updated", job.to_dict())

    def _publication_cleanup_hours(self, device: ManagedDevice) -> int:
        """Resolve a per-device override against the integration default."""
        if device.publication_cleanup_hours is not None:
            return device.publication_cleanup_hours
        return self.monitor.cleanup_hours if self.monitor else 12

    def _job_cleanup_hours(self, job: PipelineJob, device: ManagedDevice) -> int:
        return int(
            job.checkpoint.get("cleanup_hours", self._publication_cleanup_hours(device))
        )

    @staticmethod
    def _job_auto_hide(job: PipelineJob, device: ManagedDevice) -> bool:
        return bool(job.checkpoint.get("auto_hide", device.auto_hide))

    async def _update_stage(
        self,
        job: PipelineJob,
        stage: str,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> None:
        """Update job stage and persist checkpoint."""
        if self._unloaded:
            return
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
        target_version: str | None = None,
        cleanup_hours: int | None = None,
        auto_hide: bool | None = None,
    ) -> str:
        """Start an asynchronous compile-download-verify-publish pipeline.

        Returns job_id immediately.
        """
        req_id = request_id or str(uuid.uuid4())
        device_req_key = f"{device.device_id}:{req_id}"
        if device_req_key in self._in_flight_requests:
            raise EsphomeOtaError(
                f"Duplicate request already in progress for {device.device_id}"
            )

        # Prevent concurrent build requests for the same device
        active_for_dev = [
            j
            for j in self._active_jobs.values()
            if j.device_id == device.device_id
            and j.stage not in (STAGE_PUBLISHED, STAGE_FAILED, STAGE_CANCELLED)
        ]
        if active_for_dev:
            raise EsphomeOtaError(
                f"A build job is already active for {device.device_id} (job {active_for_dev[0].job_id})"
            )

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        self._in_flight_requests.add(device_req_key)

        # Version allocation (provisional; re-evaluated under device lock)
        override = (target_version or "").strip() or None
        if override:
            provisional_version = override
        elif device.own_project_version:
            provisional_version = device.own_project_version
        elif device.last_published_version:
            provisional_version = bump_patch_version(device.last_published_version)
        else:
            provisional_version = device.managed_version or "1.0.0"

        job = PipelineJob(
            job_id=job_id,
            device_id=device.device_id,
            configuration=device.configuration,
            request_id=req_id,
            stage=STAGE_PREPARING,
            reserved_version=provisional_version,
            checkpoint={"version_override": override} if override else {},
        )
        # Snapshot the effective publication policy with the job so defaults
        # changing while a long build is running cannot change its outcome.
        job.checkpoint["cleanup_hours"] = (
            self._publication_cleanup_hours(device)
            if cleanup_hours is None
            else cleanup_hours
        )
        job.checkpoint["auto_hide"] = (
            device.auto_hide if auto_hide is None else auto_hide
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
                # 1. Preparing YAML configuration and managing version under lock
                await self._update_stage(job, STAGE_PREPARING)
                current_yaml = await client.get_config(device.configuration)
                original_yaml = current_yaml
                own_ver = own_project_version(current_yaml)
                unclear = has_unclear_project_ownership(current_yaml)

                # Re-evaluate version based on override or latest published version inside lock
                version_override = job.checkpoint.get("version_override")
                override = (
                    str(version_override).strip() if version_override else None
                ) or None

                # Query builder for evaluated device version if available
                builder_version = None
                try:
                    builder_devs = await client.list_devices()
                    matching = next(
                        (
                            d
                            for d in builder_devs
                            if d.get("configuration") == device.configuration
                            or d.get("name") == device.name
                        ),
                        None,
                    )
                    if matching:
                        builder_version = matching.get("project_version")
                except Exception as b_err:  # noqa: BLE001
                    _LOGGER.debug("Could not query builder devices: %s", b_err)

                if override:
                    # If device YAML declares its own project version at top-level or in an inline package,
                    # synchronize it so the ESPHome compiler uses the target version.
                    if own_ver:
                        synced_yaml, synced = set_project_version(
                            current_yaml, override
                        )
                        if synced:
                            current_yaml = synced_yaml
                            device.own_project_version = override
                        else:
                            raise BuilderError(
                                f"Cannot update project version in {device.configuration} to '{override}'. "
                                "The current project version is defined in an external include or immutable configuration. "
                                "Please update the project version in the source file directly."
                            )
                    job.reserved_version = override
                    target_patch_version = override
                    device.managed_version = override
                    self._notify_job_update(job)
                elif own_ver:
                    if ("$" in own_ver or "{" in own_ver) and builder_version:
                        job.reserved_version = builder_version
                        device.own_project_version = builder_version
                    else:
                        job.reserved_version = own_ver
                        device.own_project_version = own_ver
                    target_patch_version = job.reserved_version
                else:
                    if device.last_published_version:
                        job.reserved_version = bump_patch_version(
                            device.last_published_version
                        )
                    else:
                        job.reserved_version = device.managed_version or "1.0.0"
                    target_patch_version = job.reserved_version
                    device.managed_version = job.reserved_version
                    self._notify_job_update(job)

                if unclear and not override and not own_ver:
                    raise BuilderError(
                        f"Cannot build {device.configuration}: project ownership is ambiguous due to external configuration includes or unresolved substitutions. Manual review required."
                    )

                diff_res = apply_ota_patch(
                    yaml_content=current_yaml,
                    base_url=base_url,
                    slug=device.slug,
                    target_version=target_patch_version,
                    node=device.name,
                )
                final_yaml = diff_res.modified
                if final_yaml != original_yaml:
                    _LOGGER.info(
                        "Updating YAML for %s (version: %s) prior to compile",
                        device.configuration,
                        job.reserved_version,
                    )
                    await client.update_config(
                        configuration=device.configuration,
                        content=final_yaml,
                        expected=original_yaml,
                    )

                await self.storage.async_save_devices(
                    self.device_manager._managed_devices
                )

                # 2. Validating configuration
                await self._update_stage(job, STAGE_VALIDATING)
                await client.validate_config(device.configuration)

                # 3. Submitting compile job to Builder
                submitting_time = datetime.now(timezone.utc).isoformat()
                job.checkpoint["submitted_at"] = submitting_time
                try:
                    prior_jobs = await client.get_jobs(
                        configuration=device.configuration
                    )
                    job.checkpoint["prior_job_ids"] = [
                        str(pj["job_id"]) for pj in prior_jobs if pj.get("job_id")
                    ]
                except Exception as p_err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Could not snapshot prior builder jobs for %s: %s",
                        job.job_id,
                        p_err,
                    )
                await self._update_stage(job, STAGE_SUBMITTING)
                b_job_id = await client.start_compile(device.configuration)
                job.builder_job_id = b_job_id
                await self._update_stage(
                    job, STAGE_QUEUED, {"builder_job_id": b_job_id}
                )

                # 4. Following and streaming compile progress
                await self._update_stage(job, STAGE_BUILDING)

                def _append_log(line: str) -> None:
                    cleaned = _clean_log_line(line)
                    if cleaned:
                        job.log_tail.append(cleaned)
                        if len(job.log_tail) > MAX_LOG_TAIL_LINES:
                            job.log_tail = job.log_tail[-MAX_LOG_TAIL_LINES:]
                        self._notify_job_update(job)

                await client.wait_for_compile_completion(
                    configuration=device.configuration,
                    job_id=b_job_id,
                    on_output=_append_log,
                )

                if self._unloaded:
                    return

                # 5. Downloading firmware binary
                await self._update_stage(job, STAGE_DOWNLOADING)
                blob = await client.download_ota(
                    device.configuration,
                    platform_hint=device.target_platform,
                )

                if self._unloaded:
                    return

                # 6. Verifying binary structure and chip family
                await self._update_stage(job, STAGE_VERIFYING)
                info = inspect_binary(
                    blob=blob,
                    target_platform=device.target_platform,
                    expected_chip=device.chip_family,
                    reserved_version=(
                        None
                        if _is_unresolved_version(job.reserved_version)
                        else job.reserved_version
                    ),
                )
                is_user_owned = device.own_project_version is not None or (
                    _is_unresolved_version(job.reserved_version)
                )

                # Concrete reserved versions must match the binary. Template values
                # cannot be compared until ESPHome resolves them during compilation.
                if (
                    job.reserved_version
                    and not _is_unresolved_version(job.reserved_version)
                    and info.authoritative_version != job.reserved_version
                ):
                    raise BuilderError(
                        f"Compiled binary version '{info.authoritative_version}' differs from planned version '{job.reserved_version}' for {device.configuration}; refusing to publish"
                    )

                job.reserved_version = info.authoritative_version
                if is_user_owned:
                    device.own_project_version = info.authoritative_version
                device.target_version = info.authoritative_version
                job.binary_version = info.authoritative_version
                job.chip_family = info.chip_family
                device.chip_family = info.chip_family
                job.size = info.size
                job.md5 = info.md5
                job.sha256 = info.sha256

                if (
                    self._unloaded
                    or job.job_id in self._cancelled_jobs
                    or job.stage == STAGE_CANCELLED
                ):
                    return

                # 7. Publishing artifact atomically
                await self._update_stage(job, STAGE_PUBLISHING)
                published = await self.publisher.async_publish(
                    device_id=device.device_id,
                    configuration=device.configuration,
                    slug=device.slug,
                    blob=blob,
                    info=info,
                    title=device.friendly_name,
                    check_cancelled=lambda: (
                        self._unloaded
                        or job.job_id in self._cancelled_jobs
                        or job.stage == STAGE_CANCELLED
                    ),
                    cleanup_hours=self._job_cleanup_hours(job, device),
                    auto_hide=self._job_auto_hide(job, device),
                )

                if (
                    self._unloaded
                    or job.job_id in self._cancelled_jobs
                    or job.stage == STAGE_CANCELLED
                ):
                    return

                # Record successful publish in storage and devices
                await self.storage.async_save_artifact(device.device_id, published)
                await self.device_manager.async_mark_published(
                    device.device_id,
                    published.version,
                    published.expires_at,
                    published.published_at,
                )

                # Schedule automatic cleanup and trigger immediate update entity check
                if self.monitor:
                    self.monitor.schedule_cleanup(
                        device.device_id,
                        device.slug,
                        artifact_id=published.published_at,
                        expires_at=published.expires_at,
                        cleanup_hours=published.cleanup_hours,
                    )
                    await self.monitor.async_refresh_entity(device.device_id)

                # Emit devices_updated so UI device cards update immediately
                if self.event_callback:
                    self.event_callback(
                        "devices_updated", {"devices": self.device_manager.list_all()}
                    )

                await self._update_stage(job, STAGE_PUBLISHED)
                _LOGGER.info(
                    "Pipeline succeeded for %s: published version %s",
                    device.configuration,
                    published.version,
                )

        except asyncio.CancelledError:
            _LOGGER.info("Pipeline job %s was cancelled", job.job_id)
            self._cancelled_jobs.add(job.job_id)
            if self._unloaded:
                _LOGGER.info(
                    "Integration unloaded; stopped tracking pipeline %s without remote builder cancellation",
                    job.job_id,
                )
                return
            if job.builder_job_id:
                await client.cancel_job(job.builder_job_id)
            await self._update_stage(job, STAGE_CANCELLED)
        except BuilderConnectionError as err:
            _LOGGER.warning(
                "Builder connection lost during job %s: %s", job.job_id, err
            )
            if not job.builder_job_id:
                if job.stage == STAGE_SUBMITTING:
                    job.error = "Connection lost while submitting compile request; recovery required"
                    await self._update_stage(
                        job, STAGE_RECOVERY_REQUIRED, {"error": job.error}
                    )
                else:
                    job.error = str(err)
                    await self._update_stage(job, STAGE_FAILED, {"error": str(err)})
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Pipeline job %s failed: %s", job.job_id, err)
            job.error = str(err)
            await self._update_stage(job, STAGE_FAILED, {"error": str(err)})
        finally:
            self._in_flight_requests.discard(device_req_key)
            self._active_tasks.pop(job.job_id, None)

    async def async_resume_jobs(
        self,
        client: BuilderClient,
        base_url: str,
    ) -> None:
        """Resume in-flight jobs after Builder reconnection or HA restart."""
        for job in list(self._active_jobs.values()):
            if job.stage in (STAGE_PUBLISHED, STAGE_FAILED, STAGE_CANCELLED):
                continue

            task = self._active_tasks.get(job.job_id)
            if task and not task.done():
                continue

            device = self.device_manager.get_device(job.device_id)
            if not device:
                continue

            if job.stage == STAGE_RECOVERY_REQUIRED or (
                job.stage == STAGE_SUBMITTING and not job.builder_job_id
            ):
                _LOGGER.info(
                    "Checking Builder active jobs to recover unacknowledged job %s for %s",
                    job.job_id,
                    job.configuration,
                )
                try:
                    builder_jobs = await client.get_jobs()
                except Exception as rec_err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed checking builder jobs for recovery of %s: %s. Maintaining recovery_required.",
                        job.job_id,
                        rec_err,
                    )
                    if job.stage != STAGE_RECOVERY_REQUIRED:
                        await self._update_stage(
                            job, STAGE_RECOVERY_REQUIRED, {"error": str(rec_err)}
                        )
                    continue

                job_ts = _parse_iso_or_timestamp(job.created_at)
                submitted_ts = _parse_iso_or_timestamp(
                    job.checkpoint.get("submitted_at")
                )
                prior_job_ids = set(job.checkpoint.get("prior_job_ids", []))
                ref_ts = submitted_ts if submitted_ts is not None else job_ts

                matching_candidates: list[dict[str, Any]] = []
                for bj in builder_jobs:
                    if bj.get("configuration") != job.configuration:
                        continue

                    bj_id = str(bj.get("job_id", ""))
                    # Exclude job IDs that existed before submission was initiated
                    if bj_id and bj_id in prior_job_ids:
                        continue

                    # Check job type (must be compile, reject upload, install, clean, etc.)
                    bj_type = bj.get("job_type") or bj.get("type")
                    if bj_type and str(bj_type).lower() not in (
                        "compile",
                        "firmware_compile",
                    ):
                        continue

                    # Check status
                    status = str(bj.get("status", "")).lower()
                    if status not in ("running", "queued", "completed"):
                        continue

                    # Check submission timestamp (reject jobs submitted before this pipeline job was created/submitted)
                    raw_bj_ts = (
                        bj.get("created_at")
                        or bj.get("submitted_at")
                        or bj.get("started_at")
                        or bj.get("timestamp")
                    )
                    bj_ts = _parse_iso_or_timestamp(raw_bj_ts)
                    if ref_ts is not None:
                        if bj_ts is None:
                            # Timestamp is missing; cannot definitively link candidate to this request
                            continue
                        if bj_ts < ref_ts:
                            # Job was submitted before this pipeline job request; reject past job!
                            continue

                    matching_candidates.append(bj)

                if len(matching_candidates) == 1 and matching_candidates[0].get(
                    "job_id"
                ):
                    matching = matching_candidates[0]
                    job.builder_job_id = str(matching["job_id"])
                    _LOGGER.info(
                        "Recovered builder_job_id=%s for job %s",
                        job.builder_job_id,
                        job.job_id,
                    )
                    self._active_tasks[job.job_id] = asyncio.create_task(
                        self._resume_pipeline(job, device, client, base_url)
                    )
                    continue
                else:
                    _LOGGER.warning(
                        "Cannot uniquely connect job %s to Builder jobs (found %d candidates). Maintaining recovery_required.",
                        job.job_id,
                        len(matching_candidates),
                    )
                    if job.stage != STAGE_RECOVERY_REQUIRED:
                        await self._update_stage(
                            job,
                            STAGE_RECOVERY_REQUIRED,
                            {
                                "detail": f"Unambiguous candidate not found ({len(matching_candidates)} candidates)"
                            },
                        )
                    continue

            if job.builder_job_id:
                _LOGGER.info(
                    "Resuming tracking for pipeline job %s (builder_job_id=%s)",
                    job.job_id,
                    job.builder_job_id,
                )
                self._active_tasks[job.job_id] = asyncio.create_task(
                    self._resume_pipeline(job, device, client, base_url)
                )
            elif job.stage in (STAGE_PREPARING, STAGE_VALIDATING):
                _LOGGER.warning(
                    "Failing unsubmitted pipeline job %s interrupted before compile submission",
                    job.job_id,
                )
                job.error = "Interrupted before compile submission"
                await self._update_stage(job, STAGE_FAILED, {"error": job.error})

    async def _resume_pipeline(
        self,
        job: PipelineJob,
        device: ManagedDevice,
        client: BuilderClient,
        base_url: str,
    ) -> None:
        """Resume an active compile job from Builder checkpoint."""
        lock = self.device_manager.get_lock(device.device_id)
        device_req_key = f"{device.device_id}:{job.request_id}"
        self._in_flight_requests.add(device_req_key)

        try:
            async with lock:
                assert job.builder_job_id is not None
                b_job_id = job.builder_job_id

                # Query compile status on Builder
                job_info = await client.get_job(b_job_id)
                status = job_info.get("status")
                if status == "cancelled":
                    _LOGGER.info(
                        "Resumed compile job %s was cancelled on remote builder",
                        b_job_id,
                    )
                    job.error = "Compile job was cancelled on remote builder"
                    await self._update_stage(job, STAGE_CANCELLED, {"error": job.error})
                    return
                if status == "failed":
                    raise BuilderError(
                        f"Compile job {b_job_id} failed on remote builder"
                    )
                if not status or status not in ("running", "queued", "completed"):
                    raise BuilderError(
                        f"Compile job {b_job_id} has invalid status on builder: '{status}'"
                    )

                if status in ("running", "queued"):
                    await self._update_stage(job, STAGE_BUILDING)

                    def _append_log(line: str) -> None:
                        cleaned = _clean_log_line(line)
                        if cleaned:
                            job.log_tail.append(cleaned)
                            if len(job.log_tail) > MAX_LOG_TAIL_LINES:
                                job.log_tail = job.log_tail[-MAX_LOG_TAIL_LINES:]
                            self._notify_job_update(job)

                    await client.wait_for_compile_completion(
                        configuration=device.configuration,
                        job_id=b_job_id,
                        on_output=_append_log,
                    )
                elif status != "completed":
                    raise BuilderError(
                        f"Compile job {b_job_id} is not completed (status={status})"
                    )

                if self._unloaded:
                    return

                # Download, verify, and publish
                await self._update_stage(job, STAGE_DOWNLOADING)
                blob = await client.download_ota(
                    device.configuration,
                    platform_hint=device.target_platform,
                )

                if self._unloaded:
                    return

                await self._update_stage(job, STAGE_VERIFYING)
                info = inspect_binary(
                    blob=blob,
                    target_platform=device.target_platform,
                    expected_chip=device.chip_family,
                    reserved_version=(
                        None
                        if _is_unresolved_version(job.reserved_version)
                        else job.reserved_version
                    ),
                )
                is_user_owned = device.own_project_version is not None or (
                    _is_unresolved_version(job.reserved_version)
                )

                if (
                    job.reserved_version
                    and not _is_unresolved_version(job.reserved_version)
                    and info.authoritative_version != job.reserved_version
                ):
                    raise BuilderError(
                        f"Compiled binary version '{info.authoritative_version}' differs from planned version '{job.reserved_version}' for {device.configuration}; refusing to publish"
                    )

                job.reserved_version = info.authoritative_version
                if is_user_owned:
                    device.own_project_version = info.authoritative_version
                device.target_version = info.authoritative_version

                job.binary_version = info.authoritative_version
                job.chip_family = info.chip_family
                job.size = info.size
                job.md5 = info.md5
                job.sha256 = info.sha256

                if (
                    self._unloaded
                    or job.job_id in self._cancelled_jobs
                    or job.stage == STAGE_CANCELLED
                ):
                    return

                await self._update_stage(job, STAGE_PUBLISHING)
                published = await self.publisher.async_publish(
                    device_id=device.device_id,
                    configuration=device.configuration,
                    slug=device.slug,
                    blob=blob,
                    info=info,
                    title=device.friendly_name,
                    check_cancelled=lambda: (
                        self._unloaded
                        or job.job_id in self._cancelled_jobs
                        or job.stage == STAGE_CANCELLED
                    ),
                    cleanup_hours=self._job_cleanup_hours(job, device),
                    auto_hide=self._job_auto_hide(job, device),
                )

                if (
                    self._unloaded
                    or job.job_id in self._cancelled_jobs
                    or job.stage == STAGE_CANCELLED
                ):
                    return

                await self.storage.async_save_artifact(device.device_id, published)
                await self.device_manager.async_mark_published(
                    device.device_id,
                    published.version,
                    published.expires_at,
                    published.published_at,
                )

                if self.monitor:
                    self.monitor.schedule_cleanup(
                        device.device_id,
                        device.slug,
                        artifact_id=published.published_at,
                        expires_at=published.expires_at,
                        cleanup_hours=published.cleanup_hours,
                    )
                    await self.monitor.async_refresh_entity(device.device_id)

                # Emit devices_updated so UI device cards update immediately
                if self.event_callback:
                    self.event_callback(
                        "devices_updated", {"devices": self.device_manager.list_all()}
                    )

                await self._update_stage(job, STAGE_PUBLISHED)
                _LOGGER.info(
                    "Resumed job %s successfully completed and published version %s",
                    job.job_id,
                    published.version,
                )

        except asyncio.CancelledError:
            _LOGGER.info("Resumed pipeline job %s was cancelled", job.job_id)
            self._cancelled_jobs.add(job.job_id)
            if self._unloaded:
                return
            if job.builder_job_id:
                await client.cancel_job(job.builder_job_id)
            await self._update_stage(job, STAGE_CANCELLED)
        except BuilderConnectionError as err:
            _LOGGER.warning(
                "Connection lost again while resuming job %s: %s", job.job_id, err
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Resumed job %s failed: %s", job.job_id, err)
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

        self._cancelled_jobs.add(job_id)
        job.stage = STAGE_CANCELLED

        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception) as err:  # noqa: BLE001
                _LOGGER.debug("Cancelled task for job %s completed: %s", job_id, err)
        elif client and job.builder_job_id:
            await client.cancel_job(job.builder_job_id)

        await self._update_stage(job, STAGE_CANCELLED)

    async def async_republish(
        self,
        device: ManagedDevice,
        artifact: PublishedArtifact,
    ) -> PublishedArtifact:
        """Republish an existing private artifact without re-compiling."""
        async with self.device_manager.get_lock(device.device_id):
            artifacts = await self.storage.async_load_artifacts()
            current = artifacts.get(device.device_id)
            if not current:
                raise EsphomeOtaError("No private artifact exists for this device")
            return await self._async_republish_locked(device, current)

    async def _async_republish_locked(
        self,
        device: ManagedDevice,
        artifact: PublishedArtifact,
    ) -> PublishedArtifact:
        """Republish while holding the device mutation lock."""
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
            check_cancelled=lambda: self._unloaded,
            cleanup_hours=self._publication_cleanup_hours(device),
            auto_hide=device.auto_hide,
        )
        await self.storage.async_save_artifact(device.device_id, published)
        await self.device_manager.async_mark_published(
            device.device_id,
            published.version,
            published.expires_at,
            published.published_at,
        )

        if self.monitor:
            self.monitor.schedule_cleanup(
                device.device_id,
                device.slug,
                artifact_id=published.published_at,
                expires_at=published.expires_at,
                cleanup_hours=published.cleanup_hours,
            )
            await self.monitor.async_refresh_entity(device.device_id)

        if self.event_callback:
            self.event_callback(
                "devices_updated", {"devices": self.device_manager.list_all()}
            )

        return published
