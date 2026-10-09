"""Regression tests for issues reported in commit 2070a00 review.

Issues covered:
1. [P1] publisher.py: Cancelled publish executor thread completes rollback before
   subsequent publish proceeds; does not overwrite subsequent successful publish
   with old backup.
2. [P2] manager.py: Selecting the same Builder restores reload suppression counter
   when async_update_entry returns False (no change), ensuring subsequent options
   updates still trigger the necessary reload.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import (
    CONF_BASE_URL,
    CONF_BUILDER_SLUG,
    DOMAIN,
)
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.manager import OtaManager
from custom_components.esphome_ota.models import BuilderCandidate
from custom_components.esphome_ota.publisher import ArtifactPublisher

from .conftest import MockBuilderServer


def _make_valid_esp32_bin(version: str) -> bytes:
    """Create a minimal binary valid for ESP32 inspection."""
    header = b"\xe9\x00\x00\x00" + b"\x00" * 8 + b"\x00\x00" + b"\x00" * 18
    app_desc_magic = b"\x32\x54\xcd\xab"
    secure_ver = b"\x00" * 4
    reserved1 = b"\x00" * 8
    ver_bytes = version.encode("ascii").ljust(32, b"\x00")[:32]
    proj_bytes = b"livingroom".ljust(32, b"\x00")
    time_bytes = b"12:00:00".ljust(16, b"\x00")
    date_bytes = b"Oct 10 2026".ljust(16, b"\x00")
    idf_bytes = b"v5.1.2".ljust(32, b"\x00")
    elf_sha = b"\x00" * 32
    reserved2 = b"\x00" * 80

    app_desc = (
        app_desc_magic
        + secure_ver
        + reserved1
        + ver_bytes
        + proj_bytes
        + time_bytes
        + date_bytes
        + idf_bytes
        + elf_sha
        + reserved2
    )

    data = bytearray(b"\x00" * 0x10000)
    data[0:len(header)] = header
    data[0x20:0x20 + len(app_desc)] = app_desc
    return bytes(data)


async def test_publish_cancellation_waits_for_executor_and_does_not_overwrite_subsequent_publish(
    hass: HomeAssistant,
) -> None:
    """[P1] Test that cancelled publish thread completes rollback before subsequent publish can proceed."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_cancel_race_test")

    # 1. Initially publish v1.0.0
    blob_v100 = _make_valid_esp32_bin("1.0.0")
    info_v100 = inspect_binary(blob_v100, target_platform="esp32", reserved_version="1.0.0")
    artifact_v100 = await publisher.async_publish(
        device_id="dev_race",
        configuration="dev_race.yaml",
        slug="dev_race_slug",
        blob=blob_v100,
        info=info_v100,
    )
    manifest_path = Path(artifact_v100.public_manifest_path)
    bin_path = Path(artifact_v100.public_bin_path)

    # 2. Start Job 1 (v1.0.1) which delays in executor during cancellation check
    blob_v101 = _make_valid_esp32_bin("1.0.1")
    info_v101 = inspect_binary(blob_v101, target_platform="esp32", reserved_version="1.0.1")

    def check_cancel_with_delay() -> bool:
        time.sleep(0.15)
        return True

    task1 = asyncio.create_task(
        publisher.async_publish(
            device_id="dev_race",
            configuration="dev_race.yaml",
            slug="dev_race_slug",
            blob=blob_v101,
            info=info_v101,
            check_cancelled=check_cancel_with_delay,
        )
    )

    # Allow task1 to start and enter executor
    await asyncio.sleep(0.02)
    # Cancel task1
    task1.cancel()

    # 3. Immediately start Job 2 (v1.0.2) for the SAME slug
    blob_v102 = _make_valid_esp32_bin("1.0.2")
    info_v102 = inspect_binary(blob_v102, target_platform="esp32", reserved_version="1.0.2")

    async def run_job2():
        return await publisher.async_publish(
            device_id="dev_race",
            configuration="dev_race.yaml",
            slug="dev_race_slug",
            blob=blob_v102,
            info=info_v102,
        )

    task2 = asyncio.create_task(run_job2())

    # Wait for task1 to finish its cancellation handling
    with pytest.raises(asyncio.CancelledError):
        await task1

    # Wait for task2 to complete
    artifact_v102 = await task2
    assert artifact_v102.version == "1.0.2"

    # Crucial assertion:
    # Public manifest must be 1.0.2, NOT rolled back to 1.0.0!
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["version"] == "1.0.2"
    assert bin_path.read_bytes() == blob_v102


async def test_publish_cancellation_before_executor_start_unblocks_cleanly(
    hass: HomeAssistant,
) -> None:
    """[P1] Cancelling publish before executor thread starts unblocks task and releases slug lock."""
    import concurrent.futures

    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_cancel_before_start_test")
    blob = _make_valid_esp32_bin("1.0.0")
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # 1. Occupy the 1-worker executor with a blocking event
    blocker_done = threading.Event()
    blocker_started = threading.Event()

    def blocker():
        blocker_started.set()
        blocker_done.wait(timeout=2.0)

    pool.submit(blocker)
    assert blocker_started.wait(timeout=1.0)

    # 2. Direct publisher's executor jobs to this 1-worker pool
    with patch.object(
        hass,
        "async_add_executor_job",
        side_effect=lambda target, *args: hass.loop.run_in_executor(pool, target, *args),
    ):
        task = asyncio.create_task(
            publisher.async_publish(
                device_id="dev_busy",
                configuration="dev_busy.yaml",
                slug="dev_busy_slug",
                blob=blob,
                info=info,
            )
        )

        # Allow task to queue in executor without starting
        await asyncio.sleep(0.01)

        # 3. Cancel task while queued in executor
        task.cancel()

        # Task must complete cancellation cleanly without hanging
        with pytest.raises(asyncio.CancelledError):
            await task

    # Release the blocker and shutdown pool
    blocker_done.set()
    pool.shutdown(wait=True)

    # 4. Crucial assertion: Slug lock MUST be free, and a subsequent publish must succeed immediately
    subsequent_artifact = await publisher.async_publish(
        device_id="dev_busy",
        configuration="dev_busy.yaml",
        slug="dev_busy_slug",
        blob=blob,
        info=info,
    )
    assert subsequent_artifact.version == "1.0.0"


async def test_select_same_builder_restores_suppress_counter_and_allows_subsequent_options_reload(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] Selecting same builder restores suppress counter so subsequent options changes trigger reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: "https://ha.local", CONF_BUILDER_SLUG: "c1"},
        options={CONF_BUILDER_SLUG: "c1"},
    )
    entry.add_to_hass(hass)

    cand1 = BuilderCandidate(
        slug="c1",
        name="Candidate 1",
        host="127.0.0.1",
        port=mock_builder.port,
        source="supervisor_addon",
        is_running=True,
    )

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[cand1],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        manager: OtaManager = hass.data[DOMAIN]["manager"]
        assert manager._suppress_reload_count == 0

        # Select the SAME builder "c1"
        client = await hass_ws_client(hass)
        await client.send_json(
            {
                "id": 1,
                "type": "esphome_ota/select_builder",
                "slug": "c1",
            }
        )
        resp = await client.receive_json()
        assert resp["success"] is True

        # Counter must be restored to 0 because entry did not change
        assert manager._suppress_reload_count == 0

        # Now update base_url in options flow / config entry
        # This MUST trigger a reload because suppress_reload_count is 0!
        with patch.object(hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload) as mock_reload:
            hass.config_entries.async_update_entry(
                entry,
                options={CONF_BUILDER_SLUG: "c1", CONF_BASE_URL: "https://new-url.local"},
            )
            await hass.async_block_till_done()
            assert mock_reload.called

        await client.close()
        await hass.config_entries.async_unload(entry.entry_id)
