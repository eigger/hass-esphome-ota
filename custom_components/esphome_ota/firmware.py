"""Firmware binary inspection, validation, hashing, and metadata extraction."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from .models import BinaryValidationError

_LOGGER = logging.getLogger(__name__)

# target_platform (normalised to lowercase alphanumerics) -> ESPHOME_VARIANT
VARIANTS = {
    "esp32": "ESP32",
    "esp32s2": "ESP32-S2",
    "esp32s3": "ESP32-S3",
    "esp32c2": "ESP32-C2",
    "esp32c3": "ESP32-C3",
    "esp32c5": "ESP32-C5",
    "esp32c6": "ESP32-C6",
    "esp32h2": "ESP32-H2",
    "esp32p4": "ESP32-P4",
    "esp8266": "ESP8266",
    "rp2040": "RP2040",
    "rp2350": "RP2350",
}

CHIP_FAMILIES = sorted(set(VARIANTS.values()))

# esp_image_header_t.chip_id (uint16 LE at offset 12) -> ESPHOME_VARIANT
CHIP_IDS = {
    0x00: "ESP32",
    0x02: "ESP32-S2",
    0x05: "ESP32-C3",
    0x09: "ESP32-S3",
    0x0C: "ESP32-C2",
    0x0D: "ESP32-C6",
    0x10: "ESP32-H2",
    0x12: "ESP32-P4",
    0x17: "ESP32-C5",
}

ESP_IMAGE_MAGIC = 0xE9
ESP_IMAGE_HEADER_LEN = 24
ESP_APP_DESC_MAGIC = 0xABCD5432

_RE_PROJECT_VERSION = re.compile(
    rb"Project ([\x20-\x7e]{1,63}?) version ([\x20-\x7e]{1,63})\x00"
)

_RE_LITERAL_BUILD_TIME = re.compile(
    rb"(20\d\d-[01]\d-[0-3]\d[ T][0-2]\d:[0-5]\d:[0-5]\d(?: ?[+-]\d{4})?)\x00"
)

_MONTH_MAP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def normalise_platform(value: str) -> str:
    """Normalize platform string."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def chip_id_from_binary(blob: bytes) -> int | None:
    """Read esp_image_header_t.chip_id, or None when this isn't an ESP32 image."""
    if len(blob) < ESP_IMAGE_HEADER_LEN or blob[0] != ESP_IMAGE_MAGIC:
        return None
    chip_id = int.from_bytes(blob[12:14], "little")
    if chip_id in CHIP_IDS:
        return chip_id
    if blob[19:23] == b"\x00\x00\x00\x00" and blob[23] <= 1:
        return chip_id
    return None


def chip_family_from_binary(blob: bytes) -> str | None:
    """Read the variant out of an ESP32 application image header."""
    chip_id = chip_id_from_binary(blob)
    return CHIP_IDS.get(chip_id) if chip_id is not None else None


def chip_family(
    target_platform: str, blob: bytes | None = None
) -> tuple[str | None, str]:
    """Return (chipFamily, how_it_was_determined)."""
    mapped = VARIANTS.get(normalise_platform(target_platform))
    sniffable = mapped is None or mapped.startswith("ESP32")
    if blob is not None:
        chip_id = chip_id_from_binary(blob) if sniffable else None
        sniffed = CHIP_IDS.get(chip_id) if chip_id is not None else None
        if sniffed:
            return sniffed, "binary"
        if mapped == "ESP8266" and len(blob) >= 8 and blob[0] == ESP_IMAGE_MAGIC:
            return "ESP8266", "binary"
        return None, "invalid"

    if mapped:
        return mapped, "platform"
    return None, "unknown"


def _parse_build_datetime(date_str: str, time_str: str) -> str | None:
    """Convert GCC __DATE__/__TIME__ strings to an ISO-8601 string."""
    try:
        parts = date_str.split()
        if len(parts) != 3:
            return None
        month = _MONTH_MAP.get(parts[0])
        day = int(parts[1])
        year = int(parts[2])
        if not month:
            return None
        h, m, s = (int(x) for x in time_str.split(":"))
        return f"{year:04d}-{month:02d}-{day:02d}T{h:02d}:{m:02d}:{s:02d}"
    except Exception:  # noqa: BLE001
        return None


def _find_literal_build_time(blob: bytes) -> str | None:
    """Scan for ESPHome's compiled-in build time literal."""
    match = _RE_LITERAL_BUILD_TIME.search(blob)
    if not match:
        return None
    return match.group(1).decode("ascii", errors="ignore")


def _find_project_version(blob: bytes) -> tuple[str, str] | None:
    """Scan for the 'Project <name> version <version>' boot-log literal."""
    match = _RE_PROJECT_VERSION.search(blob)
    if not match:
        return None
    name = match.group(1).decode("utf-8", errors="ignore").strip()
    version = match.group(2).decode("utf-8", errors="ignore").strip()
    if not name or not version:
        return None
    return name, version


def parse_app_descriptor(blob: bytes) -> dict[str, str]:
    """Parse esp_app_desc_t at offset 0x20, plus ESPHome's boot literals."""
    if len(blob) < 0x20 + 160:
        return {}
    magic = int.from_bytes(blob[0x20:0x24], "little")
    if magic != ESP_APP_DESC_MAGIC:
        return {}
    try:
        ver_bytes = blob[0x30:0x50].split(b"\x00")[0]
        version = ver_bytes.decode("utf-8", errors="ignore").strip()
        proj_bytes = blob[0x50:0x70].split(b"\x00")[0]
        project = proj_bytes.decode("utf-8", errors="ignore").strip()
        time_bytes = blob[0x70:0x80].split(b"\x00")[0]
        build_time_str = time_bytes.decode("utf-8", errors="ignore").strip()
        date_bytes = blob[0x80:0x90].split(b"\x00")[0]
        build_date_str = date_bytes.decode("utf-8", errors="ignore").strip()
        idf_bytes = blob[0x90:0xB0].split(b"\x00")[0]
        idf_ver = idf_bytes.decode("utf-8", errors="ignore").strip()
        result: dict[str, str] = {
            "version": version,
            "project_name": project,
            "idf_version": idf_ver,
        }
        build_dt = _parse_build_datetime(
            build_date_str, build_time_str
        ) or _find_literal_build_time(blob)
        if build_dt:
            result["build_time"] = build_dt

        literal = _find_project_version(blob)
        if literal:
            result["project_literal_name"], result["project_version"] = literal
        return result
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class BinaryInfo:
    """Analyzed and verified firmware binary information."""

    size: int
    md5: str
    sha256: str
    chip_family: str
    chip_source: str
    authoritative_version: str
    framework_version: str | None = None
    project_version: str | None = None
    project_literal_name: str | None = None
    build_time: str | None = None
    idf_version: str | None = None
    version_source: str = "framework"


def inspect_binary(
    blob: bytes,
    target_platform: str = "esp32",
    expected_chip: str | None = None,
    reserved_version: str | None = None,
) -> BinaryInfo:
    """Validate firmware binary structure and extract metadata.

    Raises:
        BinaryValidationError: If binary is invalid, corrupted, or chip family mismatches.
    """
    if len(blob) < 1024:
        raise BinaryValidationError(f"Binary is too small: {len(blob)} bytes")

    md5_hash = hashlib.md5(blob).hexdigest()
    sha256_hash = hashlib.sha256(blob).hexdigest()

    chip, source = chip_family(target_platform, blob)
    if not chip or source != "binary":
        target_name = (
            expected_chip
            or VARIANTS.get(normalise_platform(target_platform))
            or target_platform
        )
        raise BinaryValidationError(
            f"Invalid firmware binary structure for target '{target_name}': "
            "binary header magic or chip family could not be identified"
        )

    if expected_chip and chip != expected_chip:
        # If target device was registered as general "ESP32", allow specific ESP32 variants (ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, ESP32-P4, etc.)
        is_esp32_compat = expected_chip == "ESP32" and chip.startswith("ESP32")
        if not is_esp32_compat:
            raise BinaryValidationError(
                f"Chip family mismatch: binary is {chip}, but target device expected {expected_chip}"
            )

    mapped_target = VARIANTS.get(normalise_platform(target_platform))
    if mapped_target and mapped_target != "ESP32" and chip != mapped_target:
        raise BinaryValidationError(
            f"Chip family mismatch: binary is {chip}, but target device expected {mapped_target}"
        )

    desc = parse_app_descriptor(blob)
    proj_ver = desc.get("project_version")
    framework_ver = desc.get("version")
    build_time = desc.get("build_time")
    idf_ver = desc.get("idf_version")
    proj_literal_name = desc.get("project_literal_name")

    # Authoritative version priority:
    # 1. Boot-log Project version (what device reports at runtime)
    # 2. Reserved version (if provided for managed tracking)
    # 3. ESPHome framework version
    if proj_ver:
        auth_version = proj_ver
        ver_source = "project_literal"
    elif reserved_version:
        auth_version = reserved_version
        ver_source = "managed_reserved"
    elif framework_ver:
        auth_version = framework_ver
        ver_source = "framework"
    else:
        auth_version = "1.0.0"
        ver_source = "fallback"

    return BinaryInfo(
        size=len(blob),
        md5=md5_hash,
        sha256=sha256_hash,
        chip_family=chip,
        chip_source=source,
        authoritative_version=auth_version,
        framework_version=framework_ver,
        project_version=proj_ver,
        project_literal_name=proj_literal_name,
        build_time=build_time,
        idf_version=idf_ver,
        version_source=ver_source,
    )
