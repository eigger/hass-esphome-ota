"""Installation monitor tracking HA Update entity states and binary expiration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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
        self._cleanup_timers: dict[str, asyncio.TimerHandle] = {}

    async def async_setup(self) -> None:
        """Discover matching Update entities and attach state listeners."""
        registry = er.async_get(self.hass)
        devices = self.device_manager.list_all()

        for dev_data in devices:
            device_id = dev_data["device_id"]
            slug = dev_data["slug"]
            dev_name = dev_data["name"]

            # Search entity registry for matching update entity
            matched_entity_id: str | None = None
            for entity in registry.entities.values():
                if entity.domain != "update":
                    continue
                # Match by entity unique_id or entity_id naming convention
                if (
                    dev_name in entity.entity_id
                    or (entity.original_name and dev_name in entity.original_name.lower())
                ):
                    matched_entity_id = entity.entity_id
                    break

            if matched_entity_id:
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
                    self.hass.async_create_task(
                        self.device_manager.async_mark_installed(
                            device_id, installed_version
                        )
                    )
                    if self.event_callback:
                        self.event_callback(
                            "installation_verified",
                            {"device_id": device_id, "version": installed_version},
                        )

        unsub = async_track_state_change_event(self.hass, [entity_id], _state_changed)
        self._unsub_listeners.append(unsub)

    def schedule_cleanup(self, device_id: str, slug: str) -> None:
        """Schedule automatic public binary deactivation after expiry period."""
        self.cancel_cleanup(device_id)

        delay_seconds = self.cleanup_hours * 3600

        @callback
        def _run_cleanup() -> None:
            _LOGGER.info("Running automatic cleanup for %s (slug=%s)", device_id, slug)
            self.hass.async_create_task(self.publisher.async_deactivate(slug))

        timer = self.hass.loop.call_later(delay_seconds, _run_cleanup)
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

        for timer in self._cleanup_timers.values():
            timer.cancel()
        self._cleanup_timers.clear()
