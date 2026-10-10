"""Data migration adapter from legacy ESPHome OTA Publisher add-on."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .config_patch import apply_ota_patch
from .const import DEFAULT_PUBLISH_DIR, YAML_MODE_INLINE_PACKAGE
from .devices import DeviceManager
from .firmware import inspect_binary
from .models import BuilderConnectionError
from .publisher import ArtifactPublisher
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)


class MigrationManager:
    """Imports configuration, tokens, and artifacts from legacy ESPHome OTA Publisher add-on."""

    def __init__(
        self,
        hass: HomeAssistant,
        storage: StorageManager,
        device_manager: DeviceManager,
        publisher: ArtifactPublisher,
        base_url: str = "",
        resolver: Any = None,
        builder_client: Any = None,
    ) -> None:
        self.hass = hass
        self.storage = storage
        self.device_manager = device_manager
        self.publisher = publisher
        self.base_url = base_url
        self.resolver = resolver
        self._builder_client = builder_client

    @property
    def client(self) -> Any:
        """Return active BuilderClient if available."""
        if self._builder_client is not None:
            return self._builder_client
        if self.resolver is not None:
            return getattr(self.resolver, "active_client", None)
        return None

    def _inspect_legacy_data_sync(self) -> dict[str, Any]:
        """Inspect legacy directories and prepare migration preview."""
        esphome_dir = Path(self.hass.config.path("esphome"))
        legacy_reg_path = esphome_dir / "ota_server" / "registered.json"
        www_dir = Path(self.hass.config.path("www", DEFAULT_PUBLISH_DIR))

        registered_data: dict[str, Any] = {}
        if legacy_reg_path.is_file():
            try:
                registered_data = json.loads(legacy_reg_path.read_text(encoding="utf-8"))
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to read legacy registered.json: %s", err)

        manifests_found: list[str] = []
        binaries_found: list[str] = []
        if www_dir.is_dir():
            for p in www_dir.glob("*.json"):
                manifests_found.append(p.name)
            for p in www_dir.glob("*.ota.bin"):
                binaries_found.append(p.name)

        return {
            "has_legacy_registry": legacy_reg_path.is_file(),
            "device_count": len(registered_data),
            "devices": list(registered_data.keys()),
            "manifest_count": len(manifests_found),
            "binary_count": len(binaries_found),
        }

    async def async_preview(self) -> dict[str, Any]:
        """Return preview of migratable data."""
        data = await self.hass.async_add_executor_job(self._inspect_legacy_data_sync)
        record = await self.storage.async_load_migration()
        data["already_migrated"] = bool(record)
        if record:
            data["migrated_at"] = record.get("migrated_at")
        return data

    def _execute_migration_sync(self) -> dict[str, Any]:
        """Migrate legacy devices and public files into modern storage format."""
        esphome_dir = Path(self.hass.config.path("esphome"))
        legacy_reg_path = esphome_dir / "ota_server" / "registered.json"
        www_dir = Path(self.hass.config.path("www", DEFAULT_PUBLISH_DIR))

        registered: dict[str, Any] = {}
        if legacy_reg_path.is_file():
            try:
                registered = json.loads(legacy_reg_path.read_text(encoding="utf-8"))
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Could not read legacy registry during migration: %s", err)

        migrated_artifacts: list[str] = []

        for node, rec in registered.items():
            token = rec.get("token", "")
            slug = f"{node}_{token}" if token else node
            version = rec.get("version", "1.0.0")
            title = rec.get("title") or node

            # Check if public binary exists in www directory
            bin_path = www_dir / f"{slug}.ota.bin"
            if bin_path.is_file():
                try:
                    blob = bin_path.read_bytes()
                    info = inspect_binary(blob=blob, reserved_version=version)
                    # Archive into private storage
                    self.publisher._publish_sync(
                        device_id=node,
                        configuration=f"{node}.yaml",
                        slug=slug,
                        blob=blob,
                        info=info,
                        title=title,
                    )
                    migrated_artifacts.append(node)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed copying binary for %s: %s", node, err)

        return {
            "migrated_artifacts": migrated_artifacts,
        }

    async def async_migrate(self) -> dict[str, Any]:
        """Execute legacy migration and update storage."""
        sync_result = await self.hass.async_add_executor_job(self._execute_migration_sync)
        migrated_artifacts: list[str] = sync_result.get("migrated_artifacts", [])

        # Reload devices in device_manager, matching Builder YAML when possible
        esphome_dir = Path(self.hass.config.path("esphome"))
        legacy_reg_path = esphome_dir / "ota_server" / "registered.json"
        ambiguous_matches: dict[str, list[str]] = {}
        claimed_configs: set[str] = set()

        migrated_devices: list[str] = []
        failed_devices: dict[str, str] = {}
        migrated_yaml_configs: list[str] = []

        if legacy_reg_path.is_file():
            try:
                content = await self.hass.async_add_executor_job(
                    legacy_reg_path.read_text, "utf-8"
                )
                registered = json.loads(content)
            except Exception as reg_err:  # noqa: BLE001
                _LOGGER.error("Failed to read legacy registered.json: %s", reg_err)
                return {
                    "success": False,
                    "error": f"Failed to read legacy registry: {reg_err}",
                    "migrated_devices": [],
                    "migrated_artifacts": migrated_artifacts,
                    "migrated_yaml_configs": [],
                }

            for node, rec in registered.items():
                try:
                    token = rec.get("token", "") or ""
                    title = rec.get("title") or node
                    version = rec.get("version", "1.0.0")
                    slug = f"{node}_{token}" if token else node
                    device_id, configuration, raw, ambiguous = (
                        self.device_manager.resolve_legacy_configuration(node, token)
                    )
                    if ambiguous:
                        ambiguous_matches[node] = ambiguous

                    # Avoid attaching two legacy nodes to the same Builder config
                    if configuration in claimed_configs:
                        _LOGGER.warning(
                            "Skipping migration for %s: configuration %s already claimed",
                            node,
                            configuration,
                        )
                        failed_devices[node] = f"Configuration {configuration} already claimed"
                        continue
                    claimed_configs.add(configuration)

                    # Serialize device YAML modification and registration under device lock
                    # (matching internal compile jobs lock)
                    lock = self.device_manager.get_lock(device_id)
                    async with lock:
                        client = self.client
                        orig_yaml: str | None = None
                        cfg_path = esphome_dir / configuration

                        if client is not None:
                            try:
                                orig_yaml = await client.get_config(configuration)
                            except Exception as get_err:
                                err_msg = str(get_err).lower()
                                if "not found" in err_msg or "no such file" in err_msg:
                                    orig_yaml = None
                                else:
                                    raise
                        else:
                            is_file = await self.hass.async_add_executor_job(cfg_path.is_file)
                            if is_file:
                                orig_yaml = await self.hass.async_add_executor_job(
                                    cfg_path.read_text, "utf-8"
                                )

                        if orig_yaml is not None:
                            diff_res = apply_ota_patch(
                                yaml_content=orig_yaml,
                                base_url=self.base_url,
                                slug=slug,
                                target_version=version,
                                node=node,
                            )
                            if diff_res.modified != orig_yaml:
                                if client is None:
                                    raise BuilderConnectionError(
                                        f"Builder client is not connected; cannot safely update {configuration} with concurrency protection"
                                    )
                                # CAS update via builder: expected=orig_yaml detects concurrent modifications
                                await client.update_config(
                                    configuration, diff_res.modified, expected=orig_yaml
                                )
                                migrated_yaml_configs.append(node)
                                _LOGGER.info(
                                    "Migrated YAML for %s (%s) from ota_server to packages.esphome_ota",
                                    node,
                                    configuration,
                                )

                        # Drop a previous bare-node orphan if we resolved to a different stem
                        if device_id != node and self.device_manager.get_device(node):
                            orphan = self.device_manager.get_device(node)
                            if orphan and orphan.configuration in {f"{node}.yaml", node}:
                                await self.device_manager.async_remove_device(node)

                        plat = (
                            raw.get("target_platform", "esp32")
                            if raw
                            else "esp32"
                        )
                        await self.device_manager.async_register_or_update(
                            device_id=device_id,
                            configuration=configuration,
                            name=node,
                            friendly_name=title,
                            target_platform=plat,
                            token=token,
                            has_http_ota=True,
                            managed_version=version,
                            yaml_mode=YAML_MODE_INLINE_PACKAGE,
                        )
                        migrated_devices.append(node)

                except Exception as dev_err:  # noqa: BLE001
                    _LOGGER.warning("Failed migrating device %s: %s", node, dev_err)
                    failed_devices[node] = str(dev_err)

        result: dict[str, Any] = {
            "success": len(failed_devices) == 0,
            "migrated_devices": migrated_devices,
            "migrated_artifacts": migrated_artifacts,
            "migrated_yaml_configs": migrated_yaml_configs,
        }

        if ambiguous_matches:
            result["ambiguous_matches"] = ambiguous_matches

        if failed_devices:
            result["failed_devices"] = failed_devices
            result["error"] = f"Failed migrating {len(failed_devices)} device(s): {', '.join(failed_devices.keys())}"

        if result["success"]:
            await self.storage.async_save_migration(
                {
                    "completed": True,
                    "migrated_at": dt_util.utcnow().isoformat(),
                    "details": result,
                }
            )

        return result
