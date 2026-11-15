"""Tests for storing the public slug in secrets.yaml instead of device YAML."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
import yaml
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.builder.client import BuilderClient
from custom_components.esphome_ota.builder.connection import BuilderConnection
from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    ota_base_url_secret_ref,
    ota_slug_secret_ref,
    set_package_ota_slug,
)
from custom_components.esphome_ota.const import DOMAIN, STAGE_PUBLISHED
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.jobs import JobRunner
from custom_components.esphome_ota.models import BuilderError
from custom_components.esphome_ota.packages import (
    BASE_URL_SECRET_KEY,
    generate_inline_ota_yaml,
    remove_secret_text,
    slug_secret_key,
    upsert_secret_text,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

SLUG = "livingroom_0123456789abcdef0123456789abcdef"
KEY = "esphome_ota_slug_livingroom"
NEW_TOKEN = "fedcba9876543210fedcba9876543210"


def test_slug_secret_key_naming() -> None:
    assert slug_secret_key("livingroom") == KEY
    assert slug_secret_key("bed_room2") == "esphome_ota_slug_bed_room2"
    hyphen = slug_secret_key("esp-tab")
    assert re.fullmatch(r"esphome_ota_slug_esp_tab_[0-9a-f]{6}", hyphen)
    # Lossy mappings never collide.
    assert slug_secret_key("esp_tab") != hyphen
    assert slug_secret_key("Esp-Tab") != hyphen
    assert re.fullmatch(r"[a-z0-9_]+", slug_secret_key("Odd.Name-1"))
    assert slug_secret_key("esp-tab") == hyphen  # deterministic


def test_upsert_appends_and_replaces_preserving_content() -> None:
    src = '# my secrets\nwifi_ssid: "home"\n\nwifi_password: "pw"  # keep\n'
    appended = upsert_secret_text(src, KEY, SLUG)
    assert appended == src + f'{KEY}: "{SLUG}"\n'
    replaced = upsert_secret_text(appended, KEY, "new_value")
    assert replaced == src + f'{KEY}: "new_value"\n'
    assert yaml.safe_load(replaced)["wifi_ssid"] == "home"


def test_upsert_missing_file_and_missing_trailing_newline() -> None:
    assert upsert_secret_text("", KEY, SLUG) == f'{KEY}: "{SLUG}"\n'
    assert upsert_secret_text("a: 1", KEY, SLUG) == f'a: 1\n{KEY}: "{SLUG}"\n'


def test_upsert_preserves_crlf() -> None:
    src = "a: 1\r\nb: 2"
    out = upsert_secret_text(src, KEY, SLUG)
    assert out == f'a: 1\r\nb: 2\r\n{KEY}: "{SLUG}"\r\n'
    out2 = upsert_secret_text(out, KEY, "x")
    assert out2 == f'a: 1\r\nb: 2\r\n{KEY}: "x"\r\n'


def test_upsert_does_not_touch_similar_keys() -> None:
    src = f'{KEY}_2: "other"\n'
    out = upsert_secret_text(src, KEY, SLUG)
    assert out.splitlines() == [f'{KEY}_2: "other"', f'{KEY}: "{SLUG}"']


def test_remove_secret_text() -> None:
    src = f'a: 1\n{KEY}: "{SLUG}"\n# c\n'
    out, removed = remove_secret_text(src, KEY)
    assert removed and out == "a: 1\n# c\n"
    assert remove_secret_text(out, KEY) == (out, False)


def test_generate_block_emits_secret_reference() -> None:
    text = generate_inline_ota_yaml("http://ha", SLUG, slug_secret=KEY)
    assert f"ota_slug: !secret {KEY}" in text
    assert SLUG not in text


def test_apply_patch_migrates_plaintext_to_secret() -> None:
    src = (
        "esphome:\n  name: livingroom\npackages:\n  esphome_ota:\n"
        f'    substitutions:\n      ota_slug: "{SLUG}"\n'
    )
    res = apply_ota_patch(src, "http://ha", SLUG, node="livingroom")
    assert SLUG not in res.modified
    assert ota_slug_secret_ref(res.modified) == KEY


def test_apply_patch_emits_both_secrets_and_migrates_plaintext_base_url() -> None:
    src = (
        "esphome:\n  name: livingroom\npackages:\n  esphome_ota:\n"
        '    substitutions:\n      ota_base_url: "http://ha.local:8123"\n'
        f'      ota_slug: "{SLUG}"\n'
    )
    res = apply_ota_patch(src, "http://ha.local:8123/", SLUG, node="livingroom")
    assert "ota_base_url: !secret esphome_ota_base_url" in res.modified
    assert f"ota_slug: !secret {KEY}" in res.modified
    assert "ha.local" not in res.modified
    assert SLUG not in res.modified
    assert ota_base_url_secret_ref(res.modified) == BASE_URL_SECRET_KEY


def test_generate_inlines_base_url_without_secret_key() -> None:
    text = generate_inline_ota_yaml("http://ha/", SLUG)
    assert 'ota_base_url: "http://ha"' in text
    assert ota_base_url_secret_ref(text) is None


def test_set_package_ota_slug_keeps_secret_reference() -> None:
    src = f"substitutions:\n  ota_slug: !secret {KEY}\n"
    assert set_package_ota_slug(src, "livingroom_new") == (src, False)


async def test_client_set_secret_fallback_edits_secrets_yaml() -> None:
    conn = AsyncMock()
    store = {"secrets.yaml": "a: 1"}

    async def command(name, args=None):
        if name == "config/set_secret":
            raise BuilderError("nope", error_code="UNKNOWN_COMMAND")
        if name == "devices/get_config":
            return {"content": store.get(args["configuration"], "")}
        if name == "devices/update_config":
            assert "expected" not in args
            store[args["configuration"]] = args["content"]
            return {}
        raise AssertionError(name)

    conn.command.side_effect = command
    conn.server_info = {}
    client = BuilderClient(conn)
    await client.set_secret(KEY, SLUG)
    assert store["secrets.yaml"] == f'a: 1\n{KEY}: "{SLUG}"\n'


async def test_client_set_secret_fallback_never_wipes_on_read_error() -> None:
    """An unstructured read failure must not be mistaken for a missing file."""
    conn = AsyncMock()

    async def command(name, args=None):
        if name == "config/set_secret":
            raise BuilderError("nope", error_code="UNKNOWN_COMMAND")
        if name == "devices/get_config":
            raise BuilderError("configuration not found in cache")
        raise AssertionError(f"unexpected write: {name}")

    conn.command.side_effect = command
    conn.server_info = {}
    with pytest.raises(BuilderError):
        await BuilderClient(conn).set_secret(KEY, SLUG)


async def test_client_set_secret_propagates_other_errors() -> None:
    conn = AsyncMock()
    conn.command.side_effect = BuilderError("denied", error_code="PERMISSION_DENIED")
    conn.server_info = {}
    with pytest.raises(BuilderError):
        await BuilderClient(conn).set_secret(KEY, SLUG)


async def test_build_writes_secret_before_yaml_and_migrates_plaintext(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_secret_test")
    runner = JobRunner(hass, storage, device_manager, publisher)
    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )
    old_slug = dev.slug
    mock_builder.configs["livingroom.yaml"] = (
        "esphome:\n  name: livingroom\nesp32:\n  board: esp32dev\n"
        f'packages:\n  esphome_ota:\n    substitutions:\n      ota_slug: "{old_slug}"\n'
    )
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)
        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url="https://ha.example"
        )
        await runner._active_tasks[job_id]
        assert runner.get_job(job_id).stage == STAGE_PUBLISHED
        await conn.disconnect()

    # Same slug value, now only in secrets; device YAML references it.
    assert dev.slug == old_slug
    assert mock_builder.secrets == {
        KEY: old_slug,
        BASE_URL_SECRET_KEY: "https://ha.example",
    }
    assert "ha.example" not in mock_builder.configs["livingroom.yaml"]
    final = mock_builder.configs["livingroom.yaml"]
    assert old_slug not in final
    assert f"ota_slug: !secret {KEY}" in final
    config_idx = mock_builder.write_log.index("config:livingroom.yaml")
    assert mock_builder.write_log.index(f"secret:{KEY}") < config_idx
    assert mock_builder.write_log.index(f"secret:{BASE_URL_SECRET_KEY}") < config_idx


async def _setup_rotation(hass, mock_config_entry, secret_form: bool):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    await manager.device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        target_platform="esp32",
        token="0123456789abcdef0123456789abcdef",
    )
    value = f"!secret {KEY}" if secret_form else f'"{SLUG}"'
    client = AsyncMock()
    client.get_config.return_value = (
        f"packages:\n  esphome_ota:\n    substitutions:\n      ota_slug: {value}\n"
    )
    manager.resolver.active_client = client
    return manager, client


async def _set_token(ws) -> dict:
    await ws.send_json(
        {
            "id": 1,
            "type": "esphome_ota/set_token",
            "device_id": "livingroom",
            "token": NEW_TOKEN,
        }
    )
    msg = await ws.receive_json()
    while msg.get("type") == "event":
        msg = await ws.receive_json()
    return msg


async def test_rotation_with_secret_updates_secrets_only(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        _manager, client = await _setup_rotation(hass, mock_config_entry, True)
        ws = await hass_ws_client(hass)
        msg = await _set_token(ws)
        assert msg["success"] is True, msg
        client.set_secret.assert_awaited_once_with(KEY, f"livingroom_{NEW_TOKEN}")
        client.update_config.assert_not_called()
        await ws.close()


async def test_rotation_failure_restores_secret(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, client = await _setup_rotation(hass, mock_config_entry, True)
        ws = await hass_ws_client(hass)
        with patch.object(
            manager.storage,
            "async_save_devices",
            AsyncMock(side_effect=[RuntimeError("disk full"), None]),
        ):
            msg = await _set_token(ws)
        assert msg["success"] is False
        assert msg["error"]["code"] == "token_update_failed"
        calls = [c.args for c in client.set_secret.await_args_list]
        assert calls == [
            (KEY, f"livingroom_{NEW_TOKEN}"),
            (KEY, "livingroom_0123456789abcdef0123456789abcdef"),
        ]
        await ws.close()


async def _setup_apply(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    dev = await manager.device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom.yaml",
        name="livingroom",
        friendly_name="Living Room",
        target_platform="esp32",
        token="0123456789abcdef0123456789abcdef",
    )
    client = AsyncMock()
    manager.resolver.active_client = client
    return manager, dev, client


async def _apply(ws, content: str) -> dict:
    await ws.send_json(
        {
            "id": 1,
            "type": "esphome_ota/apply_ota",
            "device_id": "livingroom",
            "content": content,
        }
    )
    msg = await ws.receive_json()
    while msg.get("type") == "event":
        msg = await ws.receive_json()
    return msg


async def test_apply_ota_writes_both_secrets(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, dev, client = await _setup_apply(hass, mock_config_entry)
        content = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            f"      ota_base_url: !secret {BASE_URL_SECRET_KEY}\n"
            f"      ota_slug: !secret {KEY}\n"
        )
        ws = await hass_ws_client(hass)
        msg = await _apply(ws, content)
        assert msg["success"] is True, msg
        calls = [c.args for c in client.set_secret.await_args_list]
        assert calls == [
            (BASE_URL_SECRET_KEY, manager.base_url.rstrip("/")),
            (KEY, dev.slug),
        ]
        client.update_config.assert_awaited_once()
        await ws.close()


async def test_apply_ota_refuses_foreign_base_url_secret(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        _manager, _dev, client = await _setup_apply(hass, mock_config_entry)
        content = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            "      ota_base_url: !secret some_other_key\n"
            f"      ota_slug: !secret {KEY}\n"
        )
        ws = await hass_ws_client(hass)
        msg = await _apply(ws, content)
        assert msg["success"] is False
        assert msg["error"]["code"] == "apply_failed"
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        await ws.close()


async def test_remove_keeps_shared_base_url_secret(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        _manager, _dev, client = await _setup_apply(hass, mock_config_entry)
        yaml_text = (
            "esphome:\n  name: livingroom\n"
            "packages:\n  esphome_ota:\n    substitutions:\n"
            f"      ota_base_url: !secret {BASE_URL_SECRET_KEY}\n"
            f"      ota_slug: !secret {KEY}\n"
        )
        client.get_config.return_value = yaml_text
        ws = await hass_ws_client(hass)
        await ws.send_json(
            {"id": 1, "type": "esphome_ota/remove_ota", "device_id": "livingroom"}
        )
        msg = await ws.receive_json()
        while msg.get("type") == "event":
            msg = await ws.receive_json()
        assert msg["success"] is True, msg
        client.update_config.assert_awaited_once()
        assert "!secret" not in client.update_config.await_args.args[1]
        client.remove_secret.assert_awaited_once_with(KEY)
        await ws.close()
