"""Firmware publisher handling private artifact archiving and atomic public publishing."""

from __future__ import annotations

import json
import logging
import os
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
    ) -> PublishedArtifact:
        """Synchronous publish implementation executing in executor."""
        self._ensure_dirs()
        digest = info.md5
        sha256 = info.sha256
        version = info.authoritative_version
        chip_family = info.chip_family

        # 1. Archive in private storage
        private_path = self._write_private_artifact(device_id, sha256, blob)

        # 2. Write public files in atomic, manifest-last order
        bin_name = f"{slug}.ota.bin"
        public_bin = self.www_dir / bin_name
        public_md5 = self.www_dir / f"{bin_name}.md5"
        public_manifest = self.www_dir / f"{slug}.json"

        # Write .bin and .md5 first
        self._atomic_write_bytes(public_bin, blob)
        self._atomic_write_bytes(public_md5, digest.encode("ascii"))

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
        # Manifest written last to finalize the atomic publication
        self._atomic_write_bytes(public_manifest, manifest_bytes)

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
