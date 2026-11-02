"""Tests for storage caching, public-binary lookup and executor offloading."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp

from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota import jobs
from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    DEFAULT_PUBLISH_DIR,
    DOMAIN,
    STAGE_PUBLISHED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import ManagedDevice
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_storage_cache_hits_disk_once(hass: HomeAssistant) -> None:
    """Repeated loads read the store a single time."""
    storage = StorageManager(hass)
    with patch.object(
        storage._device_store, "async_load", return_value={}
    ) as mock_load:
        await storage.async_load_devices()
        await storage.async_load_devices()
        await storage.async_load_devices()
    assert mock_load.call_count == 1


async def test_storage_save_visible_to_load_and_other_instance(
    hass: HomeAssistant,
) -> None:
    """A save is reflected in later loads, including from another instance."""
    first = StorageManager(hass)
    second = StorageManager(hass)
    assert await first.async_load_devices() == {}
    assert await second.async_load_devices() == {}

    dev = ManagedDevice(
        device_id="a",
        name="a",
        friendly_name="A",
        token="t",
        configuration="a.yaml",
        slug="a",
    )
    await first.async_save_devices({"a": dev})

    assert set(await first.async_load_devices()) == {"a"}
    assert set(await second.async_load_devices()) == {"a"}


async def test_storage_cache_not_polluted_by_caller_mutation(
    hass: HomeAssistant,
) -> None:
    """Mutating a loaded result must not alter what the next load returns."""
    storage = StorageManager(hass)
    await storage.async_save_migration({"nested": {"k": [1]}})
    loaded = await storage.async_load_migration()
    loaded["nested"]["k"].append(2)
    loaded["other"] = True
    assert await storage.async_load_migration() == {"nested": {"k": [1]}}

    payload = {"x": [1]}
    await storage.async_save_migration(payload)
    payload["x"].append(2)
    assert await storage.async_load_migration() == {"x": [1]}


async def test_storage_failed_save_drops_cache(hass: HomeAssistant) -> None:
    """A failed save falls back to re-reading from disk."""
    storage = StorageManager(hass)
    await storage.async_save_migration({"v": 1})
    with patch.object(
        storage._migration_store, "async_save", side_effect=OSError("boom")
    ):
        try:
            await storage.async_save_migration({"v": 2})
        except OSError:
            pass
    assert storage._migration_store.key not in storage._cache


async def test_public_binary_lookup_tracks_directory(hass: HomeAssistant) -> None:
    """has_public_binary follows file creation and removal."""
    pub = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    pub.mkdir(parents=True, exist_ok=True)
    storage = StorageManager(hass)
    dm = DeviceManager(hass, storage)
    dm._managed_devices = {
        "a": ManagedDevice(
            device_id="a",
            name="a",
            friendly_name="A",
            token="t",
            configuration="a.yaml",
            slug="a_tok",
        )
    }

    def has_public() -> bool:
        return dm.list_all()[0]["has_public_binary"]

    assert has_public() is False
    binfile = pub / "a_tok.ota.bin"
    binfile.write_bytes(b"x")
    (pub / "a_tok.ota.bin.md5").write_text("m")
    assert has_public() is True
    # Cached scan is reused while the directory is unchanged.
    with patch("custom_components.esphome_ota.devices.os.scandir") as scandir:
        scandir.side_effect = AssertionError("rescan")
        # Make the entry look settled so the cache is trusted.
        mtime, _trusted, slugs = dm._public_scan
        dm._public_scan = (mtime, True, slugs)
        assert has_public() is True
    binfile.unlink()
    # Force a distinct directory mtime regardless of filesystem granularity.
    st = pub.stat()
    os.utime(pub, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert has_public() is False


async def test_public_binary_lookup_missing_dir(hass: HomeAssistant) -> None:
    """A missing publish directory means no public binaries."""
    dm = DeviceManager(hass, StorageManager(hass))
    dm._managed_devices = {
        "a": ManagedDevice(
            device_id="a",
            name="a",
            friendly_name="A",
            token="t",
            configuration="a.yaml",
            slug="a",
        )
    }
    assert dm.list_all()[0]["has_public_binary"] is False


async def test_pipeline_inspects_binary_in_executor(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """The verify stage hashes and scans the binary off the event loop."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    runner = JobRunner(
        hass,
        storage,
        device_manager,
        ArtifactPublisher(hass, publish_dir="esphome_ota_job_test"),
    )
    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )
    loop_thread = threading.get_ident()
    seen: list[int] = []
    real = jobs.inspect_binary

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        with patch.object(jobs, "inspect_binary", spy):
            job_id = await runner.async_start_build_pipeline(
                device=dev,
                client=BuilderClient(conn),
                base_url="https://my-ha.duckdns.org",
            )
            await runner._active_tasks[job_id]
        await conn.disconnect()

    job = runner.get_job(job_id)
    assert job is not None
    assert job.stage == STAGE_PUBLISHED
    assert seen
    assert loop_thread not in seen


async def test_set_publication_policy_saves_devices_once(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """save_as_default with an active publication persists devices once."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.data[DOMAIN]["manager"]
        await manager.device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom",
            name="livingroom",
            friendly_name="Living Room",
        )
        ws = await hass_ws_client(hass)
        with patch.object(
            manager.storage, "async_save_devices", AsyncMock()
        ) as save_devices:
            await ws.send_json(
                {
                    "id": 1,
                    "type": "esphome_ota/set_publication_policy",
                    "device_id": "livingroom",
                    "cleanup_hours": 12,
                    "auto_hide": False,
                    "save_as_default": True,
                }
            )
            msg = await ws.receive_json()
        assert msg["success"] is True
        assert save_devices.await_count == 1
        dev = manager.device_manager.get_device("livingroom")
        assert dev.publication_cleanup_hours == 12
        assert dev.auto_hide is False
        assert dev.expires_at
