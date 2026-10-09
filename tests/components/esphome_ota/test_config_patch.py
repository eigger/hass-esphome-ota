"""Unit tests for config patch, version ownership detection, and YAML diff generation."""

from __future__ import annotations

import pytest

from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    bump_patch_version,
    own_project_version,
    remove_ota_patch,
)


def test_own_project_version_detection() -> None:
    """Test detecting user's own project version and not framework version."""
    # 1. User declares project.version
    yaml_with_proj = """
esphome:
  name: livingroom
  project:
    name: "my.livingroom"
    version: "2.5.0"
esp32:
  board: esp32dev
"""
    assert own_project_version(yaml_with_proj) == "2.5.0"

    # 2. User has esp32 framework version, but no project block
    yaml_with_fw = """
esphome:
  name: livingroom
esp32:
  board: esp32dev
  framework:
    type: esp-idf
    version: 5.1.2
"""
    assert own_project_version(yaml_with_fw) is None

    # 3. Simple device YAML without project
    yaml_simple = """
esphome:
  name: bedroom
esp8266:
  board: d1_mini
"""
    assert own_project_version(yaml_simple) is None


def test_apply_ota_patch_preserves_comments_and_secrets() -> None:
    """Test applying OTA package into YAML preserving custom comments, !secret, and formatting."""
    original = """# Living Room Sensor
esphome:
  name: livingroom

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

packages:
  sensors: !include sensors.yaml

sensor:
  - platform: dht
    pin: GPIO23
"""
    diff_res = apply_ota_patch(
        yaml_content=original,
        base_url="https://my-ha.duckdns.org",
        slug="livingroom_abc123",
        target_version="1.0.0",
        node="livingroom",
    )

    assert "+  esphome_ota:" in diff_res.diff
    assert "https://my-ha.duckdns.org" in diff_res.modified
    assert "livingroom_abc123" in diff_res.modified
    # Check preservation of comments and secrets
    assert "# Living Room Sensor" in diff_res.modified
    assert "!secret wifi_password" in diff_res.modified
    assert "!include sensors.yaml" in diff_res.modified


def test_apply_ota_patch_creates_packages_if_absent() -> None:
    """Test applying patch to YAML that lacks a top-level packages: block."""
    original = """esphome:
  name: kitchen
esp32:
  board: esp32dev
"""
    diff_res = apply_ota_patch(
        yaml_content=original,
        base_url="https://ha.local",
        slug="kitchen_112233",
        target_version="1.0.0",
        node="kitchen",
    )

    assert "packages:" in diff_res.modified
    assert "  esphome_ota:" in diff_res.modified


def test_remove_ota_patch() -> None:
    """Test removing managed esphome_ota block cleanly."""
    content = """esphome:
  name: kitchen
packages:
  esphome_ota:
    substitutions:
      ota_slug: "kitchen_1122"
    update:
      - platform: http_request
  custom_pkg: !include custom.yaml
"""
    cleaned, removed = remove_ota_patch(content)
    assert removed is True
    assert "esphome_ota:" not in cleaned
    assert "custom_pkg: !include custom.yaml" in cleaned


def test_version_bump() -> None:
    """Test semantic version patch bumping."""
    assert bump_patch_version("1.0.0") == "1.0.1"
    assert bump_patch_version("1.0.9") == "1.0.10"
    assert bump_patch_version("2.1") == "2.1.1"
    assert bump_patch_version("3") == "3.0.1"
