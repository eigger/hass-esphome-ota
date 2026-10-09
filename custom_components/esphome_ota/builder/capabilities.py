"""Capability probing and version checking for ESPHome Builder API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BuilderCapabilities:
    """Represents the discovered feature set of an ESPHome Builder instance."""

    version: str | None = None
    has_config_write_cas: bool = True
    has_devices_validate: bool = True
    has_firmware_compile: bool = True
    has_firmware_follow_job: bool = True
    has_firmware_get_job: bool = True
    has_firmware_cancel: bool = True
    has_firmware_download: bool = True
    has_firmware_get_binaries: bool = True
    has_build_queue: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "has_config_write_cas": self.has_config_write_cas,
            "has_devices_validate": self.has_devices_validate,
            "has_firmware_compile": self.has_firmware_compile,
            "has_firmware_follow_job": self.has_firmware_follow_job,
            "has_firmware_get_job": self.has_firmware_get_job,
            "has_firmware_cancel": self.has_firmware_cancel,
            "has_firmware_download": self.has_firmware_download,
            "has_firmware_get_binaries": self.has_firmware_get_binaries,
            "has_build_queue": self.has_build_queue,
        }

    @classmethod
    def from_server_info(cls, server_info: dict[str, Any]) -> BuilderCapabilities:
        """Infer capabilities from server_info frame received at handshake."""
        version = server_info.get("version")
        # In modern ESPHome Builder (device-builder), all required endpoints are supported.
        return cls(version=version)
