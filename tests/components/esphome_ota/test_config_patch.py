"""Unit tests for config patch, version ownership detection, and YAML diff generation."""

from __future__ import annotations


from custom_components.esphome_ota.config_patch import (
    apply_ota_patch,
    bump_patch_version,
    ensure_project_version,
    has_unclear_project_ownership,
    own_project_version,
    remove_ota_patch,
    set_project_version,
    strip_legacy_ota_packages,
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


def test_ensure_project_version_clears_include_ambiguity() -> None:
    """Writing top-level project.version makes package !include ownership clear."""
    content = """esphome:
  name: colorado
packages:
  common: !include common.yaml
"""
    assert has_unclear_project_ownership(content) is True
    updated, changed = ensure_project_version(content, "v260901 rev.1")
    assert changed is True
    assert 'version: "v260901 rev.1"' in updated
    assert has_unclear_project_ownership(updated) is False
    assert own_project_version(updated) == "v260901 rev.1"


def test_set_project_version_updates_literal_and_substitution() -> None:
    """Editing target version must rewrite esphome.project.version in YAML."""
    yaml_literal = """esphome:
  name: livingroom
  project:
    name: my.livingroom
    version: "1.0.0"
esp32:
  board: esp32dev
"""
    updated, changed = set_project_version(yaml_literal, "2.5.0")
    assert changed is True
    assert 'version: "2.5.0"' in updated
    assert own_project_version(updated) == "2.5.0"

    yaml_sub = """substitutions:
  project_version: "1.0.0"
esphome:
  name: livingroom
  project:
    name: my.livingroom
    version: ${project_version}
esp32:
  board: esp32dev
"""
    updated_sub, changed_sub = set_project_version(yaml_sub, "3.1.4")
    assert changed_sub is True
    assert 'project_version: "3.1.4"' in updated_sub
    assert own_project_version(updated_sub) == "3.1.4"


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
    assert "packages:" in cleaned


def test_remove_ota_patch_four_space_indent_and_empty_packages() -> None:
    """Support 4-space package indent and drop empty packages: key."""
    content = """esphome:
    name: kitchen
packages:
    esphome_ota:
        substitutions:
            ota_slug: "kitchen_1122"
sensor:
    - platform: uptime
"""
    cleaned, removed = remove_ota_patch(content)
    assert removed is True
    assert "esphome_ota:" not in cleaned
    assert "packages:" not in cleaned
    assert "sensor:" in cleaned
    assert "name: kitchen" in cleaned


def test_remove_ota_patch_only_managed_package() -> None:
    """When esphome_ota is the sole package, packages: must disappear."""
    content = """esphome:
  name: kitchen
packages:
  esphome_ota:
    substitutions:
      ota_slug: "kitchen_1122"
"""
    cleaned, removed = remove_ota_patch(content)
    assert removed is True
    assert "packages:" not in cleaned
    assert "esphome_ota:" not in cleaned
    assert "name: kitchen" in cleaned


def test_version_bump() -> None:
    """Test semantic version patch bumping."""
    assert bump_patch_version("1.0.0") == "1.0.1"
    assert bump_patch_version("1.0.9") == "1.0.10"
    assert bump_patch_version("2.1") == "2.1.1"
    assert bump_patch_version("3") == "3.0.1"


def test_strip_legacy_ota_packages() -> None:
    """Test stripping legacy ota_server packages and substitutions while preserving other content."""
    content = """substitutions:
  ota_device: bedroom
  ota_slug: bedroom_xyz123
  sensor_name: "Bedroom Temperature"

esphome:
  name: bedroom

packages:
  ota: !include ota_server/devices/bedroom.yaml
  my_sensors: !include sensors.yaml
"""
    cleaned, changed = strip_legacy_ota_packages(content)
    assert changed is True
    assert "ota_server" not in cleaned
    assert "ota_device:" not in cleaned
    assert "ota_slug:" not in cleaned
    assert "sensor_name: \"Bedroom Temperature\"" in cleaned
    assert "my_sensors: !include sensors.yaml" in cleaned


def test_apply_ota_patch_replaces_legacy_and_includes_project() -> None:
    """Applying OTA patch to legacy device must strip ota_server and include esphome.project."""
    content = """substitutions:
  ota_device: bedroom
  ota_slug: bedroom_abc

esphome:
  name: bedroom

packages:
  ota: !include ota_server/devices/bedroom.yaml
"""
    diff_res = apply_ota_patch(
        yaml_content=content,
        base_url="https://ha.local:8123",
        slug="bedroom_abc",
        target_version="2.0.1",
        node="bedroom",
    )
    assert "ota_server" not in diff_res.modified
    assert "esphome_ota:" in diff_res.modified
    # Critical: project must be included with target_version
    assert "project:" in diff_res.modified
    assert "local.bedroom" in diff_res.modified
    assert "2.0.1" in diff_res.modified


def test_apply_ota_patch_auto_deduces_node_and_target_version() -> None:
    """When node and target_version are not passed, apply_ota_patch deduces them from YAML."""
    content = """esphome:
  name: livingroom
esp32:
  board: esp32dev
"""
    diff_res = apply_ota_patch(
        yaml_content=content,
        base_url="https://ha.local:8123",
        slug="livingroom_123",
    )
    assert "esphome_ota:" in diff_res.modified
    assert "project:" in diff_res.modified
    assert "local.livingroom" in diff_res.modified
    assert "1.0.0" in diff_res.modified


def test_has_unclear_project_ownership_ignores_legacy_ota_server() -> None:
    """A device YAML with only legacy ota_server package should not be flagged as unclear."""
    content = """esphome:
  name: bedroom
esp8266:
  board: d1_mini
packages:
  ota: !include ota_server/devices/bedroom.yaml
"""
    assert has_unclear_project_ownership(content) is False


def test_strip_legacy_ota_packages_preserves_packages_header_with_comment() -> None:
    """Comments containing ota_server must not cause packages header or other packages to be deleted."""
    content = """esphome:
  name: livingroom

packages: # migrated from ota_server
  sensors: !include sensors.yaml
  custom: !include custom.yaml # previously ota_server
"""
    cleaned, changed = strip_legacy_ota_packages(content)
    assert "packages: # migrated from ota_server" in cleaned
    assert "sensors: !include sensors.yaml" in cleaned
    assert "custom: !include custom.yaml" in cleaned
    assert "esphome:" in cleaned


def test_strip_legacy_ota_packages_preserves_regular_packages_with_ota_server_identifiers() -> None:
    """Regular packages containing ota_server identifiers or values must not be deleted."""
    content = """esphome:
  name: livingroom

packages:
  diagnostics:
    sensor:
      - platform: status
        name: "ESP Status"
        id: ota_server_status
  ota: !include ota_server/devices/livingroom.yaml
"""
    cleaned, changed = strip_legacy_ota_packages(content)
    assert changed is True
    assert "diagnostics:" in cleaned
    assert "id: ota_server_status" in cleaned
    assert "ota: !include" not in cleaned

    content_only_diag = """esphome:
  name: livingroom

packages:
  diagnostics:
    sensor:
      - platform: status
        name: "ESP Status"
        id: ota_server_status
"""
    cleaned2, changed2 = strip_legacy_ota_packages(content_only_diag)
    assert changed2 is False
    assert cleaned2 == content_only_diag


def test_strip_legacy_ota_packages_inlines_legacy_substitution_references() -> None:
    """Removing ota_device/ota_slug definition must inline any lingering ${ota_device} references."""
    content = """substitutions:
  ota_device: livingroom
  ota_slug: livingroom_abc

esphome:
  name: ${ota_device}
  comment: "$ota_slug active"
"""
    cleaned, changed = strip_legacy_ota_packages(content)
    assert changed is True
    assert "substitutions:" not in cleaned
    assert "ota_device:" not in cleaned
    assert "name: livingroom" in cleaned
    assert 'comment: "livingroom_abc active"' in cleaned




