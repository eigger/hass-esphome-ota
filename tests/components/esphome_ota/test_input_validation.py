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
    yaml_dq,
)
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


@pytest.mark.parametrize("value", ["abc-123", "custom_tok_123", "A" * 32])
def test_token_re_accepts(value: str) -> None:
    assert TOKEN_RE.match(value)


@pytest.mark.parametrize("value", ["", "a/b", "../x", "a b", "a\n", "é"])
def test_token_re_rejects(value: str) -> None:
    assert not TOKEN_RE.match(value)


def test_version_and_node_re() -> None:
    assert VERSION_RE.match("1.0.0")
    assert VERSION_RE.match("2024.1.0-beta+1")
    assert not VERSION_RE.match('1"\n')
    assert NODE_RE.match("living-room_1")
    assert not NODE_RE.match("../etc")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN]["manager"]


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
            {"type": "esphome_ota/set_token", "device_id": "a", "token": ""},
            {"type": "esphome_ota/set_token", "device_id": "../a", "token": "ok"},
            {"type": "esphome_ota/build", "device_id": "a", "target_version": '1"\nx'},
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
