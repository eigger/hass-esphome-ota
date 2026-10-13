"""Data models and exception definitions for ESPHome OTA."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .const import (
    DEVICE_STATUS_UNMANAGED,
    STAGE_PREPARING,
    YAML_MODE_INLINE_PACKAGE,
)


class EsphomeOtaError(Exception):
    """Base exception for ESPHome OTA errors."""


class BuilderError(EsphomeOtaError):
    """Error communicating with or executing on ESPHome Builder."""


class BuilderConnectionError(BuilderError):
    """Cannot connect to ESPHome Builder trusted listener."""


class BuilderAuthError(BuilderError):
    """Builder listener rejected connection due to authentication requirement."""


class BuilderVersionError(BuilderError):
    """Builder version does not meet minimum requirements."""


class BuilderUnsupportedError(BuilderError):
    """Required Builder API capability is not supported."""


class BuilderTimeoutError(BuilderError):
    """Timeout during Builder command or stream."""


class ConfigConflictError(EsphomeOtaError):
    """CAS conflict when updating device YAML."""


class BinaryValidationError(EsphomeOtaError):
    """Firmware binary validation failed."""


class DeviceNotFoundError(EsphomeOtaError):
    """Managed or Builder device not found."""


class JobCancelledError(EsphomeOtaError):
    """Job was cancelled by user."""


@dataclass
class BuilderCandidate:
    """Represents a discovered ESPHome Builder candidate."""

    slug: str
    name: str
    host: str
    port: int
    source: str  # "dashboard", "supervisor_discovery", "supervisor_addon"
    is_running: bool = True
    requires_auth: bool = False
    version: str | None = None
    dashboard_token: str | None = None

    @property
    def loopback_url(self) -> str:
        """Return the loopback HTTP URL for this candidate."""
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        """Return the loopback WebSocket URL for this candidate."""
        return f"ws://{self.host}:{self.port}/ws"


@dataclass
class BuilderSelection:
    """Persisted Builder selection configuration."""

    slug: str
    name: str
    source: str
    host_hint: str
    port_hint: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuilderSelection:
        return cls(
            slug=data["slug"],
            name=data["name"],
            source=data.get("source", "saved"),
            host_hint=data.get("host_hint", "127.0.0.1"),
            port_hint=data.get("port_hint", 6052),
        )


@dataclass
class ManagedDevice:
    """Device managed or tracked by ESPHome OTA."""

    device_id: str  # Unique ID, usually equal to configuration stem (e.g. "livingroom")
    configuration: str  # Builder YAML filename with extension (e.g. "livingroom.yaml")
    name: str  # ESPHome node name (e.g. "livingroom")
    friendly_name: str
    token: str  # 32-hex token for OTA URL obfuscation
    slug: str  # Public URL slug: "{name}_{token}" or legacy "{name}"
    target_platform: str = "esp32"
    chip_family: str = "ESP32"
    yaml_mode: str = YAML_MODE_INLINE_PACKAGE
    own_project_version: str | None = None
    managed_version: str = "1.0.0"
    last_published_version: str | None = None
    last_installed_version: str | None = None
    last_published_at: str | None = None
    last_installed_at: str | None = None
    has_http_ota: bool = False
    status: str = DEVICE_STATUS_UNMANAGED
    update_entity_id: str | None = None
    auto_hide: bool = True
    publication_cleanup_hours: int | None = None
    hidden_at: str | None = None
    expires_at: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManagedDevice:
        return cls(
            device_id=data["device_id"],
            configuration=data.get("configuration", data["device_id"]),
            name=data.get("name", data["device_id"]),
            friendly_name=data.get("friendly_name", data.get("name", data["device_id"])),
            token=data.get("token", ""),
            slug=data.get("slug", data.get("configuration", data["device_id"])),
            target_platform=data.get("target_platform", "esp32"),
            chip_family=data.get("chip_family", "ESP32"),
            yaml_mode=data.get("yaml_mode", YAML_MODE_INLINE_PACKAGE),
            own_project_version=data.get("own_project_version"),
            managed_version=data.get("managed_version", "1.0.0"),
            last_published_version=data.get("last_published_version"),
            last_installed_version=data.get("last_installed_version"),
            last_published_at=data.get("last_published_at"),
            last_installed_at=data.get("last_installed_at"),
            has_http_ota=data.get("has_http_ota", False),
            status=data.get("status", DEVICE_STATUS_UNMANAGED),
            update_entity_id=data.get("update_entity_id"),
            auto_hide=data.get("auto_hide", True),
            publication_cleanup_hours=data.get("publication_cleanup_hours"),
            hidden_at=data.get("hidden_at"),
            expires_at=data.get("expires_at"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class PipelineCheckpoint:
    """State checkpoint for an active compile/publish pipeline."""

    stage: str
    builder_job_id: str | None = None
    reserved_version: str | None = None
    yaml_hash: str | None = None
    download_token: str | None = None
    artifact_hash: str | None = None
    error: str | None = None


@dataclass
class PipelineJob:
    """Tracks a compile, download, verify, and publish pipeline execution."""

    job_id: str
    device_id: str
    configuration: str
    request_id: str
    stage: str = STAGE_PREPARING
    builder_job_id: str | None = None
    reserved_version: str | None = None
    binary_version: str | None = None
    chip_family: str | None = None
    size: int | None = None
    md5: str | None = None
    sha256: str | None = None
    log_tail: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineJob:
        return cls(
            job_id=data["job_id"],
            device_id=data["device_id"],
            configuration=data.get("configuration", data["device_id"]),
            request_id=data.get("request_id", data["job_id"]),
            stage=data.get("stage", STAGE_PREPARING),
            builder_job_id=data.get("builder_job_id"),
            reserved_version=data.get("reserved_version"),
            binary_version=data.get("binary_version"),
            chip_family=data.get("chip_family"),
            size=data.get("size"),
            md5=data.get("md5"),
            sha256=data.get("sha256"),
            log_tail=data.get("log_tail", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            error=data.get("error"),
            checkpoint=data.get("checkpoint", {}),
        )


@dataclass
class PublishedArtifact:
    """Record of a published firmware binary and manifest."""

    device_id: str
    configuration: str
    version: str
    chip_family: str
    size: int
    md5: str
    sha256: str
    published_at: str
    private_path: str
    public_bin_path: str | None
    public_manifest_path: str
    is_public: bool = True
    build_time: str | None = None
    version_source: str | None = None
    cleanup_hours: int | None = None
    expires_at: str | None = None
    auto_hide: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublishedArtifact:
        return cls(
            device_id=data["device_id"],
            configuration=data.get("configuration", data["device_id"]),
            version=data["version"],
            chip_family=data["chip_family"],
            size=data["size"],
            md5=data["md5"],
            sha256=data["sha256"],
            published_at=data["published_at"],
            private_path=data["private_path"],
            public_bin_path=data.get("public_bin_path"),
            public_manifest_path=data["public_manifest_path"],
            is_public=data.get("is_public", True),
            build_time=data.get("build_time"),
            version_source=data.get("version_source"),
            cleanup_hours=data.get("cleanup_hours"),
            expires_at=data.get("expires_at"),
            auto_hide=data.get("auto_hide", True),
        )


@dataclass
class YamlDiff:
    """Describes planned YAML alterations for OTA setup."""

    original: str
    modified: str
    diff: str
    mode: str
    will_change_ownership: bool = False
    previous_version: str | None = None
    target_version: str | None = None
