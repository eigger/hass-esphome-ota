"""Unit tests for ArtifactPublisher atomic publishing and deactivation."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.firmware import inspect_binary
from custom_components.esphome_ota.publisher import ArtifactPublisher


async def test_publish_atomic_and_manifest_last(hass: HomeAssistant) -> None:
    """Test publishing creates private artifact and public files with cache buster."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test")
    blob = (
        b"\xe9\x00\x00\x00"
        + b"\x00" * 8
        + b"\x00\x00"  # ESP32
        + b"\x00" * 5
        + b"\x00\x00\x00\x00\x00"
        + b"\x00" * 8
        + b"\x32\x54\xcd\xab"
        + b"\x00" * 12
        + b"2026.10.0".ljust(32, b"\x00")
        + b"\x00" * 1500
    )
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")

    artifact = await publisher.async_publish(
        device_id="livingroom",
        configuration="livingroom",
        slug="livingroom_token123",
        blob=blob,
        info=info,
        title="Living Room Sensor",
    )

    # 1. Private artifact exists
    assert Path(artifact.private_path).is_file()
    assert Path(artifact.private_path).read_bytes() == blob

    # 2. Public files exist
    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    assert pub_bin.is_file()
    assert pub_bin.read_bytes() == blob
    assert pub_md5.is_file()
    assert pub_md5.read_text(encoding="ascii") == info.md5
    assert pub_manifest.is_file()

    manifest_data = json.loads(pub_manifest.read_text(encoding="utf-8"))
    assert manifest_data["version"] == "1.0.0"
    assert manifest_data["builds"][0]["chipFamily"] == "ESP32"
    assert f"?v={info.md5[:8]}" in manifest_data["builds"][0]["ota"]["path"]


async def test_deactivate_removes_binary_keeps_manifest(hass: HomeAssistant) -> None:
    """Test deactivation hides public .bin and .md5 but keeps .json manifest."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test")
    blob = b"\xe9\x00\x00\x00" + b"\x00" * 2000
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")

    artifact = await publisher.async_publish(
        device_id="livingroom",
        configuration="livingroom",
        slug="livingroom_tok",
        blob=blob,
        info=info,
    )

    pub_bin = Path(artifact.public_bin_path)
    pub_md5 = pub_bin.with_suffix(".bin.md5")
    pub_manifest = Path(artifact.public_manifest_path)

    assert pub_bin.is_file()
    assert pub_md5.is_file()

    # Deactivate
    removed = await publisher.async_deactivate("livingroom_tok")
    assert removed is True
    assert not pub_bin.exists()
    assert not pub_md5.exists()
    assert pub_manifest.is_file()  # Manifest preserved!
    assert Path(artifact.private_path).is_file()  # Private artifact preserved!


async def test_republish_private_artifact(hass: HomeAssistant) -> None:
    """Test loading and republishing verified private artifact."""
    publisher = ArtifactPublisher(hass, publish_dir="esphome_ota_test")
    blob = b"\xe9\x00\x00\x00" + b"\x00" * 2000
    info = inspect_binary(blob, target_platform="esp32", reserved_version="1.0.0")

    artifact = await publisher.async_publish(
        device_id="livingroom",
        configuration="livingroom",
        slug="livingroom_tok",
        blob=blob,
        info=info,
    )

    # Deactivate
    await publisher.async_deactivate("livingroom_tok")
    assert not Path(artifact.public_bin_path).exists()

    # Load bytes from private storage
    loaded_blob = await publisher.async_load_private_artifact(artifact.private_path)
    assert loaded_blob == blob

    # Republish
    republished = await publisher.async_publish(
        device_id="livingroom",
        configuration="livingroom",
        slug="livingroom_tok",
        blob=loaded_blob,
        info=info,
    )
    assert Path(republished.public_bin_path).is_file()
