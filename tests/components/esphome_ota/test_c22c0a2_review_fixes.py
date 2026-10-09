"""Unit and regression tests for c22c0a2 review fixes.

Issues covered:
1. [P1] Cancelling new build deletes existing normal firmware (jobs.py:425, publisher.py)
   - Do not call async_deactivate(device.slug) on job cancellation or unload.
   - Stage files during publishing and ensure prior existing public files are never unlinked.
   - Cancellation during compile, validation, or publish leaves existing valid firmware files intact.
2. [P2] Options Auto-detect prevents automatic connection (manager.py:60, config_flow.py)
   - Options storing "auto" is normalized to None (unselected state).
   - Single builder candidate is automatically selected and connected.
3. [P2] Builder selection changed in panel reverts upon reload (manager.py:317)
   - async_select_builder updates both entry data and options.
   - Unified storage location and read priority ensures selection is preserved after reload.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_NAME,
    CONF_BUILDER_SLUG,
    DOMAIN,
    STAGE_CANCELLED,
    STATUS_READY,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.manager import OtaManager
from custom_components.esphome_ota.models import BuilderCandidate, EsphomeOtaError
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_esp32_bin(version: str = "1.0.0") -> bytes:
    """Create a minimal valid ESP32 binary with esp_app_desc_t."""
    blob = bytearray(b"\x00" * 2048)
    blob[0:4] = b"\xe9\x04\x02\x10"
    blob[20:22] = b"\x00\x00"
    offset = 0x20
    blob[offset : offset + 4] = b"\x32\x54\xcd\xab"
    ver_bytes = version.encode("ascii")
    blob[offset + 16 : offset + 16 + len(ver_bytes)] = ver_bytes
    return bytes(blob)


# ---------------------------------------------------------------------------
# Tests for Issue 1: Cancelling build preserves existing normal firmware
# ---------------------------------------------------------------------------


async def test_cancelling_build_preserves_existing_firmware_files(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test that cancelling a new build retains the existing valid public firmware."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_cancel_test")

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
    )

    # 1. Publish initial v1 firmware
    old_blob = _make_valid_esp32_bin("1.0.0")
    old_info = inspect_binary(old_blob, target_platform="esp32", reserved_version="1.0.0")
    artifact = await publisher.async_publish(
        device_id=dev.device_id,
        configuration=dev.configuration,
        slug=dev.slug,
        blob=old_blob,
        info=old_info,
        title="Living Room Initial",
    )

    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    assert pub_bin.is_file()
    assert pub_bin.read_bytes() == old_blob
    assert pub_md5.is_file()
    assert pub_manifest.is_file()

    # 2. Start a new build pipeline
    runner = JobRunner(hass, storage, device_manager, publisher)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local"
        )

        # 3. Cancel the job while in progress
        await runner.async_cancel_job(job_id, client)
        job = runner.get_job(job_id)
        assert job is not None
        assert job.stage == STAGE_CANCELLED

        await conn.disconnect()

    # 4. Existing firmware files MUST still exist and match the old binary!
    assert pub_bin.is_file(), "Existing firmware binary must NOT be deleted on cancel"
    assert pub_bin.read_bytes() == old_blob
    assert pub_md5.is_file(), "Existing firmware MD5 must NOT be deleted on cancel"
    assert pub_manifest.is_file(), "Existing firmware manifest must NOT be deleted on cancel"


async def test_job_runner_unload_preserves_existing_firmware(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test that unloading JobRunner while a task runs does NOT delete existing firmware."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_unload_test")

    dev = await device_manager.async_register_or_update(
        device_id="bedroom",
        configuration="bedroom.yaml",
        name="bedroom",
        friendly_name="Bedroom",
    )

    old_blob = _make_valid_esp32_bin("1.0.0")
    old_info = inspect_binary(old_blob, target_platform="esp32", reserved_version="1.0.0")
    artifact = await publisher.async_publish(
        device_id=dev.device_id,
        configuration=dev.configuration,
        slug=dev.slug,
        blob=old_blob,
        info=old_info,
        title="Bedroom Initial",
    )

    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    runner = JobRunner(hass, storage, device_manager, publisher)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.local"
        )
        assert job_id.startswith("job_")

        # Unload integration while pipeline is running
        await runner.async_unload()

        await conn.disconnect()

    # Existing files must still be preserved
    assert pub_bin.is_file()
    assert pub_bin.read_bytes() == old_blob
    assert pub_md5.is_file()
    assert pub_manifest.is_file()


async def test_publisher_abort_during_publish_preserves_prior_files(
    hass: HomeAssistant,
) -> None:
    """Test that if publishing is aborted, prior files are untouched and staging files removed."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_abort_test")

    old_blob = _make_valid_esp32_bin("1.0.0")
    old_info = inspect_binary(old_blob, target_platform="esp32", reserved_version="1.0.0")
    artifact = await publisher.async_publish(
        device_id="dev1",
        configuration="dev1.yaml",
        slug="dev1_slug",
        blob=old_blob,
        info=old_info,
    )

    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    new_blob = _make_valid_esp32_bin("2.0.0")
    new_info = inspect_binary(new_blob, target_platform="esp32", reserved_version="2.0.0")

    # Try publishing new version but abort via check_cancelled
    with pytest.raises(EsphomeOtaError, match="Publish aborted"):
        await publisher.async_publish(
            device_id="dev1",
            configuration="dev1.yaml",
            slug="dev1_slug",
            blob=new_blob,
            info=new_info,
            check_cancelled=lambda: True,
        )

    # Prior files must be untouched
    assert pub_bin.is_file()
    assert pub_bin.read_bytes() == old_blob
    assert pub_md5.is_file()
    assert pub_manifest.is_file()

    # No stray staging files left in directory
    staging_files = list(publisher.www_dir.glob("*stage*"))
    assert len(staging_files) == 0


# ---------------------------------------------------------------------------
# Tests for Issue 2: Options Auto-detect normalizes and allows auto-connection
# ---------------------------------------------------------------------------


async def test_auto_detect_option_normalizes_to_none_and_connects(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test that 'auto' stored in options normalizes to unselected and connects to single builder."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ESPHome OTA",
        data={CONF_BASE_URL: "http://127.0.0.1:8123"},
        options={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_AUTO_CLEANUP_HOURS: 24,
            CONF_BUILDER_SLUG: "auto",
        },
    )
    entry.add_to_hass(hass)

    manager = OtaManager(hass, entry)
    # Verify saved_selection is normalized to None rather than BuilderSelection(slug='auto')
    assert manager.resolver.saved_selection is None

    # Mock single discovered builder candidate
    single_cand = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Builder",
        host="127.0.0.1",
        port=mock_builder.port,
        source="ingress",
        is_running=True,
    )

    with patch.object(
        manager.resolver.discovery_adapter,
        "async_discover_all",
        return_value=[single_cand],
    ):
        await manager.async_setup()
        assert manager.resolver.status == STATUS_READY
        assert manager.resolver.active_candidate is not None
        assert manager.resolver.active_candidate.slug == "5c53de3b_esphome"

    await manager.async_unload()


async def test_options_flow_auto_selection_clears_builder_slug(
    hass: HomeAssistant,
) -> None:
    """Test that selecting 'auto' in options flow removes CONF_BUILDER_SLUG from entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ESPHome OTA",
        data={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_BUILDER_SLUG: "old_builder",
            CONF_BUILDER_NAME: "Old Builder",
        },
        options={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_BUILDER_SLUG: "old_builder",
            CONF_BUILDER_NAME: "Old Builder",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is data_entry_flow.FlowResultType.FORM

    # Submit "auto"
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_AUTO_CLEANUP_HOURS: 12,
            CONF_BUILDER_SLUG: "auto",
        },
    )
    assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY

    # Verify CONF_BUILDER_SLUG is removed/not set to literal 'auto' in both data and options
    assert CONF_BUILDER_SLUG not in entry.data
    assert CONF_BUILDER_SLUG not in entry.options


# ---------------------------------------------------------------------------
# Tests for Issue 3: Panel builder selection persists across entry reload
# ---------------------------------------------------------------------------


async def test_panel_builder_selection_persists_across_entry_reload(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test that selection changed in panel updates options and data so it persists across reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ESPHome OTA",
        data={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_BUILDER_SLUG: "builder_a",
            CONF_BUILDER_NAME: "Builder A",
        },
        options={
            CONF_BASE_URL: "http://127.0.0.1:8123",
            CONF_BUILDER_SLUG: "builder_a",
            CONF_BUILDER_NAME: "Builder A",
        },
    )
    entry.add_to_hass(hass)

    cand_a = BuilderCandidate(
        slug="builder_a",
        name="Builder A",
        host="127.0.0.1",
        port=mock_builder.port,
        source="ingress",
        is_running=True,
    )
    cand_b = BuilderCandidate(
        slug="builder_b",
        name="Builder B",
        host="127.0.0.1",
        port=mock_builder.port,
        source="ingress",
        is_running=True,
    )

    manager = OtaManager(hass, entry)
    manager.resolver.candidates = [cand_a, cand_b]

    with patch.object(
        manager.resolver.discovery_adapter,
        "async_discover_all",
        return_value=[cand_a, cand_b],
    ):
        await manager.async_setup()

        # Change builder selection to builder_b via panel method
        await manager.async_select_builder("builder_b")

        # Verify entry.data AND entry.options are both updated
        assert entry.data[CONF_BUILDER_SLUG] == "builder_b"
        assert entry.options[CONF_BUILDER_SLUG] == "builder_b"

        # Simulate integration reload by constructing a new manager with the same config entry
        await manager.async_unload()

        reloaded_manager = OtaManager(hass, entry)
        assert reloaded_manager.resolver.saved_selection is not None
        assert reloaded_manager.resolver.saved_selection.slug == "builder_b"

        reloaded_manager.resolver.candidates = [cand_a, cand_b]
        with patch.object(
            reloaded_manager.resolver.discovery_adapter,
            "async_discover_all",
            return_value=[cand_a, cand_b],
        ):
            await reloaded_manager.async_setup()
            assert reloaded_manager.resolver.status == STATUS_READY
            assert reloaded_manager.resolver.active_candidate is not None
            assert reloaded_manager.resolver.active_candidate.slug == "builder_b"

        await reloaded_manager.async_unload()
