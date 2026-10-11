"""Regression and unit test suite for the 8 P1/P2 issues identified in the code review."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import aiohttp
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.builder.resolver import BuilderResolver
from custom_components.esphome_ota.config_patch import (
    own_project_version,
)
from custom_components.esphome_ota.const import (
    CONF_BASE_URL,
    CONF_BUILDER_SLUG,
    DOMAIN,
    STAGE_BUILDING,
    STAGE_PUBLISHED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    BuilderCandidate,
    BuilderConnectionError,
    EsphomeOtaError,
    PipelineJob,
    PublishedArtifact,
)
from custom_components.esphome_ota.monitor import InstallationMonitor
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_issue1_unselected_builder_resolution(hass: HomeAssistant) -> None:
    """[P1-1] Test that install without builder keeps unselected state and uses discovered ingress port."""
    # 1. Config flow without candidates
    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "confirm_settings"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_BASE_URL: "https://my-ha.duckdns.org"},
        )
        assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
        # Must not store hardcoded slug "esphome"
        assert CONF_BUILDER_SLUG not in result2["data"]

    # 2. BuilderResolver with no saved selection discovers 5c53de3b_esphome on dynamic ingress port
    cand = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Device Builder",
        host="127.0.0.1",
        port=64285,
        source="addon",
    )
    async with aiohttp.ClientSession() as session:
        resolver = BuilderResolver(hass, session, saved_selection=None)
        with patch.object(resolver.discovery_adapter, "async_discover_all", return_value=[cand]):
            with patch.object(resolver, "_connect_and_probe", return_value=MagicMock()):
                await resolver.async_resolve()
                assert resolver.active_candidate is not None
                assert resolver.active_candidate.slug == "5c53de3b_esphome"
                assert resolver.active_candidate.port == 64285


def test_issue2_frontend_dialog_dom_preservation() -> None:
    """[P1-2] Verify that manager.js initializes DOM skeleton once and preserves dialog instances."""
    from pathlib import Path

    js_path = (
        Path(__file__).parents[3]
        / "custom_components"
        / "esphome_ota"
        / "frontend"
        / "manager.js"
    )
    content = js_path.read_text(encoding="utf-8")

    assert "_initDom()" in content
    assert "this._domInitialized" in content
    assert "_renderDeviceList()" in content
    # job_updated should call updateJob and _renderDeviceList without re-rendering entire shadowRoot
    assert 'event === "job_updated"' in content
    assert "this._renderDeviceList();" in content


async def test_issue3_user_project_version_substitution(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-3] Test that YAML with ${version} substitutions evaluates properly and matches binary."""
    yaml_with_sub = """substitutions:
  version: "2.0.0"
esphome:
  name: livingroom
  project:
    name: "test.proj"
    version: ${version}
esp32:
  board: esp32dev
"""
    assert own_project_version(yaml_with_sub) == "2.0.0"

    # YAML with unresolved substitution (e.g. from external include)
    yaml_unresolved_sub = """esphome:
  name: livingroom
  project:
    name: "test.proj"
    version: ${external_version}
esp32:
  board: esp32dev
"""
    assert own_project_version(yaml_unresolved_sub) == "${external_version}"

    # Verify pipeline accepts binary authoritative version for user-owned projects
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_sub_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        own_project_version="${external_version}",
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
        assert job.binary_version == "1.0.0"  # Authoritative version from mock binary
        await conn.disconnect()


def test_issue4_xss_escaping_in_frontend() -> None:
    """[P1-4] Verify that frontend components escape diffs, device info, and logs."""
    from pathlib import Path

    base = (
        Path(__file__).parents[3]
        / "custom_components"
        / "esphome_ota"
        / "frontend"
    )
    dev_dialog = (base / "device-dialog.js").read_text(encoding="utf-8")
    job_dialog = (base / "job-dialog.js").read_text(encoding="utf-8")
    manager_js = (base / "manager.js").read_text(encoding="utf-8")

    assert "function escapeHtml" in dev_dialog
    assert "escapeHtml(l)" in dev_dialog
    assert "function escapeHtml" in job_dialog
    assert "ansiToHtml" in job_dialog
    assert "export function ansiToHtml(rawText)" in job_dialog
    assert "let safe = escapeHtml(text)" in job_dialog
    assert "ansiToHtml(line)" in job_dialog
    assert "function escapeHtml" in manager_js


async def test_issue5_connection_drop_unblocks_queues_and_resumes(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-5] Test that socket close wakes waiting command queues and async_resume_jobs reconnects tracking."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()

        # Simulate read loop terminating
        if conn._ws:
            await conn._ws.close()
        await asyncio.sleep(0.05)

        # Subsequent command fails with BuilderConnectionError immediately, does not hang
        with pytest.raises(BuilderConnectionError):
            await conn.command("devices/list", timeout=1.0)

        # Test job runner recovery
        storage = StorageManager(hass)
        device_manager = DeviceManager(hass, storage)
        publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_resume_test")
        runner = JobRunner(hass, storage, device_manager, publisher)

        await device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom.yaml",
            name="livingroom",
            friendly_name="Living Room",
        )

        # Reconnect builder
        conn2 = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn2.connect()
        client2 = BuilderClient(conn2)

        # Register mock compile job in server
        mock_builder.jobs["job_abc123"] = {
            "status": "completed",
            "log": ["Compilation succeeded"],
        }

        interrupted_job = PipelineJob(
            job_id="job_interrupted",
            device_id="livingroom",
            configuration="livingroom.yaml",
            request_id="req-prev",
            stage=STAGE_BUILDING,
            builder_job_id="job_abc123",
            reserved_version="1.0.0",
        )
        runner._active_jobs[interrupted_job.job_id] = interrupted_job

        await runner.async_resume_jobs(client2, "https://ha.local")
        task = runner._active_tasks.get("job_interrupted")
        if task:
            await task

        resumed = runner.get_job("job_interrupted")
        assert resumed is not None
        assert resumed.stage == STAGE_PUBLISHED
        await conn2.disconnect()


async def test_issue6_sequential_and_concurrent_build_requests(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2-6] Test that concurrent requests are prevented and sequential builds bump versions correctly."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_seq_test")
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

        job1_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local", request_id="req-1"
        )

        # Concurrent request for same device should be rejected
        with pytest.raises(EsphomeOtaError, match="A build job is already active"):
            await runner.async_start_build_pipeline(
                device=dev, client=client, base_url="https://ha.local", request_id="req-2"
            )

        task1 = runner._active_tasks.get(job1_id)
        if task1:
            await task1

        job1 = runner.get_job(job1_id)
        assert job1 is not None
        assert job1.stage == STAGE_PUBLISHED

        # Update last published version on device to 1.0.1
        dev.last_published_version = "1.0.1"

        # Subsequent build after completion should reserve 1.0.2
        job2_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local", request_id="req-3"
        )
        job2 = runner.get_job(job2_id)
        assert job2 is not None
        assert job2.reserved_version == "1.0.2"

        task2 = runner._active_tasks.get(job2_id)
        if task2:
            await task2
        await conn.disconnect()


async def test_issue7_dynamic_update_entity_tracking(hass: HomeAssistant) -> None:
    """[P2-7] Test that newly created Update entities are dynamically tracked by InstallationMonitor."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_entity_test")
    monitor = InstallationMonitor(hass, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    await monitor.async_setup()
    assert len(monitor._monitored_entities) == 0

    # Simulate newly registered Update entity in Home Assistant entity registry
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="livingroom_firmware_update",
        suggested_object_id="livingroom_firmware",
    )

    # Refresh monitoring
    await monitor.async_refresh_monitoring()
    assert entry.entity_id in monitor._monitored_entities
    monitor.async_unload()


async def test_issue8_auto_cleanup_scheduling_and_restore(hass: HomeAssistant) -> None:
    """[P2-8] Test scheduling cleanup and restoring cleanup timers on startup."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_clean_test")
    monitor = InstallationMonitor(hass, device_manager, publisher, cleanup_hours=2)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    # 1. Schedule cleanup explicitly
    monitor.schedule_cleanup("livingroom", "livingroom_slug")
    assert "livingroom" in monitor._cleanup_timers

    # 2. Simulate startup restore from stored artifacts
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    mock_artifact = PublishedArtifact(
        device_id="livingroom",
        configuration="livingroom.yaml",
        version="1.0.0",
        chip_family="ESP32",
        size=1024,
        md5="abc",
        sha256="def",
        published_at=past_time,
        private_path="/tmp/priv.bin",
        public_bin_path="/tmp/pub.bin",
        public_manifest_path="/tmp/pub.json",
        is_public=True,
    )
    await storage.async_save_artifacts({"livingroom": mock_artifact})

    monitor2 = InstallationMonitor(hass, device_manager, publisher, cleanup_hours=2)
    await monitor2.async_setup()
    assert "livingroom" in monitor2._cleanup_timers
    monitor.async_unload()
    monitor2.async_unload()
