"""Unit and regression tests for e2369ce review fixes:
1. [P1] Recovery rejects compile jobs submitted prior to request (e.g. 5s before) or in prior_job_ids, maintaining recovery_required.
2. [P2] recovery_required job can be cancelled via async_cancel_job, unblocking device builds; job-dialog provides recheck & cancel actions.
3. [P2] ESP8266 binary resolution selects firmware.bin instead of firmware.ota.bin.
4. [P2] 4-space indented existing packages.esphome_ota YAML is replaced cleanly in-place without nesting or corruption.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    parse_yaml_safe,
    reindent_yaml_snippet,
)
from custom_components.esphome_ota.const import (
    FIRMWARE_BIN,
    FIRMWARE_OTA_BIN,
    STAGE_CANCELLED,
    STAGE_PUBLISHED,
    STAGE_RECOVERY_REQUIRED,
    STAGE_SUBMITTING,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import EsphomeOtaError, PipelineJob
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager

from .conftest import MockBuilderServer

# ---------------------------------------------------------------------------
# Issue 1: [P1] Recovery rejects compile finished prior to new request
# ---------------------------------------------------------------------------


async def test_issue1_recovery_rejects_compile_finished_5s_before_request(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1] Test that compile completed 5 seconds before request is NOT linked, maintaining recovery_required."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test_issue1")
    runner = JobRunner(hass, storage, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    device = device_manager.get_device("livingroom")
    assert device is not None

    req_time = datetime.now(timezone.utc)
    old_compile_time = req_time - timedelta(seconds=5)

    # Past compile in builder server submitted 5s before new request
    past_builder_job_id = "c_past_12345"
    mock_builder.jobs[past_builder_job_id] = {
        "status": "completed",
        "configuration": "livingroom.yaml",
        "type": "compile",
        "job_type": "compile",
        "created_at": old_compile_time.isoformat(),
    }

    # Pipeline job created at req_time with checkpoint
    interrupted_job = PipelineJob(
        job_id="job_req_new",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req_new_123",
        reserved_version="1.0.1",
        stage=STAGE_SUBMITTING,
        created_at=req_time.isoformat(),
        checkpoint={
            "submitted_at": req_time.isoformat(),
            "prior_job_ids": [past_builder_job_id],
        },
    )
    runner._active_jobs[interrupted_job.job_id] = interrupted_job

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Resume jobs
        await runner.async_resume_jobs(client, base_url="http://ha.local:8123")

        # The past job must NOT be linked! Stage must be transitioned to recovery_required
        assert interrupted_job.builder_job_id is None
        assert interrupted_job.stage == STAGE_RECOVERY_REQUIRED
        assert "job_req_new" not in runner._active_tasks


async def test_issue1_recovery_links_compile_submitted_after_request(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P1] Test that compile submitted after request timestamp IS linked and resumed."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test_issue1_valid")
    runner = JobRunner(hass, storage, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    device = device_manager.get_device("livingroom")
    assert device is not None

    req_time = datetime.now(timezone.utc)
    new_compile_time = req_time + timedelta(seconds=1)

    # Valid compile submitted right after request
    valid_builder_job_id = "c_new_valid_6789"
    mock_builder.jobs[valid_builder_job_id] = {
        "status": "completed",
        "configuration": "livingroom.yaml",
        "type": "compile",
        "job_type": "compile",
        "created_at": new_compile_time.isoformat(),
    }

    interrupted_job = PipelineJob(
        job_id="job_req_valid",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req_valid_456",
        reserved_version="1.0.0",
        stage=STAGE_SUBMITTING,
        created_at=req_time.isoformat(),
        checkpoint={
            "submitted_at": req_time.isoformat(),
            "prior_job_ids": [],
        },
    )
    runner._active_jobs[interrupted_job.job_id] = interrupted_job

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        await runner.async_resume_jobs(client, base_url="http://ha.local:8123")

        # The new compile is linked and pipeline resumes
        assert interrupted_job.builder_job_id == valid_builder_job_id
        task = runner._active_tasks.get("job_req_valid")
        assert task is not None
        await task
        assert interrupted_job.stage == STAGE_PUBLISHED


# ---------------------------------------------------------------------------
# Issue 2: [P2] recovery_required state cancellation unblocks new builds
# ---------------------------------------------------------------------------


async def test_issue2_cancel_recovery_required_job_unblocks_build(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test that cancelling a recovery_required job unblocks new build attempts."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test_issue2")
    runner = JobRunner(hass, storage, device_manager, publisher)

    await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )
    device = device_manager.get_device("livingroom")
    assert device is not None

    stuck_job = PipelineJob(
        job_id="job_stuck_recovery",
        device_id="livingroom",
        configuration="livingroom.yaml",
        request_id="req_stuck_789",
        reserved_version="1.0.1",
        stage=STAGE_RECOVERY_REQUIRED,
    )
    runner._active_jobs[stuck_job.job_id] = stuck_job

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # While in recovery_required, a new build is blocked
        with pytest.raises(EsphomeOtaError, match="A build job is already active"):
            await runner.async_start_build_pipeline(
                device, client, "http://ha.local:8123"
            )

        # Cancel the stuck job (as triggered by UI Cancel button)
        await runner.async_cancel_job(stuck_job.job_id, client=client)
        assert stuck_job.stage == STAGE_CANCELLED

        # Now starting a new build succeeds and returns a new job_id!
        new_job_id = await runner.async_start_build_pipeline(
            device, client, "http://ha.local:8123"
        )
        assert new_job_id != stuck_job.job_id
        assert new_job_id.startswith("job_")

        # Clean up active task
        task = runner._active_tasks.get(new_job_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# Issue 3: [P2] ESP8266 download filename resolution
# ---------------------------------------------------------------------------


async def test_issue3_esp8266_selects_firmware_bin(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test that resolve_ota_binary_file selects firmware.bin for ESP8266 devices."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. Builder provides only firmware.bin (as ESPHome ESP8266 produces)
        mock_builder.binaries = [{"file": FIRMWARE_BIN, "size": 524288}]

        resolved = await client.resolve_ota_binary_file(
            configuration="esp8266_dev.yaml",
            platform_hint="esp8266",
        )
        assert resolved == FIRMWARE_BIN

        # 2. Downloading requests token for firmware.bin
        blob = await client.download_ota(
            configuration="esp8266_dev.yaml",
            platform_hint="esp8266",
        )
        assert len(blob) > 0
        assert mock_builder.last_download_token_args == {
            "configuration": "esp8266_dev.yaml",
            "file": FIRMWARE_BIN,
        }

        # 3. For ESP32 with firmware.ota.bin, it selects firmware.ota.bin
        mock_builder.binaries = [
            {"file": "firmware.factory.bin", "size": 1048576},
            {"file": FIRMWARE_OTA_BIN, "size": 948576},
        ]
        resolved_esp32 = await client.resolve_ota_binary_file(
            configuration="esp32_dev.yaml",
            platform_hint="esp32",
        )
        assert resolved_esp32 == FIRMWARE_OTA_BIN

        # 4. If explicit type="ota" is provided, it is selected regardless of platform
        mock_builder.binaries = [
            {"file": "custom_ota.bin", "type": "ota", "size": 400000},
            {"file": FIRMWARE_BIN, "size": 400000},
        ]
        resolved_custom = await client.resolve_ota_binary_file(
            configuration="custom.yaml",
            platform_hint="esp8266",
        )
        assert resolved_custom == "custom_ota.bin"


# ---------------------------------------------------------------------------
# Issue 4: [P2] 4-space indented existing packages.esphome_ota replacement
# ---------------------------------------------------------------------------


def test_issue4_4_space_indented_packages_replaced_cleanly() -> None:
    """[P2] Test that 4-space indented existing esphome_ota block is replaced in-place without nesting."""
    original_yaml = (
        "esphome:\n"
        "    name: bedroom\n"
        "packages:\n"
        "    other_pkg: !include other.yaml\n"
        "    esphome_ota:\n"
        "        substitutions:\n"
        '            ota_base_url: "http://old-ha.local:8123"\n'
        '            ota_slug: "old_slug_1234"\n'
        "        http_request:\n"
        "            timeout: 30s\n"
        "    my_custom_sensor:\n"
        "        sensor:\n"
        "            platform: uptime\n"
    )

    diff = apply_ota_patch(
        yaml_content=original_yaml,
        base_url="http://new-ha.local:8123",
        slug="bedroom_token123",
        target_version="2.0.0",
        node="bedroom",
    )

    patched = diff.modified

    # 1. Must NOT nest esphome_ota inside another esphome_ota
    assert patched.count("esphome_ota:") == 1

    # 2. Indentation of esphome_ota key must be exactly 4 spaces
    assert "    esphome_ota:\n" in patched
    assert not any(
        re.match(r"^ {2}esphome_ota:", line) for line in patched.splitlines()
    )

    # 3. Old substitutions must be replaced with new base_url and slug
    assert "http://new-ha.local:8123" in patched
    assert "old-ha.local" not in patched
    assert "bedroom_token123" in patched

    # 4. Sibling packages must remain intact and with correct indentation
    assert "    other_pkg: !include other.yaml\n" in patched
    assert "    my_custom_sensor:\n" in patched
    assert "            platform: uptime\n" in patched

    # 5. Must parse validly
    parsed = parse_yaml_safe(patched)
    assert "packages" in parsed
    assert "esphome_ota" in parsed["packages"]
    assert "other_pkg" in parsed["packages"]
    assert "my_custom_sensor" in parsed["packages"]
    assert (
        parsed["packages"]["esphome_ota"]["substitutions"]["ota_slug"]
        == "bedroom_token123"
    )


def test_issue4_reindent_yaml_snippet_helper() -> None:
    """[P2] Test reindent_yaml_snippet helper scales 2-space YAML snippet to 4-space."""
    snippet_2sp = (
        "  esphome_ota:\n"
        "    substitutions:\n"
        '      ota_slug: "abc"\n'
        "    update:\n"
        "      - platform: http_request\n"
        '        id: "test"\n'
    )
    snippet_4sp = reindent_yaml_snippet(snippet_2sp, indent_size=4)
    assert snippet_4sp.startswith("    esphome_ota:\n")
    assert "        substitutions:\n" in snippet_4sp
    assert '            ota_slug: "abc"\n' in snippet_4sp
