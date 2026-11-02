"""Unit tests for JobRunner pipeline execution and cancellation."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    STAGE_BUILDING,
    STAGE_CANCELLED,
    STAGE_FAILED,
    STAGE_PUBLISHED,
    STAGE_RECOVERY_REQUIRED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    EsphomeOtaError,
    ManagedDevice,
    PipelineJob,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_job_runner_full_pipeline_success(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test full pipeline execution from preparation to published."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_job_test")

    events: list[tuple[str, dict]] = []
    runner = JobRunner(
        hass,
        storage,
        device_manager,
        publisher,
        event_callback=lambda e, d: events.append((e, d)),
    )

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://my-ha.duckdns.org",
        )
        assert job_id.startswith("job_")

        # Wait for task to finish
        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert job.binary_version == "1.0.0"
        assert len(job.log_tail) >= 2
        assert any("Compiling" in line for line in job.log_tail)

        # Device is marked published
        updated_dev = device_manager.get_device("livingroom")
        assert updated_dev.last_published_version == "1.0.0"

        await conn.disconnect()


async def test_duplicate_request_prevention(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test duplicate request ID is rejected."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_job_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        req_id = "req-12345"
        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local", request_id=req_id
        )

        with pytest.raises(
            EsphomeOtaError, match="Duplicate request already in progress"
        ):
            await runner.async_start_build_pipeline(
                device=dev,
                client=client,
                base_url="https://ha.local",
                request_id=req_id,
            )

        task = runner._active_tasks.get(job_id)
        if task:
            await task
        await conn.disconnect()


async def test_job_cancellation(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test cancelling an active job."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_job_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local"
        )
        await runner.async_cancel_job(job_id, client)

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_CANCELLED

        await conn.disconnect()


def _make_runner(hass: HomeAssistant, events: list | None = None) -> JobRunner:
    storage = StorageManager(hass)
    return JobRunner(
        hass,
        storage,
        DeviceManager(hass, storage),
        ArtifactPublisher(hass, publish_dir="esphome_ota_job_test"),
        event_callback=(lambda e, d: events.append((e, d)))
        if events is not None
        else None,
    )


async def test_terminal_jobs_pruned_and_log_trimmed_on_persist(
    hass: HomeAssistant,
) -> None:
    """Old finished jobs are pruned and announced; stored logs are short."""
    events: list = []
    runner = _make_runner(hass, events)
    for i in range(8):
        job = PipelineJob(
            job_id=f"job_{i}",
            device_id="dev",
            configuration="dev",
            request_id=str(i),
            log_tail=[f"l{n}" for n in range(200)],
        )
        runner._active_jobs[job.job_id] = job
        await runner._update_stage(job, STAGE_FAILED)
        job.updated_at = f"2026-01-01T00:00:0{i}+00:00"
    assert len(runner._active_jobs) == 5
    assert "job_0" not in runner._active_jobs
    pruned = [e[1]["job_ids"] for e in events if e[0] == "jobs_pruned"]
    assert ["job_0"] in pruned or any("job_0" in p for p in pruned)
    # In memory the just-failed job keeps its full log for the UI
    assert len(runner._active_jobs["job_7"].log_tail) == 200
    # Storage keeps only a short tail
    await runner.storage.async_save_jobs(runner._active_jobs)
    stored = await runner.storage.async_load_jobs()
    assert all(len(j.log_tail) <= 50 for j in stored.values())


async def test_prune_skips_jobs_with_active_task(hass: HomeAssistant) -> None:
    """A finished-looking job that still has a live task is not pruned."""
    runner = _make_runner(hass)
    for i in range(7):
        job = PipelineJob(
            job_id=f"job_{i}",
            device_id="dev",
            configuration="dev",
            request_id=str(i),
            stage=STAGE_FAILED,
        )
        job.updated_at = f"2026-01-01T00:00:0{i}+00:00"
        runner._active_jobs[job.job_id] = job
    runner._active_tasks["job_0"] = object()  # type: ignore[assignment]
    removed = runner._prune_jobs()
    assert "job_0" in runner._active_jobs
    assert removed == ["job_1"]


async def test_cancel_device_jobs_only_touches_active_jobs(
    hass: HomeAssistant,
) -> None:
    """cancel_device_jobs cancels non-terminal jobs of that device only."""
    runner = _make_runner(hass)
    specs = [
        ("a", "dev", STAGE_BUILDING),
        ("b", "dev", STAGE_PUBLISHED),
        ("c", "other", STAGE_BUILDING),
    ]
    for jid, dev, stage in specs:
        runner._active_jobs[jid] = PipelineJob(
            job_id=jid, device_id=dev, configuration=dev, request_id=jid, stage=stage
        )
    await runner.async_cancel_device_jobs("dev")
    assert runner._active_jobs["a"].stage == STAGE_CANCELLED
    assert runner._active_jobs["b"].stage == STAGE_PUBLISHED
    assert runner._active_jobs["c"].stage == STAGE_BUILDING


async def test_pipeline_cancelled_when_device_removed_while_queued(
    hass: HomeAssistant,
) -> None:
    """A job acquiring the lock after its device was removed is cancelled."""
    runner = _make_runner(hass)
    dev = ManagedDevice(
        device_id="gone",
        configuration="gone.yaml",
        name="gone",
        friendly_name="Gone",
        token="t",
        slug="gone_t",
    )
    job = PipelineJob(
        job_id="j", device_id="gone", configuration="gone.yaml", request_id="r"
    )
    runner._active_jobs["j"] = job
    await runner._run_pipeline(job, dev, None, "https://ha.local", "gone:r")  # type: ignore[arg-type]
    assert job.stage == STAGE_CANCELLED


async def test_recovered_builder_job_id_is_persisted(hass: HomeAssistant) -> None:
    """Recovery persists the matched builder job id before ephemeral stages."""
    runner = _make_runner(hass)
    dev = await runner.device_manager.async_register_or_update(
        device_id="dev", configuration="dev.yaml", name="dev", friendly_name="Dev"
    )
    job = PipelineJob(
        job_id="j",
        device_id=dev.device_id,
        configuration="dev.yaml",
        request_id="r",
        stage=STAGE_RECOVERY_REQUIRED,
    )
    runner._active_jobs["j"] = job

    class _Client:
        async def get_jobs(self, configuration: str | None = None) -> list[dict]:
            return [
                {
                    "job_id": "b1",
                    "configuration": "dev.yaml",
                    "status": "running",
                    "job_type": "compile",
                    "created_at": "2999-01-01T00:00:00+00:00",
                }
            ]

    resumed: list[str] = []

    async def _fake_resume(*args: object) -> None:
        resumed.append("x")

    runner._resume_pipeline = _fake_resume  # type: ignore[method-assign]
    await runner.async_resume_jobs(_Client(), "https://ha.local")  # type: ignore[arg-type]
    await runner._active_tasks["j"]
    stored = await runner.storage.async_load_jobs()
    assert stored["j"].builder_job_id == "b1"
    assert stored["j"].checkpoint["builder_job_id"] == "b1"
    assert resumed


async def test_ephemeral_stages_not_persisted(hass: HomeAssistant) -> None:
    """BUILDING transitions are broadcast but not written to storage."""
    runner = _make_runner(hass)
    job = PipelineJob(
        job_id="j", device_id="d", configuration="d", request_id="r", builder_job_id="b"
    )
    runner._active_jobs["j"] = job
    await runner._update_stage(job, "queued")
    await runner._update_stage(job, STAGE_BUILDING)
    stored = await runner.storage.async_load_jobs()
    assert stored["j"].stage == "queued"
    assert stored["j"].builder_job_id == "b"


async def test_cancel_terminal_job_is_ignored(hass: HomeAssistant) -> None:
    """Cancelling a finished job neither rewrites its stage nor calls the builder."""
    runner = _make_runner(hass)
    job = PipelineJob(
        job_id="job_x",
        device_id="dev",
        configuration="dev",
        request_id="r",
        stage=STAGE_PUBLISHED,
        builder_job_id="b1",
    )
    runner._active_jobs[job.job_id] = job

    class _Client:
        cancelled = False

        async def cancel_job(self, _id: str) -> None:
            self.cancelled = True

    client = _Client()
    await runner.async_cancel_job("job_x", client)  # type: ignore[arg-type]
    assert job.stage == STAGE_PUBLISHED
    assert client.cancelled is False


async def test_log_lines_emit_incremental_events_without_heartbeat(
    hass: HomeAssistant,
) -> None:
    """Log lines produce job_log events; heartbeat lines are not stored."""
    events: list = []
    runner = _make_runner(hass, events)
    job = PipelineJob(job_id="j", device_id="d", configuration="d", request_id="r")
    runner._append_job_log(job, "\x1b[32mCompiling\x1b[0m")
    runner._append_job_log(job, "... still building (job abc) ...")
    assert job.log_tail == ["Compiling"]
    assert events == [
        ("job_log", {"job_id": "j", "device_id": "d", "line": "Compiling"})
    ]


async def test_cancel_paths_survive_remote_cancel_failure(hass: HomeAssistant) -> None:
    """A failing Builder cancel still lets the job reach CANCELLED."""
    from custom_components.esphome_ota.models import BuilderConnectionError

    class _Client:
        async def cancel_job(self, _id: str) -> None:
            raise BuilderConnectionError("down")

    runner = _make_runner(hass)
    dev = ManagedDevice(
        device_id="gone",
        configuration="gone.yaml",
        name="gone",
        friendly_name="Gone",
        token="t",
        slug="gone_t",
    )
    j1 = PipelineJob(
        job_id="j1",
        device_id="gone",
        configuration="gone.yaml",
        request_id="r1",
        builder_job_id="b1",
    )
    runner._active_jobs["j1"] = j1
    assert await runner._cancel_if_device_removed(j1, dev, _Client()) is True  # type: ignore[arg-type]
    assert j1.stage == STAGE_CANCELLED

    j2 = PipelineJob(
        job_id="j2",
        device_id="gone",
        configuration="gone.yaml",
        request_id="r2",
        builder_job_id="b2",
        stage=STAGE_BUILDING,
    )
    runner._active_jobs["j2"] = j2
    await runner.async_cancel_job("j2", _Client())  # type: ignore[arg-type]
    assert j2.stage == STAGE_CANCELLED
