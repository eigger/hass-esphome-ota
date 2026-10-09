"""Regression tests for issues reported in commit 3050dea review.

Issues covered:
1. [P1] publisher.py: Cancellation during file replacement restores prior valid files
   and does not leave cancelled firmware in public directory.
2. [P2] manager.py: Builder change / unload during reconnection does not reopen
   connections on unloaded manager or create duplicate connections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import (
    CONF_BASE_URL,
    CONF_BUILDER_SLUG,
    DOMAIN,
    STATUS_READY,
)
from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.manager import OtaManager
from custom_components.esphome_ota.models import BuilderCandidate, EsphomeOtaError
from custom_components.esphome_ota.publisher import ArtifactPublisher

from .conftest import MockBuilderServer


def _make_valid_esp32_bin(version: str) -> bytes:
    """Create a minimal binary valid for ESP32 inspection."""
    header = b"\xe9\x00\x00\x00" + b"\x00" * 8 + b"\x00\x00" + b"\x00" * 18
    app_desc_magic = b"\x32\x54\xcd\xab"
    secure_ver = b"\x00" * 4
    reserved1 = b"\x00" * 8
    ver_bytes = version.encode("ascii").ljust(32, b"\x00")[:32]
    proj_bytes = b"livingroom".ljust(32, b"\x00")
    time_bytes = b"12:00:00".ljust(16, b"\x00")
    date_bytes = b"Oct 10 2026".ljust(16, b"\x00")
    idf_bytes = b"v5.1.2".ljust(32, b"\x00")
    elf_sha = b"\x00" * 32
    reserved2 = b"\x00" * 80

    app_desc = (
        app_desc_magic
        + secure_ver
        + reserved1
        + ver_bytes
        + proj_bytes
        + time_bytes
        + date_bytes
        + idf_bytes
        + elf_sha
        + reserved2
    )

    padding = b"\x00" * (0x20 - len(header))
    body = b"\x00" * 1024
    return header + padding + app_desc + body


async def test_publish_cancellation_during_replacement_restores_prior_files(
    hass: HomeAssistant,
) -> None:
    """[P1] Test that cancellation after binary replacement restores prior valid files and does not commit manifest."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_rollback_test")

    old_blob = _make_valid_esp32_bin("1.0.0")
    old_info = inspect_binary(old_blob, target_platform="esp32", reserved_version="1.0.0")
    artifact = await publisher.async_publish(
        device_id="dev_rollback",
        configuration="dev_rollback.yaml",
        slug="dev_rollback_slug",
        blob=old_blob,
        info=old_info,
    )

    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    new_blob = _make_valid_esp32_bin("2.0.0")
    new_info = inspect_binary(new_blob, target_platform="esp32", reserved_version="2.0.0")

    # Simulate cancellation right after binary replacement, before manifest replacement
    call_count = 0

    def check_cancel_mid_replace() -> bool:
        nonlocal call_count
        call_count += 1
        # Pre-replace checks return False; check right before manifest returns True
        return call_count >= 2

    with pytest.raises(EsphomeOtaError, match="Publish aborted"):
        await publisher.async_publish(
            device_id="dev_rollback",
            configuration="dev_rollback.yaml",
            slug="dev_rollback_slug",
            blob=new_blob,
            info=new_info,
            check_cancelled=check_cancel_mid_replace,
        )

    # Manifest was NOT replaced to 2.0.0
    manifest_data = json.loads(pub_manifest.read_text(encoding="utf-8"))
    assert manifest_data["version"] == "1.0.0"

    # Binary and MD5 were restored to old_blob
    assert pub_bin.read_bytes() == old_blob
    assert pub_md5.read_text(encoding="ascii") == old_info.md5

    # No stray stage or backup files left
    assert len(list(publisher.www_dir.glob("*.stage_*"))) == 0
    assert len(list(publisher.www_dir.glob("*.bak_*"))) == 0


async def test_publish_cancellation_with_no_prior_files_cleans_up(
    hass: HomeAssistant,
) -> None:
    """[P1] Test that cancellation during replacement with no prior files unlinks partial files."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_clean_test")

    blob = _make_valid_esp32_bin("1.0.0")
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")

    call_count = 0

    def check_cancel_mid_replace() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    with pytest.raises(EsphomeOtaError, match="Publish aborted"):
        await publisher.async_publish(
            device_id="dev_first_pub",
            configuration="dev_first_pub.yaml",
            slug="dev_first_pub_slug",
            blob=blob,
            info=info,
            check_cancelled=check_cancel_mid_replace,
        )

    pub_bin = publisher.www_dir / "dev_first_pub_slug.bin"
    pub_md5 = publisher.www_dir / "dev_first_pub_slug.bin.md5"
    pub_manifest = publisher.www_dir / "dev_first_pub_slug.json"

    assert not pub_bin.exists()
    assert not pub_md5.exists()
    assert not pub_manifest.exists()
    assert len(list(publisher.www_dir.glob("*.stage_*"))) == 0
    assert len(list(publisher.www_dir.glob("*.bak_*"))) == 0


async def test_manager_unloaded_during_reconnect_does_not_reopen_connection(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """[P2] Test that when manager is unloaded during reconnection, it aborts without opening a new connection."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ESPHome OTA",
        data={CONF_BASE_URL: "http://127.0.0.1:8123"},
        options={CONF_BUILDER_SLUG: "cand_1"},
    )
    entry.add_to_hass(hass)

    cand = BuilderCandidate(
        slug="cand_1",
        name="Candidate 1",
        host="127.0.0.1",
        port=mock_builder.port,
        source="ingress",
        is_running=True,
    )

    manager = OtaManager(hass, entry)
    manager.resolver.candidates = [cand]

    with patch.object(
        manager.resolver.discovery_adapter,
        "async_discover_all",
        return_value=[cand],
    ):
        await manager.async_setup()
        assert manager.resolver.status == STATUS_READY

        # Simulate unload triggering while reconnect is in-flight:
        # hook into async_disconnect to trigger manager.async_unload()
        original_disconnect = manager.resolver.async_disconnect
        unloaded = False

        async def disconnect_and_unload() -> None:
            nonlocal unloaded
            await original_disconnect()
            if not unloaded:
                unloaded = True
                await manager.async_unload()

        with patch.object(manager.resolver, "async_disconnect", side_effect=disconnect_and_unload):
            await manager.async_reconnect()

        # Manager is unloaded, active_client is None, and it did not reopen a connection
        assert manager._unloaded is True
        assert manager.resolver.active_client is None


async def test_manager_select_builder_suppresses_automatic_entry_reload(
    hass: HomeAssistant,
    hass_ws_client: Any,
    mock_builder: MockBuilderServer,
) -> None:
    """[P2] Test that selecting builder updates entry options/data without triggering duplicate reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_BASE_URL: "https://ha.local"},
        options={},
    )
    entry.add_to_hass(hass)

    cand1 = BuilderCandidate(
        slug="c1",
        name="Candidate 1",
        host="127.0.0.1",
        port=9999,
        source="supervisor_addon",
    )
    cand2 = BuilderCandidate(
        slug="c2",
        name="Candidate 2",
        host="127.0.0.1",
        port=mock_builder.port,
        source="supervisor_addon",
        is_running=True,
    )

    with patch(
        "custom_components.esphome_ota.builder.resolver.HaDiscoveryAdapter.async_discover_all",
        return_value=[cand1, cand2],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        manager: OtaManager = hass.data[DOMAIN]["manager"]

        client = await hass_ws_client(hass)
        await client.send_json(
            {
                "id": 1,
                "type": "esphome_ota/select_builder",
                "slug": "c2",
            }
        )
        resp = await client.receive_json()
        assert resp["success"] is True
        assert resp["result"]["status"] == STATUS_READY

        # Check that original manager is still the active manager and was NOT unloaded
        assert hass.data[DOMAIN]["manager"] is manager
        assert manager._unloaded is False
        assert manager.resolver.status == STATUS_READY
        assert manager.resolver.active_candidate is not None
        assert manager.resolver.active_candidate.slug == "c2"

        # Check entry data and options were both updated
        assert entry.data[CONF_BUILDER_SLUG] == "c2"
        assert entry.options[CONF_BUILDER_SLUG] == "c2"

        await client.close()
        await hass.config_entries.async_unload(entry.entry_id)
