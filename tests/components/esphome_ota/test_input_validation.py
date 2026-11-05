"""Tests for input validation of WebSocket commands, YAML output and uploads."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import yaml
from aiohttp import FormData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.config_patch import set_package_ota_slug
from custom_components.esphome_ota.const import DOMAIN
from custom_components.esphome_ota.packages import (
    NODE_RE,
    TOKEN_RE,
    VERSION_RE,
    generate_inline_ota_yaml,
    is_valid_device_id,
    is_valid_token,
    yaml_dq,
)
from custom_components.esphome_ota.websocket import _www_path
from tests.components.esphome_ota.conftest import MockBuilderServer


def test_yaml_dq_escapes_special_characters() -> None:
    """Quotes, backslashes and newlines must not break out of the scalar."""
    assert yaml_dq("plain") == '"plain"'
    value = 'a"b\\c\nd'
    assert yaml.safe_load(f"k: {yaml_dq(value)}") == {"k": value}


def test_generated_yaml_escapes_slug_and_version() -> None:
    """Injected values stay inside their scalars in generated YAML."""
    text = generate_inline_ota_yaml(
        base_url="https://ha.example",
        slug='x"\nevil: 1',
        version='1"\nevil: 2',
        node="node",
    )
    data = yaml.safe_load("packages:\n" + text)["packages"]["esphome_ota"]
    assert data["substitutions"]["ota_slug"] == 'x"\nevil: 1'
    assert data["esphome"]["project"]["version"] == '1"\nevil: 2'
    assert "evil" not in data


def test_set_package_ota_slug_escapes_value() -> None:
    """ota_slug rewrite quotes the new value."""
    out, changed = set_package_ota_slug('ota_slug: "a"\n', 'b"\nx: y')
    assert changed
    assert yaml.safe_load(out) == {"ota_slug": 'b"\nx: y'}


@pytest.mark.parametrize(
    "value", ["c0ffee00c0ffee00c0ffee00c0ffee00", "a" * 32, "0" * 64]
)
def test_token_re_accepts(value: str) -> None:
    assert TOKEN_RE.match(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "abc-123",
        "custom_tok_123",
        "a" * 31,
        "A" * 32,
        "g" * 32,
        "a" * 65,
        "a/b",
        "../x",
        "a b",
        "a\n",
        "é",
    ],
)
def test_token_re_rejects(value: str) -> None:
    assert not TOKEN_RE.match(value)


def test_version_and_node_re() -> None:
    assert VERSION_RE.match("1.0.0")
    assert VERSION_RE.match("2024.1.0-beta+1")
    assert VERSION_RE.match("1.0 (build 2)")
    assert not VERSION_RE.match('1"\n')
    assert not VERSION_RE.match("1\\0")
    assert not VERSION_RE.match("")
    assert NODE_RE.match("living-room_1")
    assert not NODE_RE.match("../etc")


def test_device_id_validation() -> None:
    assert is_valid_device_id("living room(1)")
    assert is_valid_device_id("sensor+é")
    for bad in (
        ".",
        "...",
        ".yaml".removesuffix(".yaml"),
        "",
        "a/b",
        "a\\b",
        "..",
        "a..b",
        "a\x00",
        "a\n",
    ):
        assert not is_valid_device_id(bad)


def test_www_path_rejects_escape(tmp_path) -> None:
    assert _www_path(tmp_path, "a.ota.bin") == tmp_path / "a.ota.bin"
    for bad in ("../x", "a/b", "/etc/passwd", "..", ""):
        with pytest.raises(ValueError):
            _www_path(tmp_path, bad)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0].runtime_data


async def test_ws_rejects_invalid_input(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Schema rejects malformed token, version and device IDs."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        await _setup(hass, mock_config_entry)
        ws = await hass_ws_client(hass)
        bad = [
            {"type": "esphome_ota/set_token", "device_id": "a", "token": "x/../y"},
            {"type": "esphome_ota/set_token", "device_id": "../a", "token": "ok"},
            {"type": "esphome_ota/build", "device_id": "a", "target_version": '1"\nx'},
            {"type": "esphome_ota/build", "device_id": "a", "target_version": ""},
            {"type": "esphome_ota/build", "device_id": "a/b"},
            {"type": "esphome_ota/batch_build", "device_ids": ["ok", "../x"]},
        ]
        for i, payload in enumerate(bad, start=1):
            await ws.send_json({"id": i, **payload})
            msg = await ws.receive_json()
            assert msg["success"] is False, payload
            assert msg["error"]["code"] == "invalid_format", payload
        await ws.close()


async def test_build_and_prepare_reject_unknown_device(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Devices absent from the Builder are never registered."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager = await _setup(hass, mock_config_entry)
        manager.resolver.active_client = AsyncMock()
        manager.job_runner.async_start_build_pipeline = AsyncMock(return_value="job")
        ws = await hass_ws_client(hass)

        for i, payload in enumerate(
            [
                {"type": "esphome_ota/build", "device_id": "ghost"},
                {"type": "esphome_ota/prepare_ota", "device_id": "ghost"},
            ],
            start=1,
        ):
            await ws.send_json({"id": i, **payload})
            msg = await ws.receive_json()
            assert msg["success"] is False
            assert msg["error"]["code"] == "device_not_found"

        await ws.send_json(
            {"id": 3, "type": "esphome_ota/batch_build", "device_ids": ["ghost"]}
        )
        msg = await ws.receive_json()
        assert msg["success"] is True
        assert msg["result"] == {"jobs": {}}

        assert manager.device_manager.get_device("ghost") is None
        manager.job_runner.async_start_build_pipeline.assert_not_called()
        await ws.close()


async def test_upload_rejects_non_multipart_and_wrong_field(
    hass: HomeAssistant,
    hass_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Upload returns 400 instead of 500 for malformed requests."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        await _setup(hass, mock_config_entry)
        client = await hass_client()

        resp = await client.post(
            "/api/esphome_ota/upload/livingroom",
            data=b"raw",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert resp.status == 400

        form = FormData()
        form.add_field("other", b"x" * 2048, filename="f.bin")
        resp = await client.post("/api/esphome_ota/upload/livingroom", data=form)
        assert resp.status == 400

        # Broken multipart boundary
        resp = await client.post(
            "/api/esphome_ota/upload/livingroom",
            data=b"--nope\r\ngarbage",
            headers={"Content-Type": "multipart/form-data; boundary=real"},
        )
        assert resp.status == 400

        # Invalid device ID
        form = FormData()
        form.add_field("file", b"x" * 2048, filename="f.bin")
        resp = await client.post("/api/esphome_ota/upload/a..b", data=form)
        assert resp.status == 400


async def test_builder_only_device_is_auto_registered(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """Devices known to the Builder are still registered by build/batch_build."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager = await _setup(hass, mock_config_entry)
        manager.resolver.active_client = AsyncMock()
        manager.device_manager.update_builder_devices(
            [
                {"configuration": "kitchen.yaml", "name": "kitchen"},
                {"configuration": "hall.yaml", "name": "hall"},
                {"configuration": "bad.yaml", "name": "bad name!"},
            ]
        )
        manager.job_runner.async_start_build_pipeline = AsyncMock(return_value="job")
        ws = await hass_ws_client(hass)

        await ws.send_json(
            {"id": 1, "type": "esphome_ota/build", "device_id": "kitchen"}
        )
        msg = await ws.receive_json()
        assert msg["success"] is True
        assert manager.device_manager.get_device("kitchen") is not None

        await ws.send_json(
            {
                "id": 2,
                "type": "esphome_ota/batch_build",
                "device_ids": ["hall", "bad"],
            }
        )
        msg = await ws.receive_json()
        assert msg["result"] == {"jobs": {"hall": "job"}}
        assert manager.device_manager.get_device("bad") is None
        await ws.close()


async def test_set_token_empty_reverts_slug_and_invalid_name(
    hass: HomeAssistant,
    hass_ws_client: any,
    mock_config_entry: MockConfigEntry,
    mock_builder: MockBuilderServer,
) -> None:
    """An empty token generates a random one; invalid builder names yield invalid_name."""
    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[],
    ):
        manager = await _setup(hass, mock_config_entry)
        await manager.device_manager.async_register_or_update(
            device_id="esp-tab",
            configuration="esp-tab.yaml",
            name="esp-tab",
            friendly_name="ESP Tab",
            token="0123456789abcdef0123456789abcdef",
        )
        manager.device_manager.update_builder_devices(
            [{"configuration": "weird.yaml", "name": "we ird"}]
        )
        manager.resolver.active_client = None
        ws = await hass_ws_client(hass)

        await ws.send_json(
            {
                "id": 1,
                "type": "esphome_ota/set_token",
                "device_id": "weird",
                "token": "a" * 32,
            }
        )
        msg = await ws.receive_json()
        assert msg["success"] is False
        assert msg["error"]["code"] == "invalid_name"

        await ws.send_json(
            {
                "id": 2,
                "type": "esphome_ota/set_token",
                "device_id": "esp-tab",
                "token": "",
            }
        )
        msg = await ws.receive_json()
        assert msg["success"] is True, msg
        dev = manager.device_manager.get_device("esp-tab")
        assert is_valid_token(dev.token)
        assert dev.token != "0123456789abcdef0123456789abcdef"
        assert dev.slug == f"esp-tab_{dev.token}"
        assert msg["result"]["token"] == dev.token

        # A weak token is rejected by the schema.
        await ws.send_json(
            {
                "id": 3,
                "type": "esphome_ota/set_token",
                "device_id": "esp-tab",
                "token": "short",
            }
        )
        msg = await ws.receive_json()
        assert msg["success"] is False
        assert msg["error"]["code"] == "invalid_format"
        await ws.close()


def test_format_yaml_scalar_quotes_non_string_scalars() -> None:
    from custom_components.esphome_ota.config_patch import _format_yaml_scalar

    for v in ("~", "-1", "null", "true", ".inf", "0x10"):
        out = _format_yaml_scalar(v)
        assert out == f'"{v}"'
        assert yaml.safe_load(out) == v
    assert _format_yaml_scalar("beta") == "beta"
