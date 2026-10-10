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
from custom_components.esphome_ota.models import EsphomeOtaError
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
        hass, storage, device_manager, publisher, event_callback=lambda e, d: events.append((e, d))
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

        with pytest.raises(EsphomeOtaError, match="Duplicate request already in progress"):
            await runner.async_start_build_pipeline(
                device=dev, client=client, base_url="https://ha.local", request_id=req_id
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
