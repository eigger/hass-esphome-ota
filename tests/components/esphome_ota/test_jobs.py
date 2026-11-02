"""Unit tests for JobRunner pipeline execution and cancellation."""

from __future__ import annotations


import aiohttp
from homeassistant.core import HomeAssistant
import pytest

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import STAGE_CANCELLED, STAGE_PUBLISHED
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.const import STAGE_FAILED
from custom_components.esphome_ota.models import EsphomeOtaError, PipelineJob
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


async def test_terminal_jobs_pruned_and_log_trimmed(hass: HomeAssistant) -> None:
    """Only the most recent finished jobs per device are kept, with short logs."""
    runner = _make_runner(hass)
    for i in range(8):
        job = PipelineJob(
            job_id=f"job_{i}",
            device_id="dev",
            configuration="dev",
            request_id=str(i),
            log_tail=[f"l{n}" for n in range(200)],
        )
        job.updated_at = f"2026-01-01T00:00:0{i}+00:00"
        runner._active_jobs[job.job_id] = job
        await runner._update_stage(job, STAGE_FAILED)
        job.updated_at = f"2026-01-01T00:00:0{i}+00:00"
    assert len(runner._active_jobs) == 5
    assert "job_0" not in runner._active_jobs
    assert all(len(j.log_tail) <= 50 for j in runner._active_jobs.values())


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
