"""Constants for the ESPHome OTA integration."""

from __future__ import annotations

DOMAIN = "esphome_ota"

# Configuration options
CONF_BUILDER_SLUG = "builder_slug"
CONF_BUILDER_NAME = "builder_name"
CONF_BASE_URL = "base_url"
CONF_AUTO_CLEANUP_HOURS = "auto_cleanup_hours"
DEFAULT_AUTO_CLEANUP_HOURS = 12

# Storage keys
STORAGE_VERSION = 1
STORAGE_KEY_DEVICES = f"{DOMAIN}.devices"
STORAGE_KEY_JOBS = f"{DOMAIN}.jobs"
STORAGE_KEY_ARTIFACTS = f"{DOMAIN}.artifacts"
STORAGE_KEY_MIGRATION = f"{DOMAIN}.migration"

# Panel & Frontend
PANEL_NAME = "esphome-ota"
PANEL_TITLE = "ESPHome OTA"
PANEL_ICON = "mdi:cellphone-arrow-down"
FRONTEND_URL_PATH = "/esphome_ota_frontend"

# Connection Statuses
STATUS_DISCOVERING = "discovering"
STATUS_CONNECTING = "connecting"
STATUS_READY = "ready"
STATUS_RECONNECTING = "reconnecting"
STATUS_WAITING = "waiting"
STATUS_SELECTION_REQUIRED = "selection_required"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"

# Pipeline Stages
STAGE_PREPARING = "preparing"
STAGE_VALIDATING = "validating"
STAGE_SUBMITTING = "submitting"
STAGE_QUEUED = "queued"
STAGE_BUILDING = "building"
STAGE_DOWNLOADING = "downloading"
STAGE_VERIFYING = "verifying"
STAGE_PUBLISHING = "publishing"
STAGE_PUBLISHED = "published"
STAGE_FAILED = "failed"
STAGE_CANCELLING = "cancelling"
STAGE_CANCELLED = "cancelled"
STAGE_RECOVERY_REQUIRED = "recovery_required"

# Device Installation Statuses
DEVICE_STATUS_UNMANAGED = "unmanaged"
DEVICE_STATUS_READY = "ready"
DEVICE_STATUS_NEEDS_INITIAL_INSTALL = "needs_initial_install"
DEVICE_STATUS_UPDATE_AVAILABLE = "update_available"
DEVICE_STATUS_BUILDING = "building"
DEVICE_STATUS_INSTALLING = "installing"
DEVICE_STATUS_INSTALLED = "installed"
DEVICE_STATUS_INSTALL_FAILED = "install_failed"
DEVICE_STATUS_UNKNOWN = "unknown"

# YAML & Package Modes
YAML_MODE_INLINE_PACKAGE = "inline_package"  # packages.esphome_ota
YAML_MODE_LEGACY_WRAPPER = "legacy_wrapper"  # ota_server/devices/<slug>.yaml

# Publisher Directory
DEFAULT_PUBLISH_DIR = "esphome_ota"
FIRMWARE_OTA_BIN = "firmware.ota.bin"
FIRMWARE_BIN = "firmware.bin"

# Limits & Timeouts
MAX_UPLOAD_SIZE = 16 * 1024 * 1024  # 16 MiB
MAX_LOG_TAIL_LINES = 200
WS_HEARTBEAT_INTERVAL = 30
WS_COMMAND_TIMEOUT = 60
STREAM_POLL_INTERVAL = 20
DOWNLOAD_TIMEOUT_SECONDS = 180
COMPILE_TIMEOUT_SECONDS = 45 * 60
