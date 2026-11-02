"""Tests for RP platform rejection, legacy migration platform, and Builder client hardening."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.ha_discovery import HaDiscoveryAdapter
from custom_components.esphome_ota.const import MAX_UPLOAD_SIZE
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.migration import MigrationManager
from custom_components.esphome_ota.models import (
    BuilderError,
    ConfigConflictError,
    UnsupportedPlatformError,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager


@pytest.mark.parametrize("platform", ["rp2040", "RP2350", "rp-2040"])
def test_inspect_binary_rejects_rp_platforms(platform: str) -> None:
    """RP images have no verifiable header, so they are rejected up front."""
    with pytest.raises(UnsupportedPlatformError, match="not supported"):
        inspect_binary(b"\xe9" + b"\x00" * 2000, target_platform=platform)


async def test_start_build_rejects_rp_platform(hass: HomeAssistant) -> None:
    """A build for an RP device is refused before any job is created."""
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    runner = JobRunner(
        hass, storage, device_manager, ArtifactPublisher(hass, publish_dir="rp_test")
    )
    dev = await device_manager.async_register_or_update(
        device_id="picow",
        configuration="picow",
        name="picow",
        friendly_name="Pico W",
        target_platform="rp2040",
    )
    with pytest.raises(UnsupportedPlatformError):
        await runner.async_start_build_pipeline(
            device=dev, client=MagicMock(), base_url="http://ha.local:8123"
        )
    assert not runner._active_jobs


async def test_migration_inspects_with_builder_platform(hass: HomeAssistant) -> None:
    """Legacy ESP8266 binaries are inspected against the Builder's platform."""
    esphome_dir = Path(hass.config.path("esphome"))
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "registered.json").write_text(
        json.dumps({"oldnode": {"token": "", "version": "1.0.0", "title": "Old"}}),
        encoding="utf-8",
    )
    www_dir = Path(hass.config.path("www", "esphome_ota_pub"))
    www_dir.mkdir(parents=True, exist_ok=True)
    # ESP8266-style image: magic byte, non-ESP32 chip_id bytes, non-zero guard bytes
    blob = bytearray(b"\xe9\x04\x02\x40" + b"\x00" * 2000)
    blob[12:14] = b"\x34\x12"
    blob[19:23] = b"\x01\x02\x03\x04"
    (www_dir / "oldnode.ota.bin").write_bytes(bytes(blob))

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    device_manager.update_builder_devices(
        [
            {
                "name": "oldnode",
                "configuration": "oldnode.yaml",
                "target_platform": "ESP8266",
            }
        ]
    )
    publisher = MagicMock()
    migrator = MigrationManager(hass, storage, device_manager, publisher)
    migrator.hass.config.path = lambda *parts: str(Path(hass.config.config_dir, *parts))

    platforms = await migrator._async_legacy_platforms()
    assert platforms == {"oldnode": "ESP8266"}
    with patch(
        "custom_components.esphome_ota.migration.DEFAULT_PUBLISH_DIR", "esphome_ota_pub"
    ):
        result = migrator._execute_migration_sync(platforms)
    assert result["migrated_artifacts"] == ["oldnode"]
    assert publisher._publish_sync.call_args.kwargs["info"].chip_family == "ESP8266"


def _client_with_response(resp: MagicMock) -> BuilderClient:
    conn = MagicMock()
    conn.base_url = "http://builder"
    conn.command = AsyncMock(return_value={"token": "t"})
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    conn.session.get = MagicMock(return_value=ctx)
    return BuilderClient(conn)


def _response(content_length: int | None, chunks: list[bytes]) -> MagicMock:
    resp = MagicMock()
    resp.status = 200
    resp.content_length = content_length

    async def _iter(_size: int):
        for chunk in chunks:
            yield chunk

    resp.content.iter_chunked = _iter
    return resp


async def test_download_ota_ok() -> None:
    """A normal download is reassembled from chunks."""
    client = _client_with_response(_response(6, [b"abc", b"def"]))
    assert await client.download_ota("n", filename="firmware.ota.bin") == b"abcdef"


async def test_download_ota_rejects_large_content_length() -> None:
    """An oversized Content-Length is refused before reading the body."""
    client = _client_with_response(_response(MAX_UPLOAD_SIZE + 1, [b"x"]))
    with pytest.raises(BuilderError, match="exceeds"):
        await client.download_ota("n", filename="firmware.ota.bin")


async def test_download_ota_rejects_oversized_stream() -> None:
    """A body larger than the limit is cut off even without Content-Length."""
    half = b"x" * (MAX_UPLOAD_SIZE // 2 + 1)
    client = _client_with_response(_response(None, [half, half]))
    with pytest.raises(BuilderError, match="exceeds"):
        await client.download_ota("n", filename="firmware.ota.bin")


@pytest.mark.parametrize(
    ("error", "is_conflict"),
    [
        (BuilderError("failed: CAS_CONFLICT x", error_code="CAS_CONFLICT"), True),
        # Structured code wins over misleading words in the message
        (
            BuilderError("failed: expected a string", error_code="INVALID_ARGUMENT"),
            False,
        ),
        # No structured code: legacy message fallback
        (BuilderError("failed: content mismatch"), True),
        (BuilderError("failed: disk full"), False),
    ],
)
async def test_update_config_conflict_classification(
    error: BuilderError, is_conflict: bool
) -> None:
    """CAS conflicts are classified by error_code first, message as fallback."""
    conn = MagicMock()
    conn.command = AsyncMock(side_effect=error)
    client = BuilderClient(conn)
    expected_exc = ConfigConflictError if is_conflict else BuilderError
    with pytest.raises(expected_exc) as exc:
        await client.update_config("n.yaml", "new", expected="old")
    assert isinstance(exc.value, ConfigConflictError) is is_conflict


@pytest.mark.parametrize(
    "stored",
    [
        None,
        [],
        {"info": "nope"},
        {"info": {"host": "h", "port": "6052"}},
        {"info": {"host": 5, "port": 6052}},
        {"info": {"host": "h", "port": 6052, "addon_slug": None}},
        {"info": {"host": "h", "port": 99999}},
    ],
)
async def test_dashboard_storage_unexpected_format(
    hass: HomeAssistant, stored: object
) -> None:
    """Unexpected esphome.dashboard storage shapes yield no candidate."""
    with (
        patch("homeassistant.helpers.storage.Store.async_load", return_value=stored),
    ):
        adapter = HaDiscoveryAdapter(hass)
        assert await adapter.async_discover_from_esphome_dashboard() == []


async def test_dashboard_storage_valid(hass: HomeAssistant) -> None:
    """A well-formed stored dashboard record still produces a candidate."""
    stored = {"info": {"host": "127.0.0.1", "port": 6052, "addon_slug": "esphome"}}
    with (
        patch("homeassistant.helpers.storage.Store.async_load", return_value=stored),
    ):
        candidates = await HaDiscoveryAdapter(
            hass
        ).async_discover_from_esphome_dashboard()
    assert [c.port for c in candidates] == [6052]
