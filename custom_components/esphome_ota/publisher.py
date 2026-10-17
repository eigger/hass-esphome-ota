"""Firmware publisher handling private artifact archiving and atomic public publishing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEFAULT_AUTO_CLEANUP_HOURS, DEFAULT_PUBLISH_DIR
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
        self._slug_locks: dict[str, asyncio.Lock] = {}
        self._sync_slug_locks: dict[str, threading.Lock] = {}
        self._sync_locks_guard = threading.Lock()
        self._active_artifacts: dict[str, str] = {}

    def get_current_artifact_id(self, slug: str) -> str | None:
        """Get currently recorded active publication identifier for slug."""
        return self._active_artifacts.get(slug)

    def _get_slug_lock(self, slug: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for a specific slug."""
        if slug not in self._slug_locks:
            self._slug_locks[slug] = asyncio.Lock()
        return self._slug_locks[slug]

    def _get_sync_slug_lock(self, slug: str) -> threading.Lock:
        """Get or create a threading.Lock for a specific slug."""
        with self._sync_locks_guard:
            if slug not in self._sync_slug_locks:
                self._sync_slug_locks[slug] = threading.Lock()
            return self._sync_slug_locks[slug]

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
        loop: asyncio.AbstractEventLoop | None = None,
        done_event: asyncio.Event | None = None,
        started_event: asyncio.Event | None = None,
        cleanup_hours: int = DEFAULT_AUTO_CLEANUP_HOURS,
        auto_hide: bool = True,
    ) -> PublishedArtifact:
        """Synchronous publish implementation executing in executor."""
        with self._get_sync_slug_lock(slug):
            if loop and started_event:
                try:
                    loop.call_soon_threadsafe(started_event.set)
                except RuntimeError:
                    pass
            staged_files: list[Path] = []
            backup_files: list[Path] = []
            backup_bin: Path | None = None
            backup_md5: Path | None = None
            backup_manifest: Path | None = None
            prior_bin_exists = False
            prior_md5_exists = False
            prior_manifest_exists = False

            def _check_validity() -> None:
                if self._unloaded:
                    raise EsphomeOtaError("Publish aborted: integration is unloaded")
                if check_cancelled and check_cancelled():
                    raise EsphomeOtaError("Publish aborted: pipeline job was cancelled")

            try:
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

                # Build ESP-Web-Tools manifest
                published_at = datetime.now(timezone.utc).isoformat()
                manifest: dict[str, Any] = {
                    "name": title or configuration,
                    "version": version,
                    "published_at": published_at,
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

                manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode(
                    "utf-8"
                )

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
                self._active_artifacts[slug] = published_at
            except Exception:
                # Rollback: restore prior files if they existed, or unlink newly placed public files
                if prior_bin_exists and backup_bin is not None and backup_bin.exists():
                    os.replace(backup_bin, public_bin)
                elif not prior_bin_exists and "public_bin" in locals():
                    public_bin.unlink(missing_ok=True)

                if prior_md5_exists and backup_md5 is not None and backup_md5.exists():
                    os.replace(backup_md5, public_md5)
                elif not prior_md5_exists and "public_md5" in locals():
                    public_md5.unlink(missing_ok=True)

                if (
                    prior_manifest_exists
                    and backup_manifest is not None
                    and backup_manifest.exists()
                ):
                    os.replace(backup_manifest, public_manifest)
                elif not prior_manifest_exists and "public_manifest" in locals():
                    public_manifest.unlink(missing_ok=True)

                raise
            finally:
                for sf in staged_files:
                    sf.unlink(missing_ok=True)
                for bf in backup_files:
                    bf.unlink(missing_ok=True)
                if loop and done_event:
                    try:
                        loop.call_soon_threadsafe(done_event.set)
                    except RuntimeError:
                        pass

        _LOGGER.info(
            "Published firmware for %s (slug=%s, version=%s, chip=%s, size=%d bytes)",
            configuration,
            slug,
            version,
            chip_family,
            len(blob),
        )

        return PublishedArtifact(
            device_id=device_id,
            configuration=configuration,
            version=version,
            chip_family=chip_family,
            size=len(blob),
            md5=digest,
            sha256=sha256,
            published_at=published_at,
            private_path=str(private_path),
            public_bin_path=str(public_bin),
            public_manifest_path=str(public_manifest),
            is_public=True,
            build_time=info.build_time,
            version_source=info.version_source,
            cleanup_hours=cleanup_hours,
            expires_at=(
                (
                    datetime.fromisoformat(published_at)
                    + timedelta(hours=cleanup_hours)
                ).isoformat()
                if cleanup_hours > 0
                else None
            ),
            auto_hide=auto_hide,
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
        cleanup_hours: int = DEFAULT_AUTO_CLEANUP_HOURS,
        auto_hide: bool = True,
    ) -> PublishedArtifact:
        """Asynchronously publish firmware binary and manifest."""
        lock = self._get_slug_lock(slug)
        async with lock:
            done_event = asyncio.Event()
            started_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            fut = self.hass.async_add_executor_job(
                self._publish_sync,
                device_id,
                configuration,
                slug,
                blob,
                info,
                title,
                summary,
                check_cancelled,
                loop,
                done_event,
                started_event,
                cleanup_hours,
                auto_hide,
            )
            try:
                return await fut
            finally:
                if fut.cancelled() and not started_event.is_set():
                    try:
                        await asyncio.sleep(0)
                    except asyncio.CancelledError:
                        pass
                if started_event.is_set():
                    while not done_event.is_set():
                        try:
                            await done_event.wait()
                        except asyncio.CancelledError:
                            pass

    def _deactivate_sync(
        self, slug: str, expected_artifact_id: str | None = None
    ) -> bool:
        """Hide/remove public binary from /local while keeping manifest."""
        with self._get_sync_slug_lock(slug):
            if self._unloaded:
                _LOGGER.info(
                    "Skipping deactivation for %s: publisher is unloaded", slug
                )
                return False

            manifest_path = self.www_dir / f"{slug}.json"
            if not manifest_path.exists():
                manifest_path = self.www_dir / f"{slug}.ota.json"
            bin_path = self.www_dir / f"{slug}.ota.bin"
            md5_path = self.www_dir / f"{slug}.ota.bin.md5"

            if expected_artifact_id is not None:
                matches = False
                if manifest_path.exists():
                    try:
                        manifest_data = json.loads(
                            manifest_path.read_text(encoding="utf-8")
                        )
                        m_pub_at = manifest_data.get("published_at")
                        m_version = manifest_data.get("version")
                        builds = manifest_data.get("builds", [])
                        m_md5 = builds[0].get("ota", {}).get("md5") if builds else None
                        if (
                            (m_pub_at and m_pub_at == expected_artifact_id)
                            or (m_version and m_version == expected_artifact_id)
                            or (m_md5 and m_md5 == expected_artifact_id)
                        ):
                            matches = True
                        if m_pub_at:
                            self._active_artifacts[slug] = m_pub_at
                    except (OSError, json.JSONDecodeError) as err:
                        _LOGGER.warning(
                            "Error reading manifest for %s during deactivation: %s",
                            slug,
                            err,
                        )
                else:
                    current_pub_at = self._active_artifacts.get(slug)
                    if current_pub_at and current_pub_at == expected_artifact_id:
                        matches = True

                if not matches:
                    _LOGGER.info(
                        "Skipping deactivation for %s: active publication does not match expected %s",
                        slug,
                        expected_artifact_id,
                    )
                    return False

            removed = False
            if bin_path.exists():
                bin_path.unlink(missing_ok=True)
                removed = True
            if md5_path.exists():
                md5_path.unlink(missing_ok=True)
                removed = True

            if removed:
                self._active_artifacts.pop(slug, None)

            return removed

    async def async_deactivate(
        self, slug: str, expected_artifact_id: str | None = None
    ) -> bool:
        """Remove public binary from /local."""
        if self._unloaded:
            _LOGGER.info("Skipping deactivation for %s: publisher is unloaded", slug)
            return False
        async with self._get_slug_lock(slug):
            if self._unloaded:
                _LOGGER.info(
                    "Skipping deactivation for %s: publisher is unloaded", slug
                )
                return False
            return await self.hass.async_add_executor_job(
                self._deactivate_sync, slug, expected_artifact_id
            )

    async def async_deactivate_with_slug_lock_held(
        self, slug: str, expected_artifact_id: str | None = None
    ) -> bool:
        """Deactivate while the caller holds this slug's async lock."""
        if self._unloaded:
            _LOGGER.info("Skipping deactivation for %s: publisher is unloaded", slug)
            return False
        return await self.hass.async_add_executor_job(
            self._deactivate_sync, slug, expected_artifact_id
        )

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
