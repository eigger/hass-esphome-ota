"""Tests for storing the public slug in secrets.yaml instead of device YAML."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
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
from custom_components.esphome_ota.models import BuilderError, BuilderTimeoutError
from custom_components.esphome_ota.packages import (
    BASE_URL_SECRET_KEY,
    LEGACY_SLUG_SECRET_PREFIX,
    find_slug_key_conflict,
    generate_inline_ota_yaml,
    legacy_slug_secret_key,
    slug_secret_key,
)
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager
from tests.components.esphome_ota.conftest import MockBuilderServer

SLUG = "livingroom_0123456789abcdef0123456789abcdef"
KEY = "esphome_ota_cfg_livingroom"
NEW_TOKEN = "fedcba9876543210fedcba9876543210"


def test_slug_secret_key_naming() -> None:
    assert slug_secret_key("livingroom") == KEY
    assert slug_secret_key("bed_room2") == "esphome_ota_cfg_bed_room2"
    hyphen = slug_secret_key("esp-tab")
    assert re.fullmatch(r"esphome_ota_cfg_esp_tab_[0-9a-f]{6}", hyphen)
    # Lossy mappings never collide.
    assert slug_secret_key("esp_tab") != hyphen
    assert slug_secret_key("Esp-Tab") != hyphen
    assert re.fullmatch(r"[a-z0-9_]+", slug_secret_key("Odd.Name-1"))
    assert slug_secret_key("esp-tab") == hyphen  # deterministic


def test_generate_block_emits_secret_reference() -> None:
    text = generate_inline_ota_yaml("http://ha", SLUG, slug_secret=KEY)
    assert f"ota_slug: !secret {KEY}" in text
    assert SLUG not in text


def test_apply_patch_migrates_plaintext_to_secret() -> None:
    src = (
        "esphome:\n  name: livingroom\npackages:\n  esphome_ota:\n"
        f'    substitutions:\n      ota_slug: "{SLUG}"\n'
    )
    res = apply_ota_patch(
        src, "http://ha", SLUG, node="livingroom", device_id="livingroom"
    )
    assert SLUG not in res.modified
    assert ota_slug_secret_ref(res.modified) == KEY


def test_apply_patch_emits_both_secrets_and_migrates_plaintext_base_url() -> None:
    src = (
        "esphome:\n  name: livingroom\npackages:\n  esphome_ota:\n"
        '    substitutions:\n      ota_base_url: "http://ha.local:8123"\n'
        f'      ota_slug: "{SLUG}"\n'
    )
    res = apply_ota_patch(
        src, "http://ha.local:8123/", SLUG, node="livingroom", device_id="livingroom"
    )
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


def _logging_conn(set_secret_error: BuilderError | None):
    conn = AsyncMock()
    log: list[str] = []

    async def command(name, args=None):
        log.append(name)
        if name == "config/set_secret":
            if set_secret_error:
                raise set_secret_error
            return {"created": True}
        raise AssertionError(f"unexpected command {name}")

    conn.command.side_effect = command
    conn.server_info = {}
    return conn, log


async def test_client_set_secret_unsupported_never_falls_back() -> None:
    conn, log = _logging_conn(BuilderError("nope", error_code="UNKNOWN_COMMAND"))
    with pytest.raises(BuilderError, match="does not support config/set_secret"):
        await BuilderClient(conn).set_secret(KEY, SLUG)
    assert log == ["config/set_secret"]


@pytest.mark.parametrize("code", ["PERMISSION_DENIED", "INVALID_ARGS", None])
async def test_client_set_secret_error_writes_nothing_else(code) -> None:
    conn, log = _logging_conn(BuilderError("denied", error_code=code))
    with pytest.raises(BuilderError):
        await BuilderClient(conn).set_secret(KEY, SLUG)
    assert log == ["config/set_secret"]


async def test_client_set_secret_ok_single_command() -> None:
    conn, log = _logging_conn(None)
    await BuilderClient(conn).set_secret(KEY, SLUG)
    assert log == ["config/set_secret"]
    assert conn.command.await_args.args[1]["key"] == KEY


@pytest.mark.parametrize(
    "name",
    [
        "secrets.yaml",
        "secrets.yml",
        "Secrets.YAML",
        "SECRETS.yml",
        "secrets",
        "sub/secrets.yaml",
    ],
)
async def test_client_refuses_whole_file_secrets_access(name) -> None:
    conn = AsyncMock()
    conn.server_info = {}
    client = BuilderClient(conn)
    with pytest.raises(BuilderError):
        await client.update_config(name, "a: 1")
    with pytest.raises(BuilderError):
        await client.update_config(name, "", expected="x")
    with pytest.raises(BuilderError):
        await client.get_config(name)
    conn.command.assert_not_called()


def test_client_has_no_whole_file_secret_helpers() -> None:
    assert not hasattr(BuilderClient, "remove_secret")
    assert not hasattr(BuilderClient, "_read_secrets_text")


def test_slug_key_is_per_device_id_not_name() -> None:
    assert slug_secret_key("kitchen_a") != slug_secret_key("kitchen_b")
    assert find_slug_key_conflict("a-b", ["a-b", "a_b", "x"]) is None
    assert find_slug_key_conflict("a", ["a", "a"]) is None


def test_same_esphome_name_gets_distinct_keys_in_yaml() -> None:
    src = "esphome:" + chr(10) + "  name: kitchen" + chr(10)
    one = apply_ota_patch(src, "http://ha", SLUG, node="kitchen", device_id="k1")
    two = apply_ota_patch(src, "http://ha", SLUG, node="kitchen", device_id="k2")
    assert ota_slug_secret_ref(one.modified) == "esphome_ota_cfg_k1"
    assert ota_slug_secret_ref(two.modified) == "esphome_ota_cfg_k2"


def test_apply_patch_without_device_id_inlines_slug() -> None:
    res = apply_ota_patch(
        "esphome:" + chr(10) + "  name: a" + chr(10), "http://ha", SLUG, node="a"
    )
    assert ota_slug_secret_ref(res.modified) is None


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
        client.set_secret.assert_not_called()
        assert [c[0] for c in client.method_calls if "secret" in c[0]] == []
        await ws.close()


# ---------------------------------------------------------------------------
# Actionable error messages: failed job detail and WS error text
# ---------------------------------------------------------------------------


async def _run_build(hass, mock_builder, base_url="https://ha.example", patch_ctx=None):
    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_msg_test")
    runner = JobRunner(hass, storage, device_manager, publisher)
    dev = await device_manager.async_register_or_update(
        device_id="livingroom",
        configuration="livingroom",
        name="livingroom",
        friendly_name="Living Room",
    )
    async with aiohttp.ClientSession() as session:
        conn = BuilderConnection("127.0.0.1", mock_builder.port, session)
        await conn.connect()
        client = BuilderClient(conn)
        job_id = await runner.async_start_build_pipeline(
            device=dev, client=client, base_url=base_url
        )
        await runner._active_tasks[job_id]
        job = runner.get_job(job_id)
        await conn.disconnect()
    return job


async def test_job_fails_clearly_when_set_secret_unsupported(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    mock_builder.set_secret_error = "UNKNOWN_COMMAND"
    job = await _run_build(hass, mock_builder)
    assert job.stage == "failed"
    assert "does not support config/set_secret" in job.error
    assert "Update the ESPHome Builder" in job.error
    assert "Nothing was written" in job.error
    assert mock_builder.write_log == []
    assert mock_builder.secrets == {}


async def test_job_fails_with_builder_code_when_set_secret_refused(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    mock_builder.set_secret_error = "INVALID_ARGS"
    job = await _run_build(hass, mock_builder, base_url="https://ha.example")
    assert job.stage == "failed"
    assert "INVALID_ARGS" in job.error
    assert "esphome_ota_base_url" in job.error
    assert "ha.example" not in job.error
    assert mock_builder.write_log == []


@pytest.mark.parametrize("base_url", ["", "not a url", "ftp://ha"])
async def test_job_aborts_before_any_write_on_invalid_base_url(
    hass: HomeAssistant, mock_builder: MockBuilderServer, base_url
) -> None:
    job = await _run_build(hass, mock_builder, base_url=base_url)
    assert job.stage == "failed"
    assert "Base URL" in job.error
    assert "integration options" in job.error
    assert "Nothing was written" in job.error
    assert mock_builder.write_log == []
    assert mock_builder.secrets == {}


async def test_job_aborts_on_slug_key_collision_naming_both_configs(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    with patch(
        "custom_components.esphome_ota.devices.find_slug_key_conflict",
        return_value="livingroom2",
    ):
        job = await _run_build(hass, mock_builder)
    assert job.stage == "failed"
    assert "'livingroom.yaml'" in job.error
    assert "'livingroom2.yaml'" in job.error
    assert "Rename" in job.error
    assert mock_builder.write_log == []


@pytest.mark.parametrize("ref_key", ["some_other_key", "esphome_ota_slug_livingroom"])
async def test_rotation_with_foreign_or_legacy_key_writes_nothing(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
    ref_key,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        _manager, client = await _setup_rotation(hass, mock_config_entry, True)
        client.get_config.return_value = client.get_config.return_value.replace(
            KEY, ref_key
        )
        ws = await hass_ws_client(hass)
        msg = await _set_token(ws)
        assert msg["success"] is False
        assert msg["error"]["code"] == "token_update_failed"
        text = msg["error"]["message"]
        assert ref_key in text and KEY in text
        assert "Run a build" in text
        assert "Nothing was written" in text
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        await ws.close()


async def test_unmanaged_rotation_with_secret_writes_nothing(
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
        manager.device_manager.managed_devices.pop("livingroom")
        manager.device_manager._builder_devices = [
            {
                "name": "livingroom",
                "configuration": "livingroom.yaml",
                "target_platform": "esp32",
            }
        ]
        ws = await hass_ws_client(hass)
        msg = await _set_token(ws)
        assert msg["success"] is False
        text = msg["error"]["message"]
        assert "not managed" in text and "Nothing was written" in text
        assert "Build this device once" in text
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        await ws.close()


async def test_apply_ota_empty_base_url_reports_options_hint(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, _dev, client = await _setup_apply(hass, mock_config_entry)
        manager.base_url = ""
        content = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            f"      ota_base_url: !secret {BASE_URL_SECRET_KEY}\n"
            f"      ota_slug: !secret {KEY}\n"
        )
        ws = await hass_ws_client(hass)
        msg = await _apply(ws, content)
        assert msg["success"] is False
        assert msg["error"]["code"] == "apply_failed"
        assert "integration options" in msg["error"]["message"]
        assert "Nothing was written" in msg["error"]["message"]
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        await ws.close()


async def test_guard_message_is_explicit() -> None:
    conn = AsyncMock()
    conn.server_info = {}
    with pytest.raises(BuilderError, match="Nothing was written"):
        await BuilderClient(conn).update_config("secrets.yaml", "x")


# ---------------------------------------------------------------------------
# Review round 2: key namespace, rollback, locking, redaction, scoping
# ---------------------------------------------------------------------------


def test_new_keys_are_disjoint_from_legacy_name_keys() -> None:
    assert not slug_secret_key("x").startswith(LEGACY_SLUG_SECRET_PREFIX)
    samples = ["kitchen", "id_kitchen", "cfg_kitchen", "a-b", "Odd.Name", "x_1"]
    for stem in samples:
        for name in samples:
            assert slug_secret_key(stem) != legacy_slug_secret_key(name)
    assert slug_secret_key("kitchen") != BASE_URL_SECRET_KEY


async def test_stem_of_one_device_equals_name_of_another(
    hass: HomeAssistant,
) -> None:
    """kitchen.yaml (name kitchen-sensor) vs sensor2.yaml (name kitchen)."""
    dm = DeviceManager(hass, StorageManager(hass))
    await dm.async_register_or_update(
        device_id="kitchen",
        configuration="kitchen.yaml",
        name="kitchen-sensor",
        friendly_name="A",
    )
    await dm.async_register_or_update(
        device_id="sensor2",
        configuration="sensor2.yaml",
        name="kitchen",
        friendly_name="B",
    )
    dm.assert_slug_key_unique("kitchen")
    dm.assert_slug_key_unique("sensor2")
    assert slug_secret_key("kitchen") != legacy_slug_secret_key("kitchen")


async def test_guard_rejects_equal_legacy_key_defense_in_depth(
    hass: HomeAssistant,
) -> None:
    dm = DeviceManager(hass, StorageManager(hass))
    await dm.async_register_or_update(
        device_id="sensor2",
        configuration="sensor2.yaml",
        name="kitchen",
        friendly_name="B",
    )
    with patch(
        "custom_components.esphome_ota.packages.SLUG_SECRET_PREFIX",
        LEGACY_SLUG_SECRET_PREFIX,
    ):
        with pytest.raises(BuilderError, match="sensor2.yaml"):
            dm.assert_slug_key_unique("kitchen")


async def test_guard_real_lossy_collision_managed_vs_builder_list(
    hass: HomeAssistant,
) -> None:
    digest = hashlib.sha1(b"a-b").hexdigest()[:6]
    twin = f"a_b_{digest}"
    assert slug_secret_key("a-b") == slug_secret_key(twin)
    dm = DeviceManager(hass, StorageManager(hass))
    dm.update_builder_devices([{"configuration": f"{twin}.yaml", "name": "twin"}])
    await dm.async_register_or_update(
        device_id="a-b",
        configuration="a-b.yaml",
        name="a-b",
        friendly_name="A",
    )
    with pytest.raises(BuilderError) as exc:
        dm.assert_slug_key_unique("a-b")
    assert "'a-b.yaml'" in str(exc.value)
    assert f"'{twin}.yaml'" in str(exc.value)
    assert exc.value.error_code == "SLUG_KEY_COLLISION"


async def test_guard_real_collision_between_two_managed_devices(
    hass: HomeAssistant,
) -> None:
    twin = f"a_b_{hashlib.sha1(b'a-b').hexdigest()[:6]}"
    dm = DeviceManager(hass, StorageManager(hass))
    for dev_id in ("a-b", twin):
        await dm.async_register_or_update(
            device_id=dev_id,
            configuration=f"{dev_id}.yaml",
            name="same",
            friendly_name=dev_id,
        )
    with pytest.raises(BuilderError, match="same secrets.yaml key"):
        dm.assert_slug_key_unique(twin)


@pytest.mark.parametrize(
    "name",
    [
        "secrets.yaml.",
        "secrets.yaml/",
        " secrets.yaml ",
        "./secrets.yml/",
        "a/Secrets.YAML.",
    ],
)
async def test_client_refuses_secrets_name_variants(name) -> None:
    conn = AsyncMock()
    conn.server_info = {}
    with pytest.raises(BuilderError):
        await BuilderClient(conn).update_config(name, "x")
    conn.command.assert_not_called()


async def test_set_secret_error_never_surfaces_builder_details(caplog) -> None:
    conn = AsyncMock()
    conn.server_info = {}
    conn.command.side_effect = BuilderError(
        "duplicate key near 'wifi_password: hunter2-fake'", error_code="INVALID_ARGS"
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(BuilderError) as exc:
            await BuilderClient(conn).set_secret(KEY, SLUG)
    assert "hunter2-fake" not in str(exc.value)
    assert "INVALID_ARGS" in str(exc.value)
    assert "This secret was not changed" in str(exc.value)
    assert not [
        r
        for r in caplog.records
        if r.levelno >= logging.INFO and "hunter2-fake" in r.getMessage()
    ]


def test_secret_refs_are_scoped_to_managed_block() -> None:
    src = (
        "substitutions:\n  ota_slug: !secret mine\n  ota_base_url: !secret mine2\n"
        "packages:\n  other:\n    x: 1\n  esphome_ota:\n    substitutions:\n"
        f"      ota_base_url: !secret {BASE_URL_SECRET_KEY}\n"
        f"      ota_slug: !secret {KEY}\n"
        "logger:\n  # ota_slug: !secret nope\n"
    )
    assert ota_slug_secret_ref(src) == KEY
    assert ota_base_url_secret_ref(src) == BASE_URL_SECRET_KEY
    only_user = "substitutions:\n  ota_slug: !secret mine\npackages:\n  a:\n    b: 1\n"
    assert ota_slug_secret_ref(only_user) is None
    assert ota_base_url_secret_ref(only_user) is None


async def test_build_ignores_users_own_top_level_secret_substitution(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    mock_builder.configs["livingroom.yaml"] = (
        "esphome:\n  name: livingroom\nesp32:\n  board: esp32dev\n"
        "substitutions:\n  ota_slug: !secret mine\n"
    )
    job = await _run_build(hass, mock_builder)
    assert job.stage != "failed", job.error
    assert KEY in mock_builder.secrets


async def test_rotation_forward_timeout_rolls_back_to_old_slug(
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
        client.set_secret.side_effect = [BuilderTimeoutError("timed out"), None]
        ws = await hass_ws_client(hass)
        msg = await _set_token(ws)
        assert msg["success"] is False
        calls = [c.args for c in client.set_secret.await_args_list]
        assert calls == [
            (KEY, f"livingroom_{NEW_TOKEN}"),
            (KEY, "livingroom_0123456789abcdef0123456789abcdef"),
        ]
        await ws.close()


async def test_rotation_rollback_failure_tells_user_to_rebuild(
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
        client.set_secret.side_effect = [
            BuilderTimeoutError("timed out"),
            BuilderTimeoutError("still down"),
        ]
        ws = await hass_ws_client(hass)
        msg = await _set_token(ws)
        assert msg["success"] is False
        text = msg["error"]["message"]
        assert "rollback also failed" in text
        assert "may not match this device" in text
        assert "Run a build" in text
        await ws.close()


async def test_apply_ota_waits_for_device_lock(
    hass: HomeAssistant,
    hass_ws_client,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager, _dev, client = await _setup_apply(hass, mock_config_entry)
        content = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            f"      ota_base_url: !secret {BASE_URL_SECRET_KEY}\n"
            f"      ota_slug: !secret {KEY}\n"
        )
        lock = manager.device_manager.get_lock("livingroom")
        await lock.acquire()
        ws = await hass_ws_client(hass)
        await ws.send_json(
            {
                "id": 1,
                "type": "esphome_ota/apply_ota",
                "device_id": "livingroom",
                "content": content,
            }
        )
        await asyncio.sleep(0.3)
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        lock.release()
        msg = await ws.receive_json()
        while msg.get("type") == "event":
            msg = await ws.receive_json()
        assert msg["success"] is True, msg
        assert client.set_secret.await_count == 2
        await ws.close()


async def test_apply_ota_refuses_other_devices_key_and_unknown_device(
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
        ws = await hass_ws_client(hass)
        other = (
            "packages:\n  esphome_ota:\n    substitutions:\n"
            f"      ota_slug: !secret {slug_secret_key('bedroom')}\n"
        )
        msg = await _apply(ws, other)
        assert msg["success"] is False
        assert "Nothing was written" in msg["error"]["message"]
        own = other.replace(slug_secret_key("bedroom"), KEY)
        await ws.send_json(
            {
                "id": 2,
                "type": "esphome_ota/apply_ota",
                "device_id": "ghost",
                "content": own,
            }
        )
        msg = await ws.receive_json()
        while msg.get("type") == "event":
            msg = await ws.receive_json()
        assert msg["success"] is False
        client.set_secret.assert_not_called()
        client.update_config.assert_not_called()
        await ws.close()
