"""Regression tests for the HA-03..HA-12 audit findings (lifecycle, logging, validation)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota import manager as manager_module
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.const import (
    CONF_BASE_URL,
    CONF_BUILDER_SLUG,
    DOMAIN,
    STATUS_SELECTION_REQUIRED,
    STATUS_UNSUPPORTED,
)
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.manager import (
    BACKOFF_STEPS,
    PERMANENT_FAILURE_INTERVAL,
    OtaManager,
)
from custom_components.esphome_ota.models import (
    BuilderAuthError,
    BuilderCandidate,
    BuilderConnectionError,
    PublishedArtifact,
)
from custom_components.esphome_ota.monitor import InstallationMonitor
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.redaction import mask_slug, redact
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

DISCOVERY = (
    "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter."
    "async_discover_all"
)
SECRET = "0123456789abcdef0123456789abcdef"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> OtaManager:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN]["manager"]


def _firmware_blob() -> bytes:
    return b"\xe9" + b"\x00" * 2000


async def test_upload_view_uses_current_manager_after_reload(
    hass: HomeAssistant,
    hass_client: Any,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The upload view is registered once and always resolves the live manager."""
    with patch(DISCOVERY, return_value=[]):
        old_manager = await _setup(hass, mock_config_entry)
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        new_manager = hass.data[DOMAIN]["manager"]
        assert new_manager is not old_manager

        old_manager.device_manager.get_builder_raw = MagicMock(
            side_effect=AssertionError("stale manager used")
        )
        new_manager.device_manager.get_builder_raw = MagicMock(return_value=None)

        client = await hass_client()
        form = aiohttp.FormData()
        form.add_field("file", _firmware_blob(), filename="fw.bin")
        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)

        assert resp.status == 404
        new_manager.device_manager.get_builder_raw.assert_called_once_with("livingroom")

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        form = aiohttp.FormData()
        form.add_field("file", _firmware_blob(), filename="fw.bin")
        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 503


async def test_partial_setup_failure_cleans_up(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failing setup tears down the panel, reconnect task and hass.data."""
    created: list[OtaManager] = []

    def _factory(hass_: HomeAssistant, entry: Any) -> OtaManager:
        created.append(OtaManager(hass_, entry))
        return created[-1]

    mock_config_entry.add_to_hass(hass)
    with (
        patch(DISCOVERY, return_value=[]),
        patch("custom_components.esphome_ota.OtaManager", side_effect=_factory),
        patch(
            "custom_components.esphome_ota.manager.InstallationMonitor.async_setup",
            side_effect=RuntimeError("monitor boom"),
        ),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert DOMAIN not in hass.data
    manager = created[0]
    assert manager._unloaded is True
    assert manager.panel_manager._panel_registered is False
    assert manager._reconnect_task is None
    assert not [t for t in manager.monitor._tasks if not t.done()]


def test_mask_slug_hides_token() -> None:
    assert mask_slug(f"livingroom_{SECRET}") == "livingroom_***"
    assert mask_slug("livingroom_mysecret") == "livingroom_***"
    assert mask_slug("legacy-name") == "legacy-name"


async def test_secret_slug_not_logged(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Publishing, deactivation and cleanup never log the secret URL token."""
    caplog.set_level(logging.DEBUG)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_audit_log")
    slug = f"livingroom_{SECRET}"
    blob = b"\xe9\x00\x00\x00" + b"\x00" * 2000
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")
    await publisher.async_publish(
        device_id="livingroom",
        configuration="livingroom",
        slug=slug,
        blob=blob,
        info=info,
    )
    # Mismatching artifact id -> skip path that used to log the slug
    assert await publisher.async_deactivate(slug, expected_artifact_id="other") is False
    assert await publisher.async_deactivate(slug) is True

    # Corrupt manifest -> error path that used to log the slug
    manifest = publisher.www_dir / f"{slug}.json"
    manifest.write_text("{not json", encoding="utf-8")
    await publisher.async_deactivate(slug, expected_artifact_id="x")

    storage = StorageManager(hass)
    monitor = InstallationMonitor(
        hass,
        DeviceManager(hass, storage),
        publisher,
        cleanup_hours=1,
        event_callback=None,
    )
    monitor.schedule_cleanup("livingroom", slug, delay_seconds=0, artifact_id="x")
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    monitor.async_unload()

    publisher.async_unload()
    await publisher.async_deactivate(slug)

    assert "livingroom_***" in caplog.text
    assert SECRET not in caplog.text


async def test_websocket_file_checks_do_not_block_event_loop(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
    tmp_path: Path,
) -> None:
    """deactivate/set_token touch public files only from executor threads."""
    loop_thread = threading.get_ident()
    blocking: list[str] = []

    def _wrap(name: str) -> Any:
        original = getattr(Path, name)

        def _wrapper(self: Path, *args: Any, **kwargs: Any) -> Any:
            # DeviceManager.list_all()'s per-device stat is a known, separate item.
            if (
                threading.get_ident() == loop_thread
                and "esphome_ota" in str(self)
                and sys._getframe(1).f_code.co_name != "_has_public_bin"
            ):
                blocking.append(f"{name}:{self.name}")
            return original(self, *args, **kwargs)

        return _wrapper

    with patch(DISCOVERY, return_value=[]):
        manager = await _setup(hass, mock_config_entry)
        dev = await manager.device_manager.async_register_or_update(
            device_id="esp-tab",
            configuration="esp-tab.yaml",
            name="esp-tab",
            friendly_name="ESP Tab",
            target_platform="esp32",
            token="old_tok",
        )
        dev.last_published_version = "1.0.0"
        mock_client = AsyncMock()
        mock_client.get_config.return_value = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            "      ota_slug: esp-tab_old_tok\n"
        )
        manager.resolver.active_client = mock_client

        pub_bin = manager.publisher.www_dir / "esp-tab_old_tok.ota.bin"
        pub_bin.parent.mkdir(parents=True, exist_ok=True)
        pub_bin.write_bytes(b"dummy_bin")
        old_manifest = manager.publisher.www_dir / "esp-tab_old_tok.json"
        old_manifest.write_text("{}", encoding="utf-8")
        private_bin = tmp_path / "firmware.ota.bin"
        private_bin.write_bytes(mock_builder.binary_blob)
        art = PublishedArtifact(
            device_id="esp-tab",
            configuration="esp-tab.yaml",
            version="1.0.0",
            chip_family="ESP32",
            size=1024,
            md5="1234567890abcdef",
            sha256="abcdef1234567890",
            published_at="2026-10-10T00:00:00Z",
            private_path=str(private_bin),
            public_bin_path=str(pub_bin),
            public_manifest_path="/tmp/fake.json",
        )
        await manager.storage.async_save_artifacts({"esp-tab": art})

        ws = await hass_ws_client(hass)
        with (
            patch.object(Path, "exists", _wrap("exists")),
            patch.object(Path, "is_file", _wrap("is_file")),
            patch.object(Path, "unlink", _wrap("unlink")),
        ):
            await ws.send_json(
                {
                    "id": 1,
                    "type": "esphome_ota/set_token",
                    "device_id": "esp-tab",
                    "token": "new_tok",
                }
            )
            msg = await ws.receive_json()
            while msg.get("type") == "event":
                msg = await ws.receive_json()
            assert msg["success"] is True, msg

            await ws.send_json(
                {"id": 2, "type": "esphome_ota/deactivate", "device_id": "esp-tab"}
            )
            msg = await ws.receive_json()
            while msg.get("type") == "event":
                msg = await ws.receive_json()
            assert msg["success"] is True, msg
        await ws.close()

    assert blocking == []


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not a url",
        "ftp://host",
        "http://",
        "https://h:x",
        "https://ha/x?y=1",
        "https://ha/#f",
        "http://u:p@ha",
        "http://ha st",
    ],
)
async def test_config_flow_rejects_invalid_base_url(
    hass: HomeAssistant, bad: str
) -> None:
    with patch(DISCOVERY, return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "confirm_settings"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: bad}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {CONF_BASE_URL: "invalid_url"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BASE_URL: " http://ha.local:8123/ "}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_BASE_URL] == "http://ha.local:8123"


async def test_options_flow_validates_base_url_and_labels_auto(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    with patch(
        DISCOVERY,
        return_value=[
            BuilderCandidate(
                slug="5c53de3b_esphome",
                name="ESPHome",
                host="127.0.0.1",
                port=6052,
                source="supervisor",
            )
        ],
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        selector_config = result["data_schema"].schema[CONF_BUILDER_SLUG].config
        assert selector_config["translation_key"] == "builder_slug"
        assert {o["value"] for o in selector_config["options"]} >= {
            "auto",
            "5c53de3b_esphome",
        }

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_BASE_URL: "javascript:alert(1)", "auto_cleanup_hours": 6},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {CONF_BASE_URL: "invalid_url"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_BASE_URL: "https://ok.example.com/", "auto_cleanup_hours": 6},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_BASE_URL] == "https://ok.example.com"


def test_translations_cover_new_strings() -> None:
    root = Path(__file__).parents[3] / "custom_components" / "esphome_ota"
    for name in ("strings.json", "translations/en.json", "translations/ko.json"):
        data = json.loads((root / name).read_text(encoding="utf-8"))
        assert data["config"]["error"]["invalid_url"]
        assert data["options"]["error"]["invalid_url"]
        assert data["options"]["step"]["init"]["data"]["builder_slug"]
        assert data["selector"]["builder_slug"]["options"]["auto"]
    config_flow = (root / "config_flow.py").read_text(encoding="utf-8")
    assert "Auto-detect" not in config_flow


async def test_single_config_entry_declared(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.manifest["single_config_entry"] is True


async def test_second_config_flow_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_monitor_unload_cancels_tasks_and_blocks_refresh(
    hass: HomeAssistant,
) -> None:
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_audit_mon")
    monitor = InstallationMonitor(hass, device_manager, publisher, cleanup_hours=1)

    gate = asyncio.Event()

    async def _forever() -> None:
        await gate.wait()

    monitor._track_task(_forever())
    (task,) = monitor._tasks
    monitor.async_unload()
    await asyncio.sleep(0)
    assert task.cancelled()
    assert not monitor._tasks

    # Unloaded: new work is refused and no listeners are attached.
    closed = _forever()
    monitor._track_task(closed)
    assert not monitor._tasks
    with patch.object(device_manager, "list_all") as list_all:
        await monitor.async_refresh_monitoring()
        list_all.assert_not_called()
    monitor.schedule_cleanup("livingroom", "livingroom", delay_seconds=0)
    assert not monitor._cleanup_timers


async def test_reconnect_loop_backs_off_long_for_auth_and_selection(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    manager = OtaManager(hass, mock_config_entry)
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= 3:
            manager._unloaded = True

    manager.resolver.async_resolve = AsyncMock(side_effect=BuilderAuthError("auth"))
    manager.resolver.status = STATUS_UNSUPPORTED
    manager._note_connect_failure(BuilderAuthError("auth"))
    with patch.object(manager_module.asyncio, "sleep", _fake_sleep):
        await manager._reconnect_loop()
    assert delays
    assert all(d >= PERMANENT_FAILURE_INTERVAL * 0.8 for d in delays)

    # selection_required is treated the same way
    manager._unloaded = False
    manager._permanent_failure = False
    delays.clear()
    manager.resolver.status = STATUS_SELECTION_REQUIRED
    manager.resolver.async_resolve = AsyncMock(
        side_effect=BuilderConnectionError("Selection required")
    )
    manager._note_connect_failure(BuilderConnectionError("x"))
    assert manager._permanent_failure is True

    # A plain connection error keeps the short backoff.
    manager._unloaded = False
    delays.clear()
    manager.resolver.status = "waiting"
    manager._note_connect_failure(BuilderConnectionError("down"))
    assert manager._permanent_failure is False
    manager._reconnect_backoff_index = 0
    with patch.object(manager_module.asyncio, "sleep", _fake_sleep):
        await manager._reconnect_loop()
    assert max(delays) <= BACKOFF_STEPS[-1] * 1.2
    await manager.async_unload()


async def test_unload_awaits_reconnect_task_and_uses_background_task(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    with patch(DISCOVERY, return_value=[]):
        manager = await _setup(hass, mock_config_entry)
        task = manager._reconnect_task
        assert task is not None and not task.done()
        assert task in mock_config_entry._background_tasks

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert task.done()
        assert manager._reconnect_task is None


async def test_reconnect_loop_propagates_cancellation(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    manager = OtaManager(hass, mock_config_entry)
    task = asyncio.create_task(manager._reconnect_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    await manager.async_unload()


async def test_ws_connect_timeout_raises_connection_error() -> None:
    class HangingSession:
        async def ws_connect(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(60)

    conn = BuilderConnection("127.0.0.1", 1, HangingSession())  # type: ignore[arg-type]
    with (
        patch(
            "custom_components.esphome_ota.builder.connection.WS_CONNECT_TIMEOUT", 0.05
        ),
        pytest.raises(BuilderConnectionError, match="Timed out"),
    ):
        await conn.connect()


async def test_builder_slug_data_keys_use_constants() -> None:
    from custom_components.esphome_ota import const

    assert const.CONF_BUILDER_HOST == "builder_host"
    assert const.CONF_BUILDER_PORT == "builder_port"
    source = (Path(__file__).parents[3] / "custom_components" / "esphome_ota").glob(
        "*.py"
    )
    for path in source:
        if path.name == "const.py":
            continue
        assert not re.search(r"""["']builder_(host|port)["']""", path.read_text())


async def test_log_filter_redacts_exceptions_and_custom_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """OSError file names and tracebacks never reveal tokens, whatever their shape."""
    from custom_components.esphome_ota import publisher as publisher_module

    path = "/config/www/esphome_ota/livingroom_mysecret.ota.bin"
    assert redact(f"[Errno 13] Permission denied: '{path}'") == (
        "[Errno 13] Permission denied: '/config/www/esphome_ota/livingroom_***.ota.bin'"
    )
    caplog.set_level(logging.DEBUG)
    try:
        raise PermissionError(13, "Permission denied", path)
    except PermissionError as err:
        publisher_module._LOGGER.exception("failed: %s", err)
    assert "mysecret" not in caplog.text
    assert "mysecret" not in caplog.records[-1].exc_text
    assert "livingroom_***.ota.bin" in caplog.text


async def test_upload_refused_until_manager_ready(
    hass: HomeAssistant, hass_client: Any, mock_config_entry: MockConfigEntry
) -> None:
    with patch(DISCOVERY, return_value=[]):
        manager = await _setup(hass, mock_config_entry)
        manager.ready = False
        client = await hass_client()
        form = aiohttp.FormData()
        form.add_field("file", _firmware_blob(), filename="fw.bin")
        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 503


async def test_http_403_is_a_permanent_failure(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    from custom_components.esphome_ota.models import BuilderForbiddenError

    mock_config_entry.add_to_hass(hass)
    manager = OtaManager(hass, mock_config_entry)
    manager._note_connect_failure(BuilderForbiddenError("403"))
    assert manager._permanent_failure is True
    await manager.async_unload()


async def test_selection_required_loop_uses_long_interval(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    manager = OtaManager(hass, mock_config_entry)
    delays: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= 2:
            manager._unloaded = True

    async def _resolve() -> Any:
        manager.resolver.status = STATUS_SELECTION_REQUIRED
        raise BuilderConnectionError("Selection required")

    manager.resolver.async_resolve = _resolve  # type: ignore[method-assign]
    with patch.object(manager_module.asyncio, "sleep", _fake_sleep):
        await manager._reconnect_loop()
    # first delay is the initial short backoff; after the first failure it is long
    assert delays[-1] >= PERMANENT_FAILURE_INTERVAL * 0.8
    await manager.async_unload()


async def test_setup_cleanup_failure_still_raises_original(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    with (
        patch(DISCOVERY, return_value=[]),
        patch(
            "custom_components.esphome_ota.manager.InstallationMonitor.async_setup",
            side_effect=RuntimeError("monitor boom"),
        ),
        patch(
            "custom_components.esphome_ota.manager.OtaManager.async_unload",
            side_effect=RuntimeError("unload boom"),
        ),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert DOMAIN not in hass.data
