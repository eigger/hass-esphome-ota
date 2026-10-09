"""Unit and regression tests for ae5c1bb review fixes.

Issues covered:
1. [P1] Rejection of non-firmware binaries (0-filled, corrupt, or invalid image headers)
2. [P2] Pipeline tracking abort on integration unload without remote builder cancellation
3. [P2] Preserving project version ownership while updating/injecting OTA packages in YAML
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import FormData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    STAGE_CANCELLED,
    STAGE_PUBLISHED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import (
    BinaryValidationError,
    chip_family,
    inspect_binary,
)
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

# ---------------------------------------------------------------------------
# Issue 1: Rejection of non-firmware files
# ---------------------------------------------------------------------------

def test_issue1_rejects_zero_filled_binary() -> None:
    """[P1] Verify that a 2KB file of zeros is rejected for ESP32 and ESP8266."""
    zero_blob = b"\x00" * 2048

    # ESP32 target with expected chip and reserved version
    with pytest.raises(BinaryValidationError, match="Invalid firmware binary structure"):
        inspect_binary(
            blob=zero_blob,
            target_platform="esp32",
            expected_chip="ESP32",
            reserved_version="1.0.1",
        )

    # ESP8266 target
    with pytest.raises(BinaryValidationError, match="Invalid firmware binary structure"):
        inspect_binary(
            blob=zero_blob,
            target_platform="esp8266",
            expected_chip="ESP8266",
            reserved_version="1.0.1",
        )

    # Text file > 1KB
    text_blob = b"Hello world! This is not a binary image." * 40
    with pytest.raises(BinaryValidationError, match="Invalid firmware binary structure"):
        inspect_binary(
            blob=text_blob,
            target_platform="esp32",
            expected_chip="ESP32",
        )


def test_issue1_chip_family_returns_invalid_for_headerless_blobs() -> None:
    """[P1] Verify chip_family returns (None, 'invalid') when blob has no valid header."""
    zero_blob = b"\x00" * 2048
    chip, source = chip_family("esp32", zero_blob)
    assert chip is None
    assert source == "invalid"

    chip_8266, source_8266 = chip_family("esp8266", zero_blob)
    assert chip_8266 is None
    assert source_8266 == "invalid"


async def test_issue1_manual_upload_rejects_zero_filled_file(
    hass: HomeAssistant,
    hass_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """[P1] Verify that HTTP multipart upload rejects 2KB zero-filled file with HTTP 422."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        client = await hass_client()
        form = FormData()
        form.add_field(
            "file",
            b"\x00" * 2048,
            filename="firmware.ota.bin",
            content_type="application/octet-stream",
        )

        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 422
        data = await resp.json()
        assert "error" in data
        assert "Invalid firmware binary structure" in data["error"]


# ---------------------------------------------------------------------------
# Issue 2: Integration unload cleans up active tracking without remote builder cancellation
# ---------------------------------------------------------------------------

async def test_issue2_unload_stops_pipeline_without_cancelling_builder(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] Verify manager.async_unload() aborts local pipeline tasks without cancelling builder compile."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_unload_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        target_platform="esp32",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Spy on client.cancel_job
        client.cancel_job = AsyncMock(wraps=client.cancel_job)

        # Make wait_for_compile_completion hang briefly so we can unload during compile
        compile_started = asyncio.Event()

        async def _slow_wait(*args: Any, **kwargs: Any) -> None:
            compile_started.set()
            await asyncio.sleep(10)

        with patch.object(client, "wait_for_compile_completion", side_effect=_slow_wait):
            job_id = await runner.async_start_build_pipeline(
                device=dev,
                client=client,
                base_url="https://ha.local",
            )
            # Wait until compile starts
            await asyncio.wait_for(compile_started.wait(), timeout=2.0)

            # Now simulate unload of runner
            await runner.async_unload()

            # Verify that runner tasks are empty
            assert len(runner._active_tasks) == 0

            # Verify that client.cancel_job was NOT called!
            client.cancel_job.assert_not_called()

            # Verify that job was not published or marked failed
            job = runner.get_job(job_id)
            assert job is not None
            assert job.stage != STAGE_PUBLISHED

        await conn.disconnect()


async def test_issue2_manual_cancel_does_cancel_builder_job(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] Verify manual user cancellation DOES cancel builder compile job."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_cancel_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        target_platform="esp32",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        client.cancel_job = AsyncMock(wraps=client.cancel_job)
        compile_started = asyncio.Event()

        async def _slow_wait(*args: Any, **kwargs: Any) -> None:
            compile_started.set()
            await asyncio.sleep(10)

        with patch.object(client, "wait_for_compile_completion", side_effect=_slow_wait):
            job_id = await runner.async_start_build_pipeline(
                device=dev,
                client=client,
                base_url="https://ha.local",
            )
            await asyncio.wait_for(compile_started.wait(), timeout=2.0)

            # Manual user cancellation
            await runner.async_cancel_job(job_id, client=client)

            # Builder cancel MUST be called
            client.cancel_job.assert_called_once()
            job = runner.get_job(job_id)
            assert job is not None
            assert job.stage == STAGE_CANCELLED

        await conn.disconnect()


# ---------------------------------------------------------------------------
# Issue 3: Separating version ownership and OTA patch updating
# ---------------------------------------------------------------------------

async def test_issue3_own_project_version_preserves_version_and_updates_ota_config(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] Verify YAML with own project version gets packages.esphome_ota injected without altering version."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_own_ver_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    # bedroom.yaml in mock_builder has:
    # esphome:
    #   name: bedroom
    #   project:
    #     name: my.bedroom
    #     version: '2.1.0'
    # esp32:
    #   board: esp32dev
    dev = await device_manager.async_register_or_update(
        device_id="bedroom",
        configuration="bedroom.yaml",
        name="bedroom",
        friendly_name="Bedroom",
        target_platform="esp32",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Before build, bedroom.yaml has NO packages.esphome_ota
        cfg_before = await client.get_config("bedroom.yaml")
        assert "packages:" not in cfg_before
        assert "version: '2.1.0'" in cfg_before

        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://my-ha.duckdns.org",
        )
        task = runner._active_tasks.get(job_id)
        if task:
            await task

        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_PUBLISHED

        # After build, bedroom.yaml MUST have packages.esphome_ota and ota_base_url
        cfg_after = await client.get_config("bedroom.yaml")
        assert "packages:" in cfg_after
        assert "esphome_ota:" in cfg_after
        assert 'ota_base_url: "https://my-ha.duckdns.org"' in cfg_after

        # BUT user's project version '2.1.0' MUST be preserved (NOT overwritten)
        assert "version: '2.1.0'" in cfg_after
        assert dev.own_project_version is not None

        # Now test changing base_url: OTA config must update to new URL
        job_id_2 = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://new-ha.example.com",
        )
        task_2 = runner._active_tasks.get(job_id_2)
        if task_2:
            await task_2

        cfg_after_2 = await client.get_config("bedroom.yaml")
        assert 'ota_base_url: "https://new-ha.example.com"' in cfg_after_2
        assert "version: '2.1.0'" in cfg_after_2

        await conn.disconnect()
