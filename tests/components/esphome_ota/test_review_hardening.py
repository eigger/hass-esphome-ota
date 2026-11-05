"""Regression tests for the HACS default-catalog review (hacs/default#12543)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.builder.ha_discovery import HaDiscoveryAdapter
from custom_components.esphome_ota.const import DEFAULT_PUBLISH_DIR, DOMAIN
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import (
    EsphomeOtaError,
    ManagedDevice,
    PublishedArtifact,
)
from custom_components.esphome_ota.packages import is_valid_token
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.redaction import redact
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_weak_tokens_rotated_and_public_files_removed_on_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Stored devices without a strong token get one; guessable files are removed."""
    www = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    www.mkdir(parents=True, exist_ok=True)
    for suffix in (".ota.bin", ".ota.bin.md5", ".json"):
        (www / f"plain{suffix}").write_text("x", encoding="utf-8")
    strong = "0123456789abcdef0123456789abcdef"
    storage = StorageManager(hass)
    await storage.async_save_devices(
        {
            "plain": ManagedDevice(
                device_id="plain",
                configuration="plain.yaml",
                name="plain",
                friendly_name="Plain",
                token="",
                slug="plain",
            ),
            "strong": ManagedDevice(
                device_id="strong",
                configuration="strong.yaml",
                name="strong",
                friendly_name="Strong",
                token=strong,
                slug=f"strong_{strong}",
            ),
        }
    )
    await storage.async_save_artifact(
        "plain",
        PublishedArtifact(
            device_id="plain",
            configuration="plain.yaml",
            version="1.0.0",
            chip_family="ESP32",
            size=1,
            md5="m",
            sha256="s",
            published_at="2026-10-10T00:00:00Z",
            private_path="/nonexistent",
            public_bin_path=str(www / "plain.ota.bin"),
            public_manifest_path=str(www / "plain.json"),
        ),
    )

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data

        plain = manager.device_manager.get_device("plain")
        assert is_valid_token(plain.token)
        assert plain.slug == f"plain_{plain.token}"
        assert manager.device_manager.get_device("strong").token == strong
        for suffix in (".ota.bin", ".ota.bin.md5", ".json"):
            assert not (www / f"plain{suffix}").exists()
        artifact = (await manager.storage.async_load_artifacts())["plain"]
        assert artifact.is_public is False
        assert artifact.public_bin_path is None
        # The rotation is persisted.
        stored = await StorageManager(hass).async_load_devices()
        assert stored["plain"].token == plain.token
        await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_list_all_never_stats_on_event_loop(hass: HomeAssistant) -> None:
    """The publish directory is stat'ed only in the executor."""
    pub = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    pub.mkdir(parents=True, exist_ok=True)
    dm = DeviceManager(hass, StorageManager(hass))
    loop_thread = threading.get_ident()
    stat_threads: list[int] = []
    real_stat = Path.stat

    def spy(self: Path, *args, **kwargs):
        if self == pub:
            stat_threads.append(threading.get_ident())
        return real_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", spy):
        dm.list_all()
        await hass.async_block_till_done()
        dm.list_all()
        await hass.async_block_till_done()
    assert stat_threads
    assert all(t != loop_thread for t in stat_threads)


async def test_unmatched_frame_payload_is_not_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A late reply (e.g. device YAML with secrets) is never written to the log."""
    secret = "esp-tab_0123456789abcdef0123456789abcdef"
    frames = [
        SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT,
            data=json.dumps(
                {
                    "message_id": "42",
                    "data": f"wifi_password: hunter2\nota_slug: {secret}",
                }
            ),
        ),
        SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data="not json hunter2"),
    ]

    class _FakeWs:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for frame in frames:
                yield frame

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", 1, session)
        conn._ws = _FakeWs()
        with caplog.at_level(
            logging.DEBUG, logger="custom_components.esphome_ota.builder.connection"
        ):
            await conn._read_loop()

    assert "42" in caplog.text
    assert "hunter2" not in caplog.text
    assert "0123456789abcdef" not in caplog.text


async def test_discovery_does_not_touch_core_esphome_internals(
    hass: HomeAssistant,
) -> None:
    """Discovery relies on Supervisor only, not core esphome storage or objects."""
    assert not hasattr(HaDiscoveryAdapter, "async_discover_from_esphome_dashboard")
    source = Path(
        __import__(
            "custom_components.esphome_ota.builder.ha_discovery", fromlist=["x"]
        ).__file__
    ).read_text(encoding="utf-8")
    assert "esphome.dashboard" not in source
    assert "async_get_dashboard" not in source


async def test_leftover_migration_record_removed(hass: HomeAssistant) -> None:
    """The record of the removed legacy add-on import is deleted."""
    storage = StorageManager(hass)
    await storage._async_save(storage._migration_store, {"migrated_at": "x"})
    assert await storage._migration_store.async_load() == {"migrated_at": "x"}
    await storage.async_remove_migration_record()
    # A fresh Store sees nothing (the old instance caches its first load).
    fresh = StorageManager(hass)._migration_store
    assert await fresh.async_load() is None
    assert storage._migration_store.key not in storage._cache


@pytest.mark.parametrize("length", [32, 40, 64])
def test_redaction_covers_every_accepted_token_length(length: int) -> None:
    """Tokens of any accepted length are hidden in logs, not only 32-char ones."""
    token = "a" * length
    out = redact(f"Builder rejected ota_slug: kitchen_{token} in config")
    assert token not in out
    assert "kitchen_***" in out


async def test_build_refuses_device_without_strong_token(hass: HomeAssistant) -> None:
    """A device record with a weak token is never built and published."""
    storage = StorageManager(hass)
    dm = DeviceManager(hass, storage)
    runner = JobRunner(hass, storage, dm, ArtifactPublisher(hass, "weak_tok_test"))
    dev = ManagedDevice(
        device_id="kitchen",
        configuration="kitchen.yaml",
        name="kitchen",
        friendly_name="Kitchen",
        token="",
        slug="kitchen",
    )
    with pytest.raises(EsphomeOtaError, match="strong public URL token"):
        await runner.async_start_build_pipeline(
            device=dev, client=MagicMock(), base_url="http://ha.local:8123"
        )
    assert not runner._active_jobs


async def test_rotation_happens_even_if_cleanup_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed cleanup still rotates the token and warns the user."""
    await StorageManager(hass).async_save_devices(
        {
            "kitchen": ManagedDevice(
                device_id="kitchen",
                configuration="kitchen.yaml",
                name="kitchen",
                friendly_name="Kitchen",
                token="abc",
                slug="kitchen_abc",
            )
        }
    )
    with (
        patch(
            "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
            return_value=[],
        ),
        patch(
            "custom_components.esphome_ota.publisher.ArtifactPublisher.async_deactivate",
            side_effect=PermissionError("read-only"),
        ),
    ):
        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
        dev = manager.device_manager.get_device("kitchen")
        assert is_valid_token(dev.token)
        assert dev.slug == f"kitchen_{dev.token}"
        assert "delete kitchen_***.* from www/" in caplog.text
        assert not any(
            "kitchen_abc" in r.getMessage()
            for r in caplog.records
            if r.name.startswith("custom_components.esphome_ota")
        )
        await hass.config_entries.async_unload(mock_config_entry.entry_id)


async def test_warns_about_guessable_public_files(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Leftover public firmware at a guessable URL is reported at startup."""
    www = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    www.mkdir(parents=True, exist_ok=True)
    for p in www.glob("*"):
        p.unlink()
    (www / "garage.ota.bin").write_bytes(b"x")
    (www / "attic_Ab12Cd.ota.bin").write_bytes(b"x")
    (www / f"porch_{'b' * 32}.ota.bin").write_bytes(b"x")
    try:
        with patch(
            "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
            return_value=[],
        ):
            mock_config_entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
    finally:
        for p in www.glob("*"):
            p.unlink()
    assert "guessable URL was found" in caplog.text
    assert "garage" in caplog.text
    assert "porch_" not in caplog.text
    # The weak token of a still-served file is not written to the log.
    assert "attic_***" in caplog.text
    assert "Ab12Cd" not in caplog.text
