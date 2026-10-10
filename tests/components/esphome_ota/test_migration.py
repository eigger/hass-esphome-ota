"""Unit tests for legacy add-on migration adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.const import DEFAULT_PUBLISH_DIR
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.migration import MigrationManager
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager

_FRONTEND_DIR = (
    Path(__file__).parents[3] / "custom_components" / "esphome_ota" / "frontend"
)


def _i18n_keys(i18n_js: str, lang: str) -> set[str]:
    """Extract translation keys for a language block from i18n.js source."""
    match = re.search(
        rf"^\s{{2}}{lang}:\s*\{{(.*?)^\s{{2}}\}},",
        i18n_js,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"Missing {lang} translation block"
    return set(re.findall(r"^\s{4}(\w+):", match.group(1), re.MULTILINE))


async def test_migration_preview_and_execution(hass: HomeAssistant) -> None:
    """Test importing legacy registered devices and public files."""
    # 1. Setup legacy test files in hass config directory
    esphome_dir = Path(hass.config.path("esphome"))
    for p in esphome_dir.glob("*.yaml"):
        p.unlink(missing_ok=True)
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    registered_data = {
        "livingroom": {
            "token": "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a",
            "version": "1.0.5",
            "title": "Living Room Sensor",
        },
        "legacy_garage": {
            "token": "",
            "version": "1.0.0",
            "title": "Garage",
        },
    }
    (legacy_dir / "registered.json").write_text(
        json.dumps(registered_data), encoding="utf-8"
    )

    www_dir = Path(hass.config.path("www", DEFAULT_PUBLISH_DIR))
    www_dir.mkdir(parents=True, exist_ok=True)
    for p in www_dir.glob("*"):
        p.unlink(missing_ok=True)
    dummy_bin = b"\xe9\x00\x00\x00" + b"\x00" * 1500
    (www_dir / "livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.ota.bin").write_bytes(
        dummy_bin
    )
    (www_dir / "livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.json").write_text(
        "{}", encoding="utf-8"
    )

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)
    migrator = MigrationManager(hass, storage, device_manager, publisher)

    # 2. Preview
    preview = await migrator.async_preview()
    assert preview["has_legacy_registry"] is True
    assert preview["device_count"] == 2
    assert "livingroom" in preview["devices"]
    assert preview["binary_count"] == 1
    assert preview["already_migrated"] is False

    # 3. Execute
    res = await migrator.async_migrate()
    assert res["success"] is True
    assert "livingroom" in res["migrated_devices"]
    assert "legacy_garage" in res["migrated_devices"]
    assert "livingroom" in res["migrated_artifacts"]

    # Verify preview now reports already_migrated with a timestamp
    preview_after = await migrator.async_preview()
    assert preview_after["already_migrated"] is True
    assert preview_after["migrated_at"]
    assert "T" in preview_after["migrated_at"]

    # 4. Verify migrated devices loaded into DeviceManager
    dev_lr = device_manager.get_device("livingroom")
    assert dev_lr is not None
    assert dev_lr.token == "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
    assert dev_lr.friendly_name == "Living Room Sensor"

    dev_gar = device_manager.get_device("legacy_garage")
    assert dev_gar is not None
    assert dev_gar.token == ""
    assert dev_gar.slug == "legacy_garage"

    # 5. Idempotent re-run
    res2 = await migrator.async_migrate()
    assert res2["success"] is True


async def test_migration_matches_builder_and_reports_ambiguous(
    hass: HomeAssistant,
) -> None:
    """Migration should attach to plain YAML and report slug-named copies."""
    esphome_dir = Path(hass.config.path("esphome"))
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    token = "66538f8029a9436117254bea079c279e"
    (legacy_dir / "registered.json").write_text(
        json.dumps(
            {
                "esp-colorado-tab5": {
                    "token": token,
                    "version": "1.0.0",
                    "title": "ESP Colorado TAB5",
                }
            }
        ),
        encoding="utf-8",
    )

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    device_manager.update_builder_devices(
        [
            {
                "configuration": "esp-colorado-tab5.yaml",
                "name": "esp-colorado-tab5",
                "friendly_name": "ESP Colorado TAB5",
                "target_platform": "esp32",
            },
            {
                "configuration": f"esp-colorado-tab5_{token}(1).yaml",
                "name": "esp-colorado-tab5",
                "friendly_name": "ESP Colorado TAB5",
                "target_platform": "esp32",
            },
        ]
    )
    publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)
    migrator = MigrationManager(hass, storage, device_manager, publisher)

    res = await migrator.async_migrate()
    assert res["success"] is True
    assert "ambiguous_matches" in res
    assert "esp-colorado-tab5" in res["ambiguous_matches"]

    managed = device_manager.get_device("esp-colorado-tab5")
    assert managed is not None
    assert managed.configuration == "esp-colorado-tab5.yaml"
    assert device_manager.get_device(f"esp-colorado-tab5_{token}(1)") is None

    listed = device_manager.list_all()
    managed_rows = [d for d in listed if d["is_managed"]]
    unmanaged_rows = [d for d in listed if not d["is_managed"]]
    assert len(managed_rows) == 1
    assert managed_rows[0]["configuration"] == "esp-colorado-tab5.yaml"
    assert any(
        d["configuration"] == f"esp-colorado-tab5_{token}(1).yaml"
        for d in unmanaged_rows
    )


def test_migration_frontend_components() -> None:
    """Verify frontend manager.js and migration-dialog.js define migration UI elements."""
    manager_js = (_FRONTEND_DIR / "manager.js").read_text(encoding="utf-8")
    mig_dialog_js = (_FRONTEND_DIR / "migration-dialog.js").read_text(encoding="utf-8")
    i18n_js = (_FRONTEND_DIR / "i18n.js").read_text(encoding="utf-8")

    assert 'import "./migration-dialog.js";' in manager_js
    assert 'import "./build-dialog.js";' in manager_js
    assert 'id="btn-migration"' in manager_js
    assert 'id="migration-banner"' in manager_js
    assert "<esphome-ota-migration-dialog></esphome-ota-migration-dialog>" in manager_js
    assert "<esphome-ota-build-dialog></esphome-ota-build-dialog>" in manager_js
    assert (_FRONTEND_DIR / "build-dialog.js").is_file()

    assert "esphome-ota-migration-dialog" in mig_dialog_js
    assert "esphome_ota/migrate_preview" in mig_dialog_js
    assert "esphome_ota/migrate_execute" in mig_dialog_js
    assert "migration-completed" in mig_dialog_js
    assert "if (res && res.success)" in mig_dialog_js
    assert "failed_devices" in mig_dialog_js
    assert "migration_failed_devices" in mig_dialog_js
    assert "migration_partial_success" in mig_dialog_js
    assert "migration_retry_btn" in mig_dialog_js
    assert "migration_importing" in mig_dialog_js
    assert "status-box error" in mig_dialog_js
    assert "status-box warning" in mig_dialog_js

    assert "migration_banner_title" in i18n_js
    assert "migration_dialog_title" in i18n_js
    assert "migration_retry_btn" in i18n_js
    assert "migration_failed_devices" in i18n_js
    assert "migration_partial_success" in i18n_js
    assert 'batch_build: "Build & Publish Selected"' in i18n_js
    assert "filter_managed" in i18n_js
    assert 'value="managed"' in manager_js
    assert "if (e.detail?.success)" in manager_js
    assert "_filterDefaulted" in manager_js
    assert "_syncDefaultFilter" in manager_js
    assert "definePanelElement" in manager_js
    assert (_FRONTEND_DIR / "elements.js").is_file()
    assert "_getLatestJob" in manager_js
    assert "_getDeviceBadge" in manager_js
    assert "esphome_ota/remove_ota" in manager_js
    assert "btn_remove_ota" in i18n_js
    assert "migration_ambiguous" in i18n_js


def test_i18n_en_ko_key_parity() -> None:
    """Ensure English and Korean translation key sets stay in sync."""
    i18n_js = (_FRONTEND_DIR / "i18n.js").read_text(encoding="utf-8")
    en_keys = _i18n_keys(i18n_js, "en")
    ko_keys = _i18n_keys(i18n_js, "ko")
    assert en_keys == ko_keys, (
        f"en-only: {sorted(en_keys - ko_keys)}; ko-only: {sorted(ko_keys - en_keys)}"
    )
    assert "batch_build" in en_keys


async def test_migration_transforms_yaml_config_from_ota_server_to_inline_package(
    hass: HomeAssistant,
) -> None:
    """Migration should transform device YAML from legacy ota_server to packages.esphome_ota with project block."""
    from unittest.mock import AsyncMock

    esphome_dir = Path(hass.config.path("esphome"))
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
    registered_data = {
        "livingroom": {
            "token": token,
            "version": "1.0.5",
            "title": "Living Room Sensor",
        }
    }
    (legacy_dir / "registered.json").write_text(
        json.dumps(registered_data), encoding="utf-8"
    )

    # Legacy device YAML with ota_server include and legacy substitutions
    legacy_device_yaml = """substitutions:
  ota_device: livingroom
  ota_slug: livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a

esphome:
  name: livingroom
  friendly_name: Living Room Sensor

esp32:
  board: esp32dev

packages:
  ota: !include ota_server/devices/livingroom.yaml
"""
    yaml_file = esphome_dir / "livingroom.yaml"
    yaml_file.write_text(legacy_device_yaml, encoding="utf-8")

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)

    # Builder client simulates CAS update and updates disk file
    mock_client = AsyncMock()
    mock_client.get_config.return_value = legacy_device_yaml

    async def mock_update(configuration: str, content: str, expected: str | None = None) -> None:
        yaml_file.write_text(content, encoding="utf-8")

    mock_client.update_config.side_effect = mock_update

    migrator = MigrationManager(
        hass,
        storage,
        device_manager,
        publisher,
        base_url="https://my-ha.duckdns.org",
        builder_client=mock_client,
    )

    res = await migrator.async_migrate()
    assert res["success"] is True
    assert "livingroom" in res["migrated_devices"]
    assert "livingroom" in res["migrated_yaml_configs"]

    # Verify CAS was invoked with expected=legacy_device_yaml
    mock_client.update_config.assert_called_once()
    assert mock_client.update_config.call_args.kwargs.get("expected") == legacy_device_yaml

    # Verify transformed YAML
    updated_yaml = yaml_file.read_text(encoding="utf-8")
    assert "ota_server" not in updated_yaml
    assert "ota_device:" not in updated_yaml
    assert "packages:" in updated_yaml
    assert "esphome_ota:" in updated_yaml
    assert "https://my-ha.duckdns.org" in updated_yaml
    assert f"livingroom_{token}" in updated_yaml
    # Critical: esphome.project block MUST be included with correct version
    assert "project:" in updated_yaml
    assert "local.livingroom" in updated_yaml
    assert "1.0.5" in updated_yaml

    # Verify device record
    dev = device_manager.get_device("livingroom")
    assert dev is not None
    assert dev.yaml_mode == "inline_package"
    assert dev.managed_version == "1.0.5"
    assert dev.token == token


async def test_migration_concurrent_modification_conflict_fails(
    hass: HomeAssistant,
) -> None:
    """Migration must record device failure and preserve external changes on concurrent edits."""
    from unittest.mock import AsyncMock
    from custom_components.esphome_ota.models import ConfigConflictError

    esphome_dir = Path(hass.config.path("esphome"))
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    token = "a8f3b9c2e17d904f8e5b6c7a1d2e3f4a"
    registered_data = {
        "livingroom": {
            "token": token,
            "version": "1.0.5",
            "title": "Living Room Sensor",
        }
    }
    (legacy_dir / "registered.json").write_text(
        json.dumps(registered_data), encoding="utf-8"
    )

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)

    # 1. Test Builder CAS conflict
    mock_client = AsyncMock()
    mock_client.get_config.return_value = (
        "esphome:\n  name: livingroom\npackages:\n  ota: !include ota_server/dev.yaml\n"
    )
    mock_client.update_config.side_effect = ConfigConflictError("CAS conflict: file modified")

    migrator_builder = MigrationManager(
        hass, storage, device_manager, publisher, builder_client=mock_client
    )

    res = await migrator_builder.async_migrate()
    assert res["success"] is False
    assert "livingroom" in res["failed_devices"]
    assert "livingroom" not in res["migrated_devices"]
    assert "CAS conflict" in res["failed_devices"]["livingroom"]

    # Device must NOT have been registered and migration record NOT saved as completed
    assert device_manager.get_device("livingroom") is None
    assert not await storage.async_load_migration()

    # 2. Test local disk edit protection when Builder is not connected
    yaml_file = esphome_dir / "livingroom.yaml"
    initial_yaml = "esphome:\n  name: livingroom\npackages:\n  ota: !include ota_server/dev.yaml\n"
    # External editor added a sensor concurrently
    yaml_file.write_text(
        initial_yaml + "\nsensor:\n  - name: AddedConcurrently\n",
        encoding="utf-8",
    )

    migrator_local = MigrationManager(hass, storage, device_manager, publisher)

    res_local = await migrator_local.async_migrate()
    assert res_local["success"] is False
    assert "livingroom" in res_local["failed_devices"]
    assert "Builder client is not connected" in res_local["failed_devices"]["livingroom"]

    # Verify concurrent edit was NOT overwritten
    current = yaml_file.read_text(encoding="utf-8")
    assert "AddedConcurrently" in current
    assert device_manager.get_device("livingroom") is None
    assert not await storage.async_load_migration()


async def test_migration_partial_device_failure_does_not_mark_failed_devices_as_migrated(
    hass: HomeAssistant,
) -> None:
    """When one device fails during YAML update, other devices continue and completed record is not stored."""
    from unittest.mock import AsyncMock
    from custom_components.esphome_ota.models import BuilderError

    esphome_dir = Path(hass.config.path("esphome"))
    legacy_dir = esphome_dir / "ota_server"
    legacy_dir.mkdir(parents=True, exist_ok=True)

    registered_data = {
        "device_a": {
            "token": "tok_a",
            "version": "1.0.0",
            "title": "Device A",
        },
        "device_b": {
            "token": "tok_b",
            "version": "2.0.0",
            "title": "Device B",
        },
    }
    (legacy_dir / "registered.json").write_text(
        json.dumps(registered_data), encoding="utf-8"
    )

    storage = StorageManager(hass)
    device_manager = DeviceManager(hass, storage)
    publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)

    mock_client = AsyncMock()

    async def mock_get_config(cfg: str) -> str:
        name = "device_a" if "device_a" in cfg else "device_b"
        return f"esphome:\n  name: {name}\npackages:\n  ota: !include ota_server/{name}.yaml\n"

    async def mock_update_config(cfg: str, content: str, expected: str | None = None) -> None:
        if "device_a" in cfg:
            raise BuilderError("devices/update_config failed: PERMISSION_DENIED Permission denied")
        # device_b succeeds

    mock_client.get_config.side_effect = mock_get_config
    mock_client.update_config.side_effect = mock_update_config

    migrator = MigrationManager(
        hass, storage, device_manager, publisher, builder_client=mock_client
    )

    res = await migrator.async_migrate()

    # 1. Overall result must be success=False due to failure
    assert res["success"] is False
    assert "failed_devices" in res
    assert "device_a" in res["failed_devices"]
    assert "Permission denied" in res["failed_devices"]["device_a"]

    # 2. Failed device must NOT be in migrated_devices or migrated_yaml_configs
    assert "device_a" not in res["migrated_devices"]
    assert "device_a" not in res["migrated_yaml_configs"]
    assert device_manager.get_device("device_a") is None

    # 3. Successful device MUST be in migrated_devices and migrated_yaml_configs
    assert "device_b" in res["migrated_devices"]
    assert "device_b" in res["migrated_yaml_configs"]
    dev_b = device_manager.get_device("device_b")
    assert dev_b is not None
    assert dev_b.name == "device_b"

    # 4. Completed migration record MUST NOT be saved when there are failures
    assert not await storage.async_load_migration()
    preview = await migrator.async_preview()
    assert preview["already_migrated"] is False


