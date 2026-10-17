"""Unit and regression tests for ffe378c review fixes:
1. [P1] firmware/get_jobs API name and error handling during recovery
2. [P1] Recovery filters out unrelated past/upload jobs and preserves recovery_required on ambiguity
3. [P2] Project ownership: remote package detection and top-level explicit version precedence
4. [P2] Installation monitor rejects non-ESPHome entities and non-ESPHome devices
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    has_unclear_project_ownership,
    own_project_version,
)
from custom_components.esphome_ota.const import (
    STAGE_PUBLISHED,
    STAGE_RECOVERY_REQUIRED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    BuilderError,
    PipelineJob,
)
from custom_components.esphome_ota.monitor import InstallationMonitor
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager

from .conftest import MockBuilderServer


async def test_issue1_get_jobs_api_and_error_preserves_recovery_required(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-1] Test client.get_jobs calls firmware/get_jobs and connection failure preserves recovery_required."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_api_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    interrupted_job = PipelineJob(
        job_id="job_api_rec",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req-api-1",
        stage=STAGE_RECOVERY_REQUIRED,
        reserved_version="1.0.0",
    )
    runner._active_jobs[interrupted_job.job_id] = interrupted_job

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. Verify get_jobs successfully queries firmware/get_jobs
        jobs_res = await client.get_jobs()
        assert isinstance(jobs_res, list)

        # 2. Simulate builder error / command failure during recovery check
        # Instead of falsely marking job as STAGE_FAILED, it must maintain STAGE_RECOVERY_REQUIRED
        client.get_jobs = AsyncMock(
            side_effect=BuilderError("Builder temporarily down")
        )  # type: ignore[method-assign]

        await runner.async_resume_jobs(client, "https://ha.local")

        resumed = runner.get_job("job_api_rec")
        assert resumed is not None
        assert resumed.stage == STAGE_RECOVERY_REQUIRED
        assert resumed.builder_job_id is None

        await conn.disconnect()


async def test_issue2_recovery_rejects_past_upload_job_and_maintains_recovery_required(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1-2] Test recovery rejects past upload jobs, past timestamps, and preserves recovery_required on ambiguity."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_rec_filter_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    now = datetime.now(timezone.utc)
    current_job_created = now.isoformat()

    current_job = PipelineJob(
        job_id="job_curr",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req-curr",
        stage=STAGE_RECOVERY_REQUIRED,
        reserved_version="1.0.0",
        created_at=current_job_created,
    )
    runner._active_jobs[current_job.job_id] = current_job

    # Case A: Builder has a past completed UPLOAD job for livingroom.yaml
    mock_builder.jobs.clear()
    mock_builder.jobs["job_old_upload"] = {
        "status": "completed",
        "configuration": "livingroom.yaml",
        "type": "upload",
        "job_type": "upload",
        "created_at": (now - timedelta(hours=2)).isoformat(),
    }

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Resuming should NOT link the upload job, must maintain recovery_required
        await runner.async_resume_jobs(client, "https://ha.local")

        resumed = runner.get_job("job_curr")
        assert resumed is not None
        assert resumed.stage == STAGE_RECOVERY_REQUIRED
        assert resumed.builder_job_id is None

        # Case B: Builder has a past COMPILE job from 1 day ago
        mock_builder.jobs.clear()
        mock_builder.jobs["job_yesterday_compile"] = {
            "status": "completed",
            "configuration": "livingroom.yaml",
            "type": "compile",
            "job_type": "compile",
            "created_at": (now - timedelta(days=1)).isoformat(),
        }

        await runner.async_resume_jobs(client, "https://ha.local")
        resumed = runner.get_job("job_curr")
        assert resumed is not None
        assert resumed.stage == STAGE_RECOVERY_REQUIRED
        assert resumed.builder_job_id is None

        # Case C: Multiple matching compile jobs (ambiguous) -> maintain recovery_required
        mock_builder.jobs.clear()
        mock_builder.jobs["job_c1"] = {
            "status": "running",
            "configuration": "livingroom.yaml",
            "type": "compile",
            "job_type": "compile",
            "created_at": now.isoformat(),
        }
        mock_builder.jobs["job_c2"] = {
            "status": "queued",
            "configuration": "livingroom.yaml",
            "type": "compile",
            "job_type": "compile",
            "created_at": (now + timedelta(seconds=2)).isoformat(),
        }

        await runner.async_resume_jobs(client, "https://ha.local")
        resumed = runner.get_job("job_curr")
        assert resumed is not None
        assert resumed.stage == STAGE_RECOVERY_REQUIRED
        assert resumed.builder_job_id is None

        # Case D: Exactly one unique matching compile job -> successfully recovered
        mock_builder.jobs.clear()
        mock_builder.jobs["job_unique_valid"] = {
            "status": "completed",
            "configuration": "livingroom.yaml",
            "type": "compile",
            "job_type": "compile",
            "created_at": now.isoformat(),
        }

        await runner.async_resume_jobs(client, "https://ha.local")
        task = runner._active_tasks.get("job_curr")
        if task:
            await task

        resumed = runner.get_job("job_curr")
        assert resumed is not None
        assert resumed.stage == STAGE_PUBLISHED
        assert resumed.builder_job_id == "job_unique_valid"

        await conn.disconnect()


def test_issue3_project_ownership_remote_and_top_level_precedence() -> None:
    """[P2-3] Test remote package unclear ownership and top-level explicit project version precedence."""
    # 1. Top-level explicit project.version: "2.0.0" with legacy !include in packages
    # Top-level takes precedence: ownership is clear (not unclear).
    top_level_override_yaml = (
        "esphome:\n"
        "  name: livingroom\n"
        "  project:\n"
        "    name: acme.climate\n"
        "    version: '2.0.0'\n"
        "packages:\n"
        "  legacy_sensors: !include legacy_sensors.yaml\n"
    )
    assert own_project_version(top_level_override_yaml) == "2.0.0"
    assert has_unclear_project_ownership(top_level_override_yaml) is False

    diff = apply_ota_patch(
        yaml_content=top_level_override_yaml,
        base_url="https://ha.local",
        slug="livingroom",
        target_version="3.0.0",
    )
    # Patch should NOT inject a managed project block because user owns project version
    assert "project:" not in diff.modified.split("packages:")[1]

    # 2. Remote package via github:// shorthand without top-level project version
    github_pkg_yaml = (
        "esphome:\n"
        "  name: shelly_plug\n"
        "packages:\n"
        "  device_base: github://esphome/shelly-configs/plug.yaml@main\n"
    )
    assert own_project_version(github_pkg_yaml) is None
    assert has_unclear_project_ownership(github_pkg_yaml) is True

    # 3. Remote package via dictionary (url / files) without top-level project version
    url_files_pkg_yaml = (
        "esphome:\n"
        "  name: m5stack_core\n"
        "packages:\n"
        "  remote_m5:\n"
        "    url: https://github.com/m5stack/esphome-configs\n"
        "    files: [core.yaml]\n"
    )
    assert own_project_version(url_files_pkg_yaml) is None
    assert has_unclear_project_ownership(url_files_pkg_yaml) is True

    # When user does not own project version, apply_ota_patch injects managed project
    # inside packages.esphome_ota rather than altering top-level esphome.
    diff_github = apply_ota_patch(
        github_pkg_yaml, "https://ha.local", "shelly_plug", "1.0.0"
    )
    assert "project:" in diff_github.modified
    assert 'name: "local.shelly_plug"' in diff_github.modified
    assert 'version: "1.0.0"' in diff_github.modified
    # Once patched with managed packages.esphome_ota, ownership is clarified
    assert has_unclear_project_ownership(diff_github.modified) is False

    diff_url = apply_ota_patch(
        url_files_pkg_yaml, "https://ha.local", "m5stack_core", "1.0.0"
    )
    assert "project:" in diff_url.modified
    assert 'name: "local.m5stack_core"' in diff_url.modified
    assert 'version: "1.0.0"' in diff_url.modified
    assert has_unclear_project_ownership(diff_url.modified) is False


async def test_issue4_monitor_rejects_non_esphome_entities_and_devices(
    hass: HomeAssistant,
) -> None:
    """[P2-4] Test installation monitor rejects MQTT or other non-ESPHome entities/devices."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_mon_platform_test")
    monitor = InstallationMonitor(hass, device_manager, publisher)

    # Managed ESPHome device: "room"
    await device_manager.async_register_or_update(
        device_id="room",
        configuration="room.yaml",
        name="room",
        friendly_name="Room",
    )

    await monitor.async_setup()
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    # 1. Create an MQTT config entry, device, and MQTT update entity with matching name "room_firmware"
    mqtt_entry = MockConfigEntry(domain="mqtt", entry_id="mqtt_mock_entry")
    mqtt_entry.add_to_hass(hass)
    mqtt_dev = dev_reg.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "room_dev_1")},
        name="Room",
    )
    mqtt_entity = ent_reg.async_get_or_create(
        domain="update",
        platform="mqtt",
        unique_id="mqtt_room_firmware",
        suggested_object_id="room_firmware",
        device_id=mqtt_dev.id,
    )

    # Refresh monitoring: MQTT entity MUST NOT be linked
    await monitor.async_refresh_monitoring()
    assert mqtt_entity.entity_id not in monitor._monitored_entities

    # 2. Now create a legitimate ESPHome device and ESPHome update entity
    esphome_entry = MockConfigEntry(domain="esphome", entry_id="esphome_mock_entry")
    esphome_entry.add_to_hass(hass)
    esphome_dev = dev_reg.async_get_or_create(
        config_entry_id=esphome_entry.entry_id,
        identifiers={("esphome", "room")},
        name="Room",
    )
    esphome_entity = ent_reg.async_get_or_create(
        domain="update",
        platform="esphome",
        unique_id="esphome_room_firmware",
        suggested_object_id="room_firmware_ota",
        device_id=esphome_dev.id,
    )

    await monitor.async_refresh_monitoring()
    # The ESPHome entity MUST be monitored, while the MQTT entity is still excluded
    assert esphome_entity.entity_id in monitor._monitored_entities
    assert mqtt_entity.entity_id not in monitor._monitored_entities

    monitor.async_unload()
