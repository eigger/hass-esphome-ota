"""Tests verifying parity with legacy hassio-apps/esphome_ota addon.

Specifically verifies:
1. bump_patch_version matches legacy bump_version behavior (v260901 rev.1 -> rev.2, dates, semver).
2. Authoritative binary version is published even when different from reserved version (no crash).
3. Automatic managed_version advance after successful publish (advance_registered_version).
4. Build log sanitization strips ANSI escape sequences, literal 033, and tofu characters.
"""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import bump_patch_version
from custom_components.esphome_ota.const import STAGE_PUBLISHED
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner, _clean_log_line
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


def test_legacy_bump_version_parity() -> None:
    """Verify bump_patch_version parity with legacy addon bump_version."""
    # Revision strings like user's v260901 rev.1
    assert bump_patch_version("v260901 rev.1") == "v260901 rev.2"
    assert bump_patch_version("v260819 rev.4") == "v260819 rev.5"

    # Date-based versions
    assert bump_patch_version("2026-08-19") == "2026-08-19.1"
    assert bump_patch_version("2026-08-19.1") == "2026-08-19.2"
    assert bump_patch_version("2026.07.04") == "2026.07.04.1"
    assert bump_patch_version("20260819") == "20260819.1"
    assert bump_patch_version("20260819.3") == "20260819.4"

    # Standard semver
    assert bump_patch_version("1.0.0") == "1.0.1"
    assert bump_patch_version("1.0.9") == "1.0.10"
    assert bump_patch_version("2.1") == "2.1.1"
    assert bump_patch_version("3") == "3.0.1"
    assert bump_patch_version("") == "1.0.0"


def test_clean_log_line() -> None:
    """Verify log sanitization removes ANSI sequences, literal 033, and tofu characters."""
    # Typical ESPHome compile output with ANSI colors
    raw1 = "\033[32mINFO Successfully compiled program.\033[0m"
    assert _clean_log_line(raw1) == "INFO Successfully compiled program."

    # Literal backslash-033 string
    raw2 = r"\033[32mINFO Created: /data/build/firmware.factory.bin\033[0m"
    assert _clean_log_line(raw2) == "INFO Created: /data/build/firmware.factory.bin"

    # CSI erase in line (\x1b[K) and bold (\x1b[01m)
    raw3 = "[1865/1956] Building CXX object\x1b[K\n"
    assert _clean_log_line(raw3) == "[1865/1956] Building CXX object"

    # Tofu character replacement (\ufffd)
    raw4 = "\ufffd[01m\ufffd[K../src/components/ledc.cpp"
    assert _clean_log_line(raw4) == "[01m[K../src/components/ledc.cpp"


async def test_job_runner_publishes_authoritative_binary_version_and_advances(
    hass: HomeAssistant,
    mock_builder: MockBuilderServer,
) -> None:
    """Verify that when compiled binary reports a version different from reserved version,

    the pipeline does not crash with BinaryValidationError, publishes the binary version,
    and advances managed_version for the next build.
    """
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_parity_test")
    runner = JobRunner(hass, storage, device_manager, publisher)

    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
        managed_version="1.0.0",
    )

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)

        # Start build with target_version '9.9.9', but mock binary will report '1.0.0'
        job_id = await runner.async_start_build_pipeline(
            device=dev,
            client=client,
            base_url="https://my-ha.duckdns.org",
            target_version="9.9.9",
        )

        task = runner._active_tasks.get(job_id)
        assert task is not None
        await task

        job = runner.get_job(job_id)
        assert job is not None
        # Pipeline must succeed (published), NOT failed!
        assert job.stage == STAGE_PUBLISHED
        assert job.error is None
        # Published version must be the binary's authoritative version
        assert job.binary_version == "1.0.0"

        # Device record should have last_published_version = 1.0.0,
        # and managed_version advanced to 1.0.1!
        updated_dev = device_manager.get_device("livingroom")
        assert updated_dev is not None
        assert updated_dev.last_published_version == "1.0.0"
        assert updated_dev.managed_version == "1.0.1"
