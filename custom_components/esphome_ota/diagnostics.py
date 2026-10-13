"""Diagnostics support for ESPHome OTA integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized diagnostics for a config entry."""
    entry_data = hass.data.get(DOMAIN, {})
    manager = entry_data.get("manager")

    if not manager:
        return {"status": "unloaded"}

    # Redact tokens and confidential info
    devices_summary: list[dict[str, Any]] = []
    for dev in manager.device_manager.list_all():
        devices_summary.append(
            {
                "device_id": dev["device_id"],
                "configuration": dev["configuration"],
                "is_managed": dev["is_managed"],
                "target_platform": dev["target_platform"],
                "chip_family": dev["chip_family"],
                "status": dev["status"],
                "has_http_ota": dev["has_http_ota"],
                "has_token": bool(dev.get("token")),
                "last_published_version": dev.get("last_published_version"),
                "last_installed_version": dev.get("last_installed_version"),
                "last_published_at": dev.get("last_published_at"),
                "last_installed_at": dev.get("last_installed_at"),
            }
        )

    builder_info = None
    if manager.resolver.active_candidate:
        c = manager.resolver.active_candidate
        builder_info = {
            "slug": c.slug,
            "name": c.name,
            "host": c.host,
            "port": c.port,
            "source": c.source,
            "is_running": c.is_running,
            "requires_auth": c.requires_auth,
            "version": c.version,
        }

    jobs_summary = [
        {
            "job_id": j.job_id,
            "device_id": j.device_id,
            "stage": j.stage,
            "reserved_version": j.reserved_version,
            "binary_version": j.binary_version,
            "error": j.error,
        }
        for j in manager.job_runner.list_jobs()
    ]

    return {
        "status": manager.resolver.status,
        "builder": builder_info,
        "candidate_count": len(manager.resolver.candidates),
        "devices": devices_summary,
        "jobs": jobs_summary,
        "entry_data": {
            "entry_id": entry.entry_id,
            "builder_slug": entry.data.get("builder_slug"),
        },
    }
