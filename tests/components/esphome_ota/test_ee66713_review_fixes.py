"""Unit and regression tests for ee66713 review fixes:
1. [P1] Correctly detect direct child depth under packages: when packages use 2-space indent with 4-space internal settings.
2. [P2] BuilderClient.get_jobs(configuration=...) supports configuration argument; prior_job_ids snapshot succeeds without TypeError.
3. [P2] Rejection of factory-only images (firmware.factory.bin) and requirement for confirmed OTA binary.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    parse_yaml_safe,
)
from custom_components.esphome_ota.const import (
    FIRMWARE_OTA_BIN,
    STAGE_FAILED,
    STAGE_PUBLISHED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    BuilderError,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager

from .conftest import MockBuilderServer

# ---------------------------------------------------------------------------
# Issue 1: [P1] Direct child package depth detection under packages:
# ---------------------------------------------------------------------------


def test_issue1_two_space_packages_with_four_space_internal_settings() -> None:
    """[P1] Test that 2-space packages with 4-space internal settings are not mistaken for 4-space packages."""
    original_yaml = (
        "esphome:\n"
        "  name: livingroom\n"
        "\n"
        "packages:\n"
        "  wifi: !include wifi.yaml\n"
        "  device_base:\n"
        "    url: https://github.com/example/repo\n"
        "    files: [base.yaml]\n"
        "    refresh: 1d\n"
        "  sensors:\n"
        "    some_key: some_val\n"
    )

    diff = apply_ota_patch(
        yaml_content=original_yaml,
        base_url="http://ha.local:8123",
        slug="livingroom_token123",
        target_version="1.0.0",
        node="livingroom",
    )

    patched = diff.modified

    # 1. esphome_ota must be indented by exactly 2 spaces (matching packages direct children)
    assert re.search(r"^  esphome_ota:\n", patched, re.MULTILINE) is not None
    # Must NOT be indented by 4 spaces
    assert re.search(r"^    esphome_ota:\n", patched, re.MULTILINE) is None

    # 2. Existing packages must remain intact and aligned at 2 spaces
    assert re.search(r"^  wifi: !include wifi.yaml", patched, re.MULTILINE) is not None
    assert re.search(r"^  device_base:", patched, re.MULTILINE) is not None

    # 3. Internal settings at 4 spaces must be preserved
    assert "    url: https://github.com/example/repo" in patched

    # 4. Result must parse into valid YAML with correct structure
    parsed = parse_yaml_safe(patched)
    assert "packages" in parsed
    pkgs = parsed["packages"]
    assert "esphome_ota" in pkgs
    assert "wifi" in pkgs
    assert "device_base" in pkgs
    assert "sensors" in pkgs
    assert pkgs["esphome_ota"]["substitutions"]["ota_slug"] == "livingroom_token123"


def test_issue1_nested_esphome_ota_key_not_confused_with_top_package() -> None:
    """[P1] Test that a subkey named esphome_ota inside another package is not mistaken for the top-level package."""
    original_yaml = (
        "esphome:\n"
        "  name: livingroom\n"
        "\n"
        "packages:\n"
        "  my_pkg:\n"
        "    esphome_ota: false\n"
        "    other_setting: true\n"
    )

    diff = apply_ota_patch(
        yaml_content=original_yaml,
        base_url="http://ha.local:8123",
        slug="livingroom_token123",
        target_version="1.0.0",
        node="livingroom",
    )

    patched = diff.modified
    parsed = parse_yaml_safe(patched)
    assert "packages" in parsed
    pkgs = parsed["packages"]
    # The new managed package esphome_ota is added at depth 1
    assert "esphome_ota" in pkgs
    assert isinstance(pkgs["esphome_ota"], dict)
    # The subkey inside my_pkg is preserved at depth 2
    assert "my_pkg" in pkgs
    assert pkgs["my_pkg"]["esphome_ota"] is False


# ---------------------------------------------------------------------------
# Issue 2: [P2] get_jobs(configuration=...) and prior_job_ids snapshot
# ---------------------------------------------------------------------------


async def test_issue2_get_jobs_with_configuration_and_prior_jobs_snapshot(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test BuilderClient.get_jobs(configuration=...) and snapshot in build pipeline."""
    # Pre-populate jobs in mock builder
    mock_builder.jobs["c_prior_livingroom"] = {
        "status": "completed",
        "configuration": "livingroom.yaml",
        "type": "compile",
        "job_type": "compile",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mock_builder.jobs["c_prior_bedroom"] = {
        "status": "completed",
        "configuration": "bedroom.yaml",
        "type": "compile",
        "job_type": "compile",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. client.get_jobs() without configuration returns all jobs
        all_jobs = await client.get_jobs()
        assert len(all_jobs) == 2

        # 2. client.get_jobs(configuration=...) filters by configuration
        lr_jobs = await client.get_jobs(configuration="livingroom.yaml")
        assert len(lr_jobs) == 1
        assert lr_jobs[0]["job_id"] == "c_prior_livingroom"

        br_jobs = await client.get_jobs(configuration="bedroom.yaml")
        assert len(br_jobs) == 1
        assert br_jobs[0]["job_id"] == "c_prior_bedroom"

        none_jobs = await client.get_jobs(configuration="nonexistent.yaml")
        assert len(none_jobs) == 0

        # 3. Pipeline submission path executes without TypeError and snapshots prior_job_ids
        storage = StorageManager(hass)
        device_manager = DeviceManager(hass, storage)
        publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test_issue2_snap")
        runner = JobRunner(hass, storage, device_manager, publisher)

        await device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom.yaml",
            name="livingroom",
            friendly_name="Living Room",
        )
        device = device_manager.get_device("livingroom")
        assert device is not None

        # Start build pipeline
        job_id = await runner.async_start_build_pipeline(
            device=device,
            client=client,
            base_url="http://ha.local:8123",
        )

        job = runner._active_jobs.get(job_id)
        assert job is not None

        # Wait for compilation to complete
        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        # Checkpoint MUST contain prior_job_ids with c_prior_livingroom!
        assert "prior_job_ids" in job.checkpoint
        assert "c_prior_livingroom" in job.checkpoint["prior_job_ids"]
        # bedroom was for a different configuration, so not in prior_job_ids for livingroom
        assert "c_prior_bedroom" not in job.checkpoint["prior_job_ids"]
        assert job.stage == STAGE_PUBLISHED


# ---------------------------------------------------------------------------
# Issue 3: [P2] Rejection of factory-only images and OTA requirement
# ---------------------------------------------------------------------------


async def test_issue3_rejects_factory_only_images(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test that factory-only binaries are rejected with BuilderError and not selected for OTA."""
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # 1. Builder response only has firmware.factory.bin
        mock_builder.binaries = [
            {"file": "firmware.factory.bin", "size": 1048576}
        ]

        # resolve_ota_binary_file must raise BuilderError, NOT return firmware.factory.bin
        with pytest.raises(BuilderError, match="No OTA binary found"):
            await client.resolve_ota_binary_file("esp32_dev.yaml", platform_hint="esp32")

        # has_ota_binary must return False
        has_ota = await client.has_ota_binary("esp32_dev.yaml", platform_hint="esp32")
        assert has_ota is False

        # download_ota must raise BuilderError
        with pytest.raises(BuilderError, match="No OTA binary found"):
            await client.download_ota("esp32_dev.yaml", platform_hint="esp32")

        # 2. Builder response with explicit type="factory" must also be rejected
        mock_builder.binaries = [
            {"file": "custom_image.bin", "type": "factory", "size": 1048576}
        ]
        with pytest.raises(BuilderError, match="No OTA binary found"):
            await client.resolve_ota_binary_file("esp32_dev.yaml", platform_hint="esp32")

        # 3. When both factory and OTA images are present, OTA image is selected
        mock_builder.binaries = [
            {"file": "firmware.factory.bin", "size": 1048576},
            {"file": FIRMWARE_OTA_BIN, "size": 950000},
        ]
        resolved = await client.resolve_ota_binary_file("esp32_dev.yaml", platform_hint="esp32")
        assert resolved == FIRMWARE_OTA_BIN
        assert await client.has_ota_binary("esp32_dev.yaml", platform_hint="esp32") is True


async def test_issue3_pipeline_fails_when_only_factory_binary_produced(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test that entire pipeline fails when Builder only outputs a factory image."""
    mock_builder.binaries = [
        {"file": "firmware.factory.bin", "size": 1048576}
    ]

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        storage = StorageManager(hass)
        device_manager = DeviceManager(hass, storage)
        publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test_issue3_fail")
        runner = JobRunner(hass, storage, device_manager, publisher)

        await device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom.yaml",
            name="livingroom",
            friendly_name="Living Room",
        )
        device = device_manager.get_device("livingroom")
        assert device is not None

        job_id = await runner.async_start_build_pipeline(
            device=device,
            client=client,
            base_url="http://ha.local:8123",
        )
        job = runner._active_jobs.get(job_id)
        assert job is not None

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        # Pipeline must fail at download stage and NOT publish factory image!
        assert job.stage == STAGE_FAILED
        assert "No OTA binary found" in str(job.error)

        # Nothing should be published
        artifacts = await storage.async_load_artifacts()
        assert "livingroom" not in artifacts
