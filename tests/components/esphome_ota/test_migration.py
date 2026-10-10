"""Unit tests for legacy add-on migration adapter."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.esphome_ota.const import DEFAULT_PUBLISH_DIR
from custom_components.esphome_ota.devices import DeviceManager
from custom_components.esphome_ota.migration import MigrationManager
from custom_components.esphome_ota.publisher import ArtifactPublisher
from custom_components.esphome_ota.storage import StorageManager


async def test_migration_preview_and_execution(hass: HomeAssistant) -> None:
    """Test importing legacy registered devices and public files."""
    # 1. Setup legacy test files in hass config directory
    esphome_dir = Path(hass.config.path("esphome"))
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

    # Verify preview now reports already_migrated
    preview_after = await migrator.async_preview()
    assert preview_after["already_migrated"] is True
    assert "migrated_at" in preview_after

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


def test_migration_frontend_components() -> None:
    """Verify frontend manager.js and migration-dialog.js define migration UI elements."""
    base = (
        Path(__file__).parents[3]
        / "custom_components"
        / "esphome_ota"
        / "frontend"
    )
    manager_js = (base / "manager.js").read_text(encoding="utf-8")
    mig_dialog_js = (base / "migration-dialog.js").read_text(encoding="utf-8")
    i18n_js = (base / "i18n.js").read_text(encoding="utf-8")

    assert 'import "./migration-dialog.js";' in manager_js
    assert 'id="btn-migration"' in manager_js
    assert 'id="migration-banner"' in manager_js
    assert "<esphome-ota-migration-dialog></esphome-ota-migration-dialog>" in manager_js

    assert "esphome-ota-migration-dialog" in mig_dialog_js
    assert "esphome_ota/migrate_preview" in mig_dialog_js
    assert "esphome_ota/migrate_execute" in mig_dialog_js
    assert "migration-completed" in mig_dialog_js

    assert "migration_banner_title" in i18n_js
    assert "migration_dialog_title" in i18n_js
