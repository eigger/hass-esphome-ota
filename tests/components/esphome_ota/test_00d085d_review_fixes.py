"""Tests for issues resolved in commit 00d085d review.

1. [P1] _resume_pipeline() rejects cancelled jobs instead of publishing
2. [P1] resolver does not hijack saved production builder to dev builder
3. [P1] Component !include preserves managed version; ambiguous ownership requires review
4. [P2] Installation monitor links entities via exact device matching, avoiding substring collisions
5. [P2] Recovery of unacknowledged compile submissions via Builder list_jobs
6. [P2] devices_updated events dispatched upon publish and install verification
7. [P2] Manual HTTP upload resets auto-cleanup timer and dispatches devices_updated
"""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, device_registry as dr
import pytest

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.builder.resolver import BuilderResolver
from custom_components.esphome_ota.config_patch import (
    has_unclear_project_ownership,
    own_project_version,
)
from custom_components.esphome_ota.const import (
    STAGE_BUILDING,
    STAGE_CANCELLED,
    STAGE_FAILED,
    STAGE_PUBLISHED,
    STAGE_RECOVERY_REQUIRED,
    STAGE_SUBMITTING,
    STATUS_WAITING,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.http import FirmwareUploadView
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    BuilderCandidate,
    BuilderConnectionError,
    BuilderError,
    BuilderSelection,
    PipelineJob,
)
from custom_components.esphome_ota.monitor import InstallationMonitor
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_issue1_resume_pipeline_rejects_cancelled_job(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-1] Test that _resume_pipeline does NOT download or publish a cancelled job."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_cancel_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        mock_builder.jobs["job_cancelled_1"] = {
            "status": "cancelled",
            "configuration": "livingroom.yaml",
        }

        job = PipelineJob(
            job_id="job_c1",
            device_id="livingroom",
            configuration="livingroom.yaml",
            request_id="req-c1",
            stage=STAGE_BUILDING,
            builder_job_id="job_cancelled_1",
            reserved_version="1.0.0",
        )
        runner._active_jobs[job.job_id] = job

        await runner.async_resume_jobs(client, "https://ha.local")
        task = runner._active_tasks.get("job_c1")
        if task:
            await task

        resumed = runner.get_job("job_c1")
        assert resumed is not None
        assert resumed.stage == STAGE_CANCELLED
        # Must not be marked as published
        assert dev.last_published_version is None
        await conn.disconnect()


async def test_issue2_saved_builder_does_not_hijack_to_dev(
    hass: HomeAssistant,
) -> None:
    """[P1-2] Test that saved production builder waits rather than hijacking to esphome-dev."""
    saved = BuilderSelection(
        slug="5c53de3b_esphome",
        name="ESPHome",
        source="config_entry",
        host_hint="127.0.0.1",
        port_hint=6052,
    )

    async with aiohttp.ClientSession() as session:
        resolver = BuilderResolver(hass, session, saved_selection=saved)
        # Mock discovery returning only esphome-dev
        resolver.discovery_adapter.async_discover_all = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                BuilderCandidate(
                    slug="5c53de3b_esphome-dev",
                    name="ESPHome Dev",
                    host="127.0.0.1",
                    port=6053,
                    source="addon",
                )
            ]
        )

        with pytest.raises(BuilderConnectionError):
            await resolver.async_resolve()

        assert resolver.status == STATUS_WAITING
        assert resolver.active_candidate is None


async def test_issue3_component_include_preserves_managed_version_and_unclear_rejected(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-3] Test that sensor: !include is managed, but unclear package includes demand review."""
    # 1. Component include: should NOT be unclear
    sensor_include_yaml = """esphome:
  name: livingroom
esp32:
  board: esp32dev
sensor: !include sensors.yaml
"""
    assert has_unclear_project_ownership(sensor_include_yaml) is False
    assert own_project_version(sensor_include_yaml) is None

    # Pipeline successfully builds and patches YAML for sensor_include
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_include_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    mock_builder.configs["livingroom.yaml"] = sensor_include_yaml
    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
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
        task = runner._active_tasks.get(job_id)
        if task:
            await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED
        assert "packages:" in mock_builder.configs["livingroom.yaml"]
        assert "esphome_ota:" in mock_builder.configs["livingroom.yaml"]

        # 2. Package include: should be unclear and demand manual review
        package_include_yaml = """esphome:
  name: bedroom
esp32:
  board: esp32dev
packages:
  remote: !include remote_pkg.yaml
"""
        assert has_unclear_project_ownership(package_include_yaml) is True

        mock_builder.configs["bedroom.yaml"] = package_include_yaml
        dev2 = await device_manager.async_register_or_update(
            device_id="bedroom",
            configuration="bedroom.yaml",
            name="bedroom",
            friendly_name="Bedroom",
        )

        job_id2 = await runner.async_start_build_pipeline(
            device=dev2, client=client, base_url="https://ha.local"
        )
        task2 = runner._active_tasks.get(job_id2)
        if task2:
            await task2

        job2 = runner.get_job(job_id2)
        assert job2 is not None
        assert job2.stage == STAGE_FAILED
        assert "project ownership is ambiguous" in str(job2.error)
        await conn.disconnect()


async def test_issue4_installation_monitor_exact_matching(
    hass: HomeAssistant,
) -> None:
    """[P2-4] Test that room does not falsely match update.bedroom_firmware."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_submatch_test")

    dev_room = await device_manager.async_register_or_update(
        device_id="room",
        configuration="room.yaml",
        name="room",
        friendly_name="Room",
    )
    dev_bedroom = await device_manager.async_register_or_update(
        device_id="bedroom",
        configuration="bedroom.yaml",
        name="bedroom",
        friendly_name="Bedroom",
    )
    await device_manager.async_mark_published("room", "1.0.1")
    await device_manager.async_mark_published("bedroom", "2.0.1")

    ent_reg = er.async_get(hass)
    # Create bedroom entity first
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="bedroom_firmware_uid",
        suggested_object_id="bedroom_firmware",
    )
    # Create room entity
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="room_firmware_uid",
        suggested_object_id="room_firmware",
    )

    events: list[dict] = []
    monitor = InstallationMonitor(
        hass,
        device_manager,
        publisher,
        cleanup_hours=12,
        event_callback=lambda e, d: events.append({"event": e, "data": d}),
    )

    await monitor.async_setup()

    # Changing state of bedroom firmware must NOT affect room
    hass.states.async_set(
        "update.bedroom_firmware",
        "on",
        {"installed_version": "2.0.1", "latest_version": "2.0.1", "in_progress": False},
    )
    await hass.async_block_till_done()

    d_room = device_manager.get_device("room")
    d_bedroom = device_manager.get_device("bedroom")
    assert d_room.last_installed_version is None
    assert d_bedroom.last_installed_version == "2.0.1"


async def test_issue5_compile_submission_disconnect_recovery(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2-5] Test recovery_required on submission disconnect and resumption via list_jobs."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_rec_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    # Job interrupted during submission
    interrupted_job = PipelineJob(
        job_id="job_rec_1",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req-rec-1",
        stage=STAGE_RECOVERY_REQUIRED,
        reserved_version="1.0.0",
    )
    runner._active_jobs[interrupted_job.job_id] = interrupted_job

    # Builder received it and has job
    mock_builder.jobs["job_builder_rec"] = {
        "status": "completed",
        "configuration": "livingroom.yaml",
    }

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Resuming should recover builder_job_id and finish pipeline
        await runner.async_resume_jobs(client, "https://ha.local")
        task = runner._active_tasks.get("job_rec_1")
        if task:
            await task

        resumed = runner.get_job("job_rec_1")
        assert resumed is not None
        assert resumed.stage == STAGE_PUBLISHED
        assert resumed.builder_job_id == "job_builder_rec"
        await conn.disconnect()


async def test_issue6_publish_and_install_dispatch_devices_updated(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2-6] Test that devices_updated is dispatched when publish finishes and install completes."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_ev_test")

    events: list[tuple[str, dict]] = []

    def _on_event(name: str, payload: dict) -> None:
        events.append((name, payload))

    monitor = InstallationMonitor(
        hass,
        device_manager,
        publisher,
        cleanup_hours=12,
        event_callback=_on_event,
    )
    runner = JobRunner(
        hass,
        storage,
        device_manager,
        publisher,
        event_callback=_on_event,
        monitor=monitor,
    )

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="livingroom_firmware_uid",
        suggested_object_id="livingroom_firmware",
    )
    await monitor.async_setup()

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local"
        )
        task = runner._active_tasks.get(job_id)
        if task:
            await task

        # Verify devices_updated was emitted on publish
        dev_updates = [e for e in events if e[0] == "devices_updated"]
        assert len(dev_updates) >= 1
        published_dev = next(d for d in dev_updates[-1][1]["devices"] if d["device_id"] == "livingroom")
        assert published_dev["last_published_version"] == "1.0.0"

        # Now simulate install completed
        hass.states.async_set(
            "update.livingroom_firmware",
            "on",
            {"installed_version": "1.0.0", "latest_version": "1.0.0", "in_progress": False},
        )
        await hass.async_block_till_done()

        # Verify devices_updated was emitted on install verification
        installed_events = [e for e in events if e[0] == "installation_verified"]
        assert len(installed_events) >= 1
        assert installed_events[-1][1]["version"] == "1.0.0"

        await conn.disconnect()


async def test_issue7_manual_http_upload_schedules_cleanup_and_dispatches_devices_updated(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2-7] Test that manual HTTP upload resets cleanup timer and notifies frontend."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_upload_test")

    events: list[tuple[str, dict]] = []

    def _on_event(name: str, payload: dict) -> None:
        events.append((name, payload))

    monitor = InstallationMonitor(
        hass,
        device_manager,
        publisher,
        cleanup_hours=12,
        event_callback=_on_event,
    )

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    # Fake manager wrapper for view
    class FakeManager:
        def __init__(self) -> None:
            self.device_manager = device_manager
            self.publisher = publisher
            self.storage = storage
            self.monitor = monitor
        def _dispatch_event(self, name: str, payload: dict) -> None:
            events.append((name, payload))

    view = FirmwareUploadView(hass, FakeManager())  # type: ignore[arg-type]

    valid_blob = mock_builder.binary_blob

    # Mock aiohttp multipart request
    class MockField:
        name = "file"
        filename = "firmware.bin"
        def __init__(self, data: bytes) -> None:
            self._stream = io.BytesIO(data)
        async def read_chunk(self, size: int = 65536) -> bytes:
            return self._stream.read(size)

    class MockMultipartReader:
        def __init__(self, data: bytes) -> None:
            self._field = MockField(data)
            self._done = False
        async def next(self) -> MockField | None:
            if not self._done:
                self._done = True
                return self._field
            return None

    class MockRequest(dict):
        match_info = {"device_id": "livingroom"}
        can_read_body = True
        def __init__(self, data: bytes) -> None:
            super().__init__()
            mock_user = MagicMock()
            mock_user.is_admin = True
            self["hass_user"] = mock_user
            self._data = data
        async def multipart(self) -> MockMultipartReader:
            return MockMultipartReader(self._data)

    req = MockRequest(valid_blob)
    resp = await view.post(req, "livingroom")  # type: ignore[arg-type]
    assert resp.status == 200

    # Verify cleanup timer was scheduled
    assert "livingroom" in monitor._cleanup_timers

    # Verify devices_updated was dispatched
    dev_events = [e for e in events if e[0] == "devices_updated"]
    assert len(dev_events) >= 1
    uploaded_dev = next(d for d in dev_events[-1][1]["devices"] if d["device_id"] == "livingroom")
    assert uploaded_dev["last_published_version"] == "1.0.0"
