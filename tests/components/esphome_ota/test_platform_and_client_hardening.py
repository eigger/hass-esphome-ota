"""Tests for RP platform rejection, legacy migration platform, and Builder client hardening."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.ha_discovery import HaDiscoveryAdapter
from custom_components.esphome_ota.const import (
    DEFAULT_PUBLISH_DIR,
    DOMAIN,
    MAX_UPLOAD_SIZE,
)
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


def _esp8266_blob() -> bytes:
    """ESP8266-style image: magic byte, non-ESP32 chip_id bytes, non-zero guard bytes."""
    blob = bytearray(b"\xe9\x04\x02\x40" + b"\x00" * 2000)
    blob[12:14] = b"\x34\x12"
    blob[19:23] = b"\x01\x02\x03\x04"
    return bytes(blob)


def _legacy_setup(
    hass: HomeAssistant,
    registered: dict,
    builder_devices: list[dict],
    publisher: object | None = None,
) -> tuple[MigrationManager, DeviceManager, Path]:
    esphome_dir = Path(hass.config.path("esphome"))
    for old in esphome_dir.glob("*.yaml"):
        old.unlink(missing_ok=True)
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "registered.json").write_text(
        json.dumps(registered), encoding="utf-8"
    )
    www_dir = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    www_dir.mkdir(parents=True, exist_ok=True)
    for old in www_dir.glob("*"):
        old.unlink(missing_ok=True)
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    device_manager.update_builder_devices(builder_devices)
    publisher = publisher or ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)
    return (
        MigrationManager(hass, storage, device_manager, publisher),
        device_manager,
        www_dir,
    )


async def test_migration_inspects_with_builder_platform(hass: HomeAssistant) -> None:
    """Legacy ESP8266 binaries are inspected against the Builder's platform."""
    publisher = MagicMock()
    migrator, _, www_dir = _legacy_setup(
        hass,
        {"oldnode": {"token": "", "version": "1.0.0", "title": "Old"}},
        [
            {
                "name": "oldnode",
                "configuration": "oldnode.yaml",
                "target_platform": "ESP8266",
            }
        ],
        publisher,
    )
    (www_dir / "oldnode.ota.bin").write_bytes(_esp8266_blob())

    targets = await migrator._async_legacy_targets()
    assert targets["oldnode"]["platform"] == "ESP8266"
    result = migrator._execute_migration_sync(targets)
    assert result["migrated_artifacts"] == ["oldnode"]
    assert publisher._publish_sync.call_args.kwargs["info"].chip_family == "ESP8266"


async def test_migration_unregistered_esp8266_keeps_platform(
    hass: HomeAssistant,
) -> None:
    """ESP8266 detected by fallback is registered as ESP8266, not esp32."""
    migrator, device_manager, www_dir = _legacy_setup(
        hass, {"oldnode": {"token": "", "version": "1.0.0", "title": "Old"}}, []
    )
    (www_dir / "oldnode.ota.bin").write_bytes(_esp8266_blob())

    res = await migrator.async_migrate()
    assert res["success"] is True
    dev = device_manager.get_device("oldnode")
    assert dev is not None
    assert dev.target_platform == "esp8266"
    assert dev.chip_family == "ESP8266"


async def test_migration_raw_without_platform_uses_detected(
    hass: HomeAssistant,
) -> None:
    """A Builder entry lacking target_platform still gets the detected platform."""
    migrator, device_manager, www_dir = _legacy_setup(
        hass,
        {"oldnode": {"token": "", "version": "1.0.0", "title": "Old"}},
        [{"name": "oldnode", "configuration": "oldnode.yaml"}],
    )
    (www_dir / "oldnode.ota.bin").write_bytes(_esp8266_blob())
    res = await migrator.async_migrate()
    assert res["success"] is True
    assert device_manager.get_device("oldnode").target_platform == "esp8266"


async def test_migration_artifact_key_matches_device_key(hass: HomeAssistant) -> None:
    """Artifacts are published under the resolved Builder device_id."""
    publisher = MagicMock()
    migrator, _, www_dir = _legacy_setup(
        hass,
        {"node": {"token": "tok", "version": "1.0.0", "title": "N"}},
        [
            {
                "name": "node",
                "configuration": "node_tok.yaml",
                "target_platform": "ESP8266",
            }
        ],
        publisher,
    )
    (www_dir / "node_tok.ota.bin").write_bytes(_esp8266_blob())
    targets = await migrator._async_legacy_targets()
    migrator._execute_migration_sync(targets)
    kwargs = publisher._publish_sync.call_args.kwargs
    assert kwargs["device_id"] == targets["node"]["device_id"] != "node"
    assert kwargs["configuration"] == "node_tok.yaml"


async def test_migration_rejects_rp_device(hass: HomeAssistant) -> None:
    """RP devices are reported as failed and never registered or YAML-patched."""
    migrator, device_manager, _ = _legacy_setup(
        hass,
        {"picow": {"token": "", "version": "1.0.0", "title": "Pico"}},
        [{"name": "picow", "configuration": "picow.yaml", "target_platform": "RP2040"}],
    )
    client = AsyncMock()
    migrator._builder_client = client
    res = await migrator.async_migrate()
    assert res["success"] is False
    assert "not supported" in res["failed_devices"]["picow"]
    assert res["migrated_devices"] == []
    assert device_manager.get_device("picow") is None
    client.update_config.assert_not_called()


async def test_chip_family_esp8266_fallback_rejects_esp32_header() -> None:
    """An ESP32 extended header is never accepted as an ESP8266 image."""
    from custom_components.esphome_ota.firmware import chip_family

    blob = bytearray(b"\xe9" + b"\x00" * 2000)
    blob[12:14] = b"\x05\x00"  # ESP32-C3 chip_id
    assert chip_family("esp8266", bytes(blob)) == (None, "invalid")


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


async def test_download_ota_allows_exact_max_size() -> None:
    """Content-Length == MAX_UPLOAD_SIZE is the permitted boundary."""
    client = _client_with_response(_response(MAX_UPLOAD_SIZE, [b"x" * 1024]))
    assert len(await client.download_ota("n", filename="firmware.ota.bin")) == 1024


async def test_update_config_unknown_code_falls_back_to_message() -> None:
    """A generic Builder code does not hide a CAS conflict described in the message."""
    conn = MagicMock()
    conn.command = AsyncMock(
        side_effect=BuilderError(
            "failed: content mismatch", error_code="COMMAND_FAILED"
        )
    )
    with pytest.raises(ConfigConflictError):
        await BuilderClient(conn).update_config("n.yaml", "new", expected="old")


def test_unwrap_propagates_error_code() -> None:
    """BuilderConnection._unwrap keeps the structured error_code on BuilderError."""
    from custom_components.esphome_ota.builder.connection import BuilderConnection

    with pytest.raises(BuilderError) as exc:
        BuilderConnection._unwrap(
            "devices/update_config", {"error_code": "CAS_CONFLICT", "details": "x"}
        )
    assert exc.value.error_code == "CAS_CONFLICT"


async def test_stream_propagates_error_code() -> None:
    """Streamed error frames also carry error_code."""
    import aiohttp

    from custom_components.esphome_ota.builder.connection import BuilderConnection

    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", 1, session)
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"error_code": "CAS_CONFLICT", "details": "x"})
        conn._send_frame = AsyncMock(return_value=("1", queue))
        conn._queues["1"] = queue
        with (
            patch.object(
                BuilderConnection, "is_connected", new_callable=PropertyMock
            ) as connected,
            pytest.raises(BuilderError) as exc,
        ):
            connected.return_value = True
            async for _ in conn.stream("devices/update_config", {}, timeout=5):
                pass
    assert exc.value.error_code == "CAS_CONFLICT"


async def _setup_ws(hass, hass_ws_client, mock_config_entry, builder_devices):
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    manager = hass.data[DOMAIN]["manager"]
    manager.device_manager.update_builder_devices(builder_devices)
    manager.resolver.active_client = AsyncMock()
    return manager, await hass_ws_client(hass)


async def test_ws_rp_rejected_without_registering(
    hass: HomeAssistant, hass_ws_client, mock_config_entry, mock_builder
) -> None:
    """Build/prepare/apply/batch reject an unmanaged RP device before registering it."""
    manager, ws = await _setup_ws(
        hass,
        hass_ws_client,
        mock_config_entry,
        [{"name": "picow", "configuration": "picow.yaml", "target_platform": "RP2040"}],
    )
    for i, payload in enumerate(
        [
            {"type": "esphome_ota/build", "device_id": "picow"},
            {"type": "esphome_ota/prepare_ota", "device_id": "picow"},
            {"type": "esphome_ota/apply_ota", "device_id": "picow", "content": "x"},
        ],
        start=1,
    ):
        await ws.send_json({"id": i, **payload})
        msg = await ws.receive_json()
        assert msg["success"] is False
        assert msg["error"]["code"] == "unsupported_platform"
    manager.resolver.active_client.update_config.assert_not_called()
    assert manager.device_manager.get_device("picow") is None

    await ws.send_json(
        {"id": 10, "type": "esphome_ota/batch_build", "device_ids": ["picow"]}
    )
    msg = await ws.receive_json()
    assert msg["result"] == {"jobs": {}, "errors": {"picow": "unsupported_platform"}}
