"""Unit and regression tests for firmware analysis, app descriptor parsing, and validation."""

from __future__ import annotations

import struct
import pytest

from custom_components.esphome_ota.firmware import (
    ESP_APP_DESC_MAGIC,
    ESP_IMAGE_MAGIC,
    _parse_build_datetime,
    chip_family,
    chip_family_from_binary,
    inspect_binary,
    parse_app_descriptor,
)
from custom_components.esphome_ota.models import BinaryValidationError


def _make_synth_blob(
    chip_id: int = 0x00,
    version: str = "2026.10.0",
    project: str = "my_node",
    time_str: str = "17:04:29",
    date_str: str = "Aug 18 2026",
    idf: str = "v5.1.2",
    tail: bytes = b"",
) -> bytes:
    """Build a synthetic ESP32 firmware binary image."""
    blob = bytearray(0xC0)
    blob[0] = ESP_IMAGE_MAGIC
    # Chip ID at 12:14
    struct.pack_into("<H", blob, 12, chip_id)
    # Header guard fields
    blob[19] = blob[20] = blob[21] = blob[22] = 0
    blob[23] = 0

    # Write esp_app_desc_t magic at 0x20
    struct.pack_into("<I", blob, 0x20, ESP_APP_DESC_MAGIC)

    def write_str(offset: int, s: str, size: int) -> None:
        b = s.encode("utf-8")[:size]
        blob[offset : offset + len(b)] = b

    write_str(0x30, version, 32)
    write_str(0x50, project, 32)
    write_str(0x70, time_str, 16)
    write_str(0x80, date_str, 16)
    write_str(0x90, idf, 32)

    return bytes(blob) + tail + (b"\x00" * 1024)


def test_build_datetime_parsing() -> None:
    """Test date parsing with various formats and edge cases."""
    assert _parse_build_datetime("Aug 18 2026", "17:04:29") == "2026-08-18T17:04:29"
    # Space-padded day
    assert _parse_build_datetime("Aug  8 2026", "07:04:09") == "2026-08-08T07:04:09"
    # Invalid dates
    assert _parse_build_datetime("invalid date", "12:00:00") is None
    assert _parse_build_datetime("", "") is None
    assert _parse_build_datetime("Aug 18 2026", "invalid") is None


def test_app_descriptor_roundtrip() -> None:
    """Test parsing esp_app_desc_t struct from binary."""
    blob = _make_synth_blob(
        chip_id=0x00,
        version="2026.10.1",
        project="livingroom",
        time_str="14:30:00",
        date_str="Oct  9 2026",
        idf="v5.2.0",
        tail=b"Project local.livingroom version 1.2.3\x00",
    )
    desc = parse_app_descriptor(blob)
    assert desc["version"] == "2026.10.1"
    assert desc["project_name"] == "livingroom"
    assert desc["idf_version"] == "v5.2.0"
    assert desc["build_time"] == "2026-10-09T14:30:00"
    assert desc["project_literal_name"] == "local.livingroom"
    assert desc["project_version"] == "1.2.3"


def test_chip_family_sniffing() -> None:
    """Test chip identification across variants."""
    blob_esp32 = _make_synth_blob(chip_id=0x00)
    assert chip_family_from_binary(blob_esp32) == "ESP32"

    blob_s2 = _make_synth_blob(chip_id=0x02)
    assert chip_family_from_binary(blob_s2) == "ESP32-S2"

    blob_s3 = _make_synth_blob(chip_id=0x09)
    assert chip_family_from_binary(blob_s3) == "ESP32-S3"

    blob_c3 = _make_synth_blob(chip_id=0x05)
    assert chip_family_from_binary(blob_c3) == "ESP32-C3"

    blob_c6 = _make_synth_blob(chip_id=0x0D)
    assert chip_family_from_binary(blob_c6) == "ESP32-C6"

    # Platform fallback
    assert chip_family("esp8266")[0] == "ESP8266"
    assert chip_family("rp2040")[0] == "RP2040"


def test_inspect_binary_validation() -> None:
    """Test full inspect_binary metadata derivation and chip validation."""
    blob = _make_synth_blob(
        chip_id=0x00,
        tail=b"Project local.livingroom version 1.5.0\x00",
    )
    info = inspect_binary(blob=blob, target_platform="esp32", expected_chip="ESP32")
    assert info.chip_family == "ESP32"
    assert info.authoritative_version == "1.5.0"
    assert info.version_source == "project_literal"
    assert len(info.md5) == 32
    assert len(info.sha256) == 64

    # Size too small
    with pytest.raises(BinaryValidationError, match="too small"):
        inspect_binary(b"\xe9small")

    # Chip mismatch
    with pytest.raises(BinaryValidationError, match="Chip family mismatch"):
        inspect_binary(blob=blob, target_platform="esp32", expected_chip="ESP32-S3")


def test_inspect_binary_esp32_variant_compatibility() -> None:
    """When target device was registered with general ESP32, specific ESP32 variants (like ESP32-P4) must be accepted."""
    # 0x12 is ESP32-P4
    blob_p4 = _make_synth_blob(
        chip_id=0x12,
        tail=b"Project local.tab5 version 1.0.0\x00",
    )
    # Target device registered as general 'ESP32'
    info = inspect_binary(blob=blob_p4, target_platform="esp32", expected_chip="ESP32")
    assert info.chip_family == "ESP32-P4"
    assert info.authoritative_version == "1.0.0"

    # Specific variant mismatch should still fail (e.g. expected ESP32-S3 but binary is ESP32-P4)
    with pytest.raises(BinaryValidationError, match="Chip family mismatch"):
        inspect_binary(blob=blob_p4, target_platform="esp32", expected_chip="ESP32-S3")

