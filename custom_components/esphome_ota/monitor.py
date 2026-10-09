"""Installation monitor tracking HA Update entity states and binary expiration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DEFAULT_AUTO_CLEANUP_HOURS
from .devices import DeviceManager
from .models import ManagedDevice
from .publisher import ArtifactPublisher

_LOGGER = logging.getLogger(__name__)


class InstallationMonitor:
    """Monitors Home Assistant Update entity states and handles automatic firmware deactivation."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_manager: DeviceManager,
        publisher: ArtifactPublisher,
        cleanup_hours: int = DEFAULT_AUTO_CLEANUP_HOURS,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.hass = hass
        self.device_manager = device_manager
        self.publisher = publisher
        self.cleanup_hours = cleanup_hours
        self.event_callback = event_callback
        self._unsub_listeners: list[Callable[[], None]] = []
        self._monitored_entities: set[str] = set()
        self._cleanup_timers: dict[str, asyncio.TimerHandle] = {}

    async def async_setup(self) -> None:
        """Discover matching Update entities, listen for new entities, and restore cleanup timers."""
        await self.async_refresh_monitoring()

        # Listen for new or updated entities in the entity registry
        @callback
        def _on_entity_registry_updated(event: Event) -> None:
            self.hass.async_create_task(self.async_refresh_monitoring())

        unsub_er = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity_registry_updated
        )
        self._unsub_listeners.append(unsub_er)

        # Restore cleanup timers for existing public artifacts from storage
        artifacts = await self.device_manager.storage.async_load_artifacts()
        now = datetime.now(timezone.utc)
        for art in artifacts.values():
            if art.is_public and art.public_bin_path and art.published_at:
                try:
                    pub_dt = datetime.fromisoformat(art.published_at)
                    elapsed = (now - pub_dt).total_seconds()
                    remaining = (self.cleanup_hours * 3600) - elapsed
                    dev = self.device_manager.get_device(art.device_id)
                    slug = dev.slug if dev else art.device_id
                    if remaining <= 0:
                        self.hass.async_create_task(self.publisher.async_deactivate(slug))
                    else:
                        self.schedule_cleanup(art.device_id, slug, delay_seconds=remaining)
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug("Could not restore cleanup timer for %s: %s", art.device_id, ex)

    async def async_refresh_monitoring(self) -> None:
        """Scan devices and attach listeners to any newly discovered Update entities."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        devices = self.device_manager.list_all()

        for dev_data in devices:
            device_id = dev_data["device_id"]
            dev_name = dev_data["name"]
            norm_name = dev_name.lower().replace("-", "_")

            matched_entity_id: str | None = None

            # 1. First attempt: match via Home Assistant Device Registry
            matching_ha_device_id: str | None = None
            for ha_dev in dev_reg.devices:
                # Only consider devices belonging to the ESPHome domain
                if not any(domain == "esphome" for domain, _ in ha_dev.identifiers):
                    continue

                matched = False
                for domain, ident in ha_dev.identifiers:
                    if domain == "esphome" and str(ident).lower() in (
                        dev_name.lower(),
                        device_id.lower(),
                        norm_name,
                    ):
                        matched = True
                        break
                if not matched and ha_dev.name and ha_dev.name.lower() in (
                    dev_name.lower(),
                    norm_name,
                    dev_data.get("friendly_name", "").lower(),
                ):
                    matched = True

                if matched:
                    matching_ha_device_id = ha_dev.id
                    break

            if matching_ha_device_id:
                for entity in ent_reg.entities.values():
                    if (
                        entity.domain == "update"
                        and entity.platform == "esphome"
                        and entity.device_id == matching_ha_device_id
                    ):
                        matched_entity_id = entity.entity_id
                        break

            # 2. Second attempt: match via exact naming patterns
            # Strictly require entity.platform == "esphome" and verify device connection relationship
            if not matched_entity_id:
                for entity in ent_reg.entities.values():
                    if entity.domain != "update" or entity.platform != "esphome":
                        continue

                    # If entity is attached to a HA device, verify that device is an ESPHome device
                    if entity.device_id:
                        ent_dev = dev_reg.async_get(entity.device_id)
                        if ent_dev:
                            if not any(d == "esphome" for d, _ in ent_dev.identifiers):
                                continue
                            if matching_ha_device_id and ent_dev.id != matching_ha_device_id:
                                continue

                    obj_id = entity.entity_id.split(".", 1)[-1].lower()
                    if obj_id in (norm_name, f"{norm_name}_firmware", f"{norm_name}_update"):
                        matched_entity_id = entity.entity_id
                        break
                    if entity.unique_id:
                        u_id = entity.unique_id.lower()
                        if u_id.startswith((f"{norm_name}_", f"{norm_name}-")):
                            matched_entity_id = entity.entity_id
                            break
                    if entity.original_name:
                        orig = entity.original_name.lower()
                        if orig in (
                            norm_name,
                            f"{norm_name} firmware",
                            f"{norm_name} update",
                            dev_data.get("friendly_name", "").lower(),
                            f"{dev_data.get('friendly_name', '').lower()} firmware",
                        ):
                            matched_entity_id = entity.entity_id
                            break

            if matched_entity_id and matched_entity_id not in self._monitored_entities:
                self._monitored_entities.add(matched_entity_id)
                self._attach_listener(device_id, matched_entity_id)

    def _attach_listener(self, device_id: str, entity_id: str) -> None:
        """Attach state change listener for an Update entity."""

        @callback
        def _state_changed(event: Event) -> None:
            new_state = event.data.get("new_state")
            if not new_state or new_state.state in ("unavailable", "unknown"):
                return

            attrs = new_state.attributes
            installed_version = attrs.get("installed_version")
            in_progress = attrs.get("in_progress", False)

            dev = self.device_manager.get_device(device_id)
            if not dev or not installed_version:
                return

            # Check if device installed the published firmware
            if dev.last_published_version and installed_version == dev.last_published_version:
                if not in_progress:
                    _LOGGER.info(
                        "Installation verified for %s at version %s",
                        device_id,
                        installed_version,
                    )

                    async def _mark_and_notify() -> None:
                        await self.device_manager.async_mark_installed(
                            device_id, installed_version
                        )
                        if self.event_callback:
                            self.event_callback(
                                "devices_updated",
                                {"devices": self.device_manager.list_all()},
                            )
                            self.event_callback(
                                "installation_verified",
                                {
                                    "device_id": device_id,
                                    "version": installed_version,
                                    "devices": self.device_manager.list_all(),
                                },
                            )

                    self.hass.async_create_task(_mark_and_notify())

        unsub = async_track_state_change_event(self.hass, [entity_id], _state_changed)
        self._unsub_listeners.append(unsub)

    def schedule_cleanup(
        self, device_id: str, slug: str, delay_seconds: float | None = None
    ) -> None:
        """Schedule automatic public binary deactivation after expiry period."""
        self.cancel_cleanup(device_id)

        if delay_seconds is None:
            delay = max(0.0, float(self.cleanup_hours * 3600))
        else:
            delay = max(0.0, float(delay_seconds))

        @callback
        def _run_cleanup() -> None:
            _LOGGER.info("Running automatic cleanup for %s (slug=%s)", device_id, slug)
            self.hass.async_create_task(self.publisher.async_deactivate(slug))

        timer = self.hass.loop.call_later(delay, _run_cleanup)
        self._cleanup_timers[device_id] = timer

    def cancel_cleanup(self, device_id: str) -> None:
        """Cancel any scheduled cleanup timer for a device."""
        timer = self._cleanup_timers.pop(device_id, None)
        if timer:
            timer.cancel()

    def async_unload(self) -> None:
        """Clean up all listeners and timers on unload."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        self._monitored_entities.clear()

        for timer in self._cleanup_timers.values():
            timer.cancel()
        self._cleanup_timers.clear()
