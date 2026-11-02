"""Tests for storage caching, public-binary lookup and executor offloading."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
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
from custom_components.esphome_ota.models import ManagedDevice, PublishedArtifact
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
    """An exception escaping Store.async_save drops the entry (re-read later)."""
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


async def test_storage_concurrent_save_not_overwritten_by_slow_load(
    hass: HomeAssistant,
) -> None:
    """A save during the first disk read wins over the stale loaded value."""
    storage = StorageManager(hass)
    gate = asyncio.Event()

    async def slow_load() -> dict[str, Any]:
        await gate.wait()
        return {"old": True}

    with patch.object(storage._migration_store, "async_load", slow_load):
        load_task = asyncio.ensure_future(storage.async_load_migration())
        await asyncio.sleep(0)
        await storage.async_save_migration({"new": True})
        gate.set()
        await load_task
    assert await storage.async_load_migration() == {"new": True}


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

    async def has_public() -> bool:
        await dm.async_refresh_public_scan()
        return dm.list_all()[0]["has_public_binary"]

    assert await has_public() is False
    binfile = pub / "a_tok.ota.bin"
    binfile.write_bytes(b"x")
    (pub / "a_tok.ota.bin.md5").write_text("m")
    assert await has_public() is True
    # Let the rescan scheduled for the unsettled directory finish first.
    if dm._public_scan_task is not None:
        await dm._public_scan_task
    # Cached scan is reused while the directory is unchanged.
    with patch("custom_components.esphome_ota.devices.os.scandir") as scandir:
        # Make the entry look settled so the cache is trusted.
        mtime, _trusted, slugs = dm._public_scan
        dm._public_scan = (mtime, True, slugs)
        assert dm.list_all()[0]["has_public_binary"] is True
        scandir.assert_not_called()
    binfile.unlink()
    # Force a distinct directory mtime regardless of filesystem granularity.
    st = pub.stat()
    os.utime(pub, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert await has_public() is False


async def test_public_binary_scan_runs_off_event_loop(hass: HomeAssistant) -> None:
    """list_all never scans on the loop; a background scan updates and notifies."""
    pub = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    pub.mkdir(parents=True, exist_ok=True)
    (pub / "a_tok.ota.bin").write_bytes(b"x")
    dm = DeviceManager(hass, StorageManager(hass))
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
    loop_thread = threading.get_ident()
    scan_threads: list[int] = []
    real = DeviceManager._scan_public_dir

    def spy(pub_dir: Path) -> set[str] | None:
        scan_threads.append(threading.get_ident())
        return real(pub_dir)

    notified: list[bool] = []
    dm.public_scan_listener = lambda: notified.append(True)
    with patch.object(DeviceManager, "_scan_public_dir", staticmethod(spy)):
        dm.list_all()
        await hass.async_block_till_done()
    assert scan_threads
    assert all(t != loop_thread for t in scan_threads)
    assert notified == [True]
    assert dm.list_all()[0]["has_public_binary"] is True


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
        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
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


async def _setup_ws(hass, hass_ws_client, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await manager.device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )
    return manager, await hass_ws_client(hass)


def _artifact() -> PublishedArtifact:
    return PublishedArtifact(
        device_id="livingroom",
        configuration="livingroom.yaml",
        version="1.0.0",
        chip_family="ESP32",
        size=1,
        md5="m",
        sha256="s",
        published_at="2026-01-01T00:00:00+00:00",
        private_path="p",
        public_bin_path="b",
        public_manifest_path="m",
        is_public=False,
    )


async def test_set_publication_policy_with_artifact_saves_once(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """An existing publication updates it and saves devices exactly once."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, ws = await _setup_ws(hass, hass_ws_client, mock_config_entry)
        await manager.storage.async_save_artifact("livingroom", _artifact())
        with patch.object(
            manager.storage, "async_save_devices", AsyncMock()
        ) as save_devices:
            await ws.send_json(
                {
                    "id": 1,
                    "type": "esphome_ota/set_publication_policy",
                    "device_id": "livingroom",
                    "cleanup_hours": 6,
                    "auto_hide": False,
                    "save_as_default": True,
                }
            )
            msg = await ws.receive_json()
        assert msg["success"] is True
        assert save_devices.await_count == 1
        art = (await manager.storage.async_load_artifacts())["livingroom"]
        assert art.cleanup_hours == 6


async def test_set_publication_policy_changed_still_saves_defaults(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """publication_changed and exceptions still persist the saved defaults."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, ws = await _setup_ws(hass, hass_ws_client, mock_config_entry)
        await manager.storage.async_save_artifact("livingroom", _artifact())
        payload = {
            "type": "esphome_ota/set_publication_policy",
            "device_id": "livingroom",
            "cleanup_hours": 9,
            "auto_hide": False,
            "save_as_default": True,
        }
        with (
            patch.object(
                manager.storage,
                "async_update_artifact_policy_if_current",
                AsyncMock(return_value=None),
            ),
            patch.object(
                manager.storage, "async_save_devices", AsyncMock()
            ) as save_devices,
        ):
            await ws.send_json({"id": 1, **payload})
            msg = await ws.receive_json()
            assert msg["success"] is False
            assert msg["error"]["code"] == "publication_changed"
            assert save_devices.await_count == 1

        with (
            patch.object(
                manager.storage,
                "async_update_artifact_policy_if_current",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch.object(
                manager.storage, "async_save_devices", AsyncMock()
            ) as save_devices,
        ):
            await ws.send_json({"id": 2, **payload})
            await ws.receive_json()
            assert save_devices.await_count == 1


async def test_upload_inspects_binary_in_executor(
    hass: HomeAssistant,
    hass_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """The HTTP upload path inspects the binary off the event loop."""
    from aiohttp import FormData

    from custom_components.esphome_ota import http

    loop_thread = threading.get_ident()
    seen: list[int] = []
    real = http.inspect_binary

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        await manager.device_manager.async_register_or_update(
            device_id="livingroom",
            configuration="livingroom",
            name="livingroom",
            friendly_name="Living Room",
        )
        client = await hass_client()
        form = FormData()
        blob = bytearray(2048)
        blob[0] = 0xE9
        blob[32:36] = b"\xab\xcd\x12\x00"
        blob[48:53] = b"1.0.0"
        form.add_field("file", bytes(blob), filename="f.bin")
        with patch.object(http, "inspect_binary", spy):
            resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 200
    assert seen
    assert loop_thread not in seen
