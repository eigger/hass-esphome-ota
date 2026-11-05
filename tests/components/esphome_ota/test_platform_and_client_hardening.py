"""Tests for RP platform rejection and Builder client hardening."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.const import (
    DOMAIN,
    MAX_UPLOAD_SIZE,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.jobs import JobRunner
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
    manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
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
