"""Firmware publisher handling private artifact archiving and atomic public publishing."""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEFAULT_PUBLISH_DIR
from .firmware import BinaryInfo
from .models import EsphomeOtaError, PublishedArtifact

_LOGGER = logging.getLogger(__name__)


class ArtifactPublisher:
    """Publishes firmware binaries and manifests to Home Assistant's /local path."""

    def __init__(
        self,
        hass: HomeAssistant,
        publish_dir: str = DEFAULT_PUBLISH_DIR,
    ) -> None:
        self.hass = hass
        self.publish_dir = publish_dir
        self.www_dir = Path(hass.config.path("www", publish_dir))
        self.private_base_dir = Path(hass.config.path("esphome_ota", "firmware"))
        self._unloaded = False

    def async_unload(self) -> None:
        """Mark publisher as unloaded."""
        self._unloaded = True

    def _ensure_dirs(self) -> None:
        """Ensure public www and private storage directories exist."""
        self.www_dir.mkdir(parents=True, exist_ok=True)
        self.private_base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write_bytes(target: Path, content: bytes) -> None:
        """Write content to temporary file and atomically replace target."""
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f"{target.suffix}.tmp.{os.getpid()}")
        try:
            tmp.write_bytes(content)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _write_private_artifact(
        self,
        device_id: str,
        sha256: str,
        blob: bytes,
    ) -> Path:
        """Save binary into private configuration directory."""
        dev_dir = self.private_base_dir / device_id
        dev_dir.mkdir(parents=True, exist_ok=True)
        target = dev_dir / f"{sha256}.bin"
        self._atomic_write_bytes(target, blob)
        return target

    def _publish_sync(
        self,
        device_id: str,
        configuration: str,
        slug: str,
        blob: bytes,
        info: BinaryInfo,
        title: str = "",
        summary: str = "",
        check_cancelled: Callable[[], bool] | None = None,
    ) -> PublishedArtifact:
        """Synchronous publish implementation executing in executor."""
        def _check_validity() -> None:
            if self._unloaded:
                raise EsphomeOtaError("Publish aborted: integration is unloaded")
            if check_cancelled and check_cancelled():
                raise EsphomeOtaError("Publish aborted: pipeline job was cancelled")

        _check_validity()
        self._ensure_dirs()
        digest = info.md5
        sha256 = info.sha256
        version = info.authoritative_version
        chip_family = info.chip_family

        # 1. Archive in private storage
        private_path = self._write_private_artifact(device_id, sha256, blob)

        _check_validity()

        # 2. Write public files in atomic, manifest-last order
        bin_name = f"{slug}.ota.bin"
        public_bin = self.www_dir / bin_name
        public_md5 = self.www_dir / f"{bin_name}.md5"
        public_manifest = self.www_dir / f"{slug}.json"

        prior_bin_exists = public_bin.exists()
        prior_md5_exists = public_md5.exists()
        prior_manifest_exists = public_manifest.exists()

        tmp_id = uuid.uuid4().hex[:8]
        stage_bin = self.www_dir / f"{bin_name}.stage_{tmp_id}"
        stage_md5 = self.www_dir / f"{bin_name}.md5.stage_{tmp_id}"
        stage_manifest = self.www_dir / f"{slug}.json.stage_{tmp_id}"
        staged_files = [stage_bin, stage_md5, stage_manifest]

        backup_bin = self.www_dir / f"{bin_name}.bak_{tmp_id}"
        backup_md5 = self.www_dir / f"{bin_name}.md5.bak_{tmp_id}"
        backup_manifest = self.www_dir / f"{slug}.json.bak_{tmp_id}"
        backup_files = [backup_bin, backup_md5, backup_manifest]

        try:
            # Build ESP-Web-Tools manifest
            manifest: dict[str, Any] = {
                "name": title or configuration,
                "version": version,
                "builds": [
                    {
                        "chipFamily": chip_family,
                        "ota": {
                            "md5": digest,
                            "path": f"{bin_name}?v={digest[:8]}",
                            "summary": summary or "Built by ESPHome OTA",
                        },
                    }
                ],
            }
            if info.build_time:
                manifest["build_time"] = info.build_time
            if info.version_source:
                manifest["version_source"] = info.version_source

            manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")

            # 1. Stage files first
            stage_bin.write_bytes(blob)
            stage_md5.write_bytes(digest.encode("ascii"))
            stage_manifest.write_bytes(manifest_bytes)

            # 2. Backup prior existing files for rollback if cancelled/failed during replacement
            if prior_bin_exists:
                shutil.copyfile(public_bin, backup_bin)
            if prior_md5_exists:
                shutil.copyfile(public_md5, backup_md5)
            if prior_manifest_exists:
                shutil.copyfile(public_manifest, backup_manifest)

            # 3. Check validity before starting public file replacements
            _check_validity()

            # 4. Atomically replace binary and MD5
            os.replace(stage_bin, public_bin)
            os.replace(stage_md5, public_md5)

            # 5. Check validity right before manifest finalization (the atomic commit point)
            _check_validity()

            # 6. Final atomic commit: replace manifest
            os.replace(stage_manifest, public_manifest)
        except Exception:
            # Rollback: restore prior files if they existed, or unlink newly placed public files
            if prior_bin_exists and backup_bin.exists():
                os.replace(backup_bin, public_bin)
            elif not prior_bin_exists:
                public_bin.unlink(missing_ok=True)

            if prior_md5_exists and backup_md5.exists():
                os.replace(backup_md5, public_md5)
            elif not prior_md5_exists:
                public_md5.unlink(missing_ok=True)

            if prior_manifest_exists and backup_manifest.exists():
                os.replace(backup_manifest, public_manifest)
            elif not prior_manifest_exists:
                public_manifest.unlink(missing_ok=True)

            raise
        finally:
            for sf in staged_files:
                sf.unlink(missing_ok=True)
            for bf in backup_files:
                bf.unlink(missing_ok=True)

        _LOGGER.info(
            "Published firmware for %s (slug=%s, version=%s, chip=%s, size=%d bytes)",
            configuration,
            slug,
            version,
            chip_family,
            len(blob),
        )

        from datetime import datetime, timezone

        return PublishedArtifact(
            device_id=device_id,
            configuration=configuration,
            version=version,
            chip_family=chip_family,
            size=len(blob),
            md5=digest,
            sha256=sha256,
            published_at=datetime.now(timezone.utc).isoformat(),
            private_path=str(private_path),
            public_bin_path=str(public_bin),
            public_manifest_path=str(public_manifest),
            is_public=True,
            build_time=info.build_time,
            version_source=info.version_source,
        )

    async def async_publish(
        self,
        device_id: str,
        configuration: str,
        slug: str,
        blob: bytes,
        info: BinaryInfo,
        title: str = "",
        summary: str = "",
        check_cancelled: Callable[[], bool] | None = None,
    ) -> PublishedArtifact:
        """Asynchronously publish firmware binary and manifest."""
        return await self.hass.async_add_executor_job(
            self._publish_sync,
            device_id,
            configuration,
            slug,
            blob,
            info,
            title,
            summary,
            check_cancelled,
        )

    def _deactivate_sync(self, slug: str) -> bool:
        """Hide/remove public binary from /local while keeping manifest."""
        bin_path = self.www_dir / f"{slug}.ota.bin"
        md5_path = self.www_dir / f"{slug}.ota.bin.md5"

        removed = False
        if bin_path.exists():
            bin_path.unlink(missing_ok=True)
            removed = True
        if md5_path.exists():
            md5_path.unlink(missing_ok=True)

        return removed

    async def async_deactivate(self, slug: str) -> bool:
        """Remove public binary from /local."""
        return await self.hass.async_add_executor_job(self._deactivate_sync, slug)

    def _load_private_artifact_sync(self, private_path: str) -> bytes:
        """Load private binary bytes."""
        path = Path(private_path)
        if not path.is_file():
            raise EsphomeOtaError(f"Private artifact file not found: {private_path}")
        return path.read_bytes()

    async def async_load_private_artifact(self, private_path: str) -> bytes:
        """Load archived private artifact bytes for re-publishing."""
        return await self.hass.async_add_executor_job(
            self._load_private_artifact_sync, private_path
        )
