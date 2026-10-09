"""Central orchestrator manager for ESPHome OTA integration."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .builder.client import BuilderClient
from .builder.resolver import BuilderResolver
from .const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_NAME,
    CONF_BUILDER_SLUG,
    DEFAULT_AUTO_CLEANUP_HOURS,
    DEFAULT_PUBLISH_DIR,
    STATUS_RECONNECTING,
)
from .devices import DeviceManager
from .http import FirmwareUploadView
from .jobs import JobRunner
from .migration import MigrationManager
from .models import BuilderSelection
from .monitor import InstallationMonitor
from .panel import PanelManager
from .publisher import ArtifactPublisher
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)

BACKOFF_STEPS = [2, 5, 10, 30, 60]


class OtaManager:
    """Coordinates discovery, builder connection, devices, jobs, publisher, and UI."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)

        # Config entry values
        self.base_url = (
            entry.options.get(CONF_BASE_URL)
            or entry.data.get(CONF_BASE_URL)
            or ""
        )
        self.cleanup_hours = entry.options.get(
            CONF_AUTO_CLEANUP_HOURS, DEFAULT_AUTO_CLEANUP_HOURS
        )

        saved_selection = None
        slug = entry.data.get(CONF_BUILDER_SLUG)
        if slug:
            name = entry.data.get(CONF_BUILDER_NAME, slug or "ESPHome Builder")
            host_hint = entry.data.get("builder_host", "")
            port_hint = entry.data.get("builder_port", 0)
            saved_selection = BuilderSelection(
                slug=slug,
                name=name,
                source="config_entry",
                host_hint=host_hint,
                port_hint=port_hint,
            )

        # Subsystems
        self.storage = StorageManager(hass)
        self.publisher = ArtifactPublisher(hass, DEFAULT_PUBLISH_DIR)
        self.device_manager = DeviceManager(hass, self.storage)
        self.monitor = InstallationMonitor(
            hass,
            self.device_manager,
            self.publisher,
            self.cleanup_hours,
            self._dispatch_event,
        )
        self.job_runner = JobRunner(
            hass,
            self.storage,
            self.device_manager,
            self.publisher,
            self._dispatch_event,
            self.monitor,
        )
        self.migration_manager = MigrationManager(
            hass, self.storage, self.device_manager, self.publisher
        )
        self.resolver = BuilderResolver(hass, self.session, saved_selection)
        self.panel_manager = PanelManager(hass)
        self.upload_view = FirmwareUploadView(hass, self)

        self._subscribers: list[Callable[[str, dict[str, Any]], None]] = []
        self._refresh_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._unloaded = False
        self._reconnect_backoff_index = 0

    def add_subscriber(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Add WebSocket subscriber callback."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    def _dispatch_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Dispatch event to all active WebSocket subscribers."""
        for sub in list(self._subscribers):
            try:
                sub(event_type, data)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error notifying subscriber: %s", err)

    def _attach_connection_listener(self, client: BuilderClient) -> None:
        """Attach connection drop listener to client connection."""
        client.conn.on_disconnect = self._handle_connection_lost

    def _handle_connection_lost(self) -> None:
        """Handle unexpected disconnect from Builder."""
        if self._unloaded:
            return
        _LOGGER.warning("ESPHome Builder connection lost. Initiating automatic reconnect.")
        self.resolver.status = STATUS_RECONNECTING
        self._dispatch_event(
            "status_changed",
            {"status": STATUS_RECONNECTING, "candidate": None},
        )
        self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        """Start background reconnection loop if not already running."""
        if self._unloaded:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Repeatedly attempt re-discovery and re-connection with backoff and jitter."""
        while not self._unloaded:
            if self.resolver.active_client and self.resolver.active_client.conn.is_connected:
                return

            delay = BACKOFF_STEPS[
                min(self._reconnect_backoff_index, len(BACKOFF_STEPS) - 1)
            ] * random.uniform(0.8, 1.2)
            self._reconnect_backoff_index += 1
            _LOGGER.debug("Waiting %.1fs before retrying ESPHome Builder connection...", delay)

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

            if self._unloaded:
                return

            try:
                client = await self.resolver.async_resolve()
                self._attach_connection_listener(client)
                devices = await client.list_devices()
                self.device_manager.update_builder_devices(devices)
                self._reconnect_backoff_index = 0
                _LOGGER.info(
                    "Successfully reconnected to ESPHome Builder (%s)",
                    self.resolver.active_candidate.slug if self.resolver.active_candidate else "",
                )
                self._dispatch_event(
                    "status_changed",
                    {
                        "status": self.resolver.status,
                        "candidate": (
                            self.resolver.active_candidate.slug
                            if self.resolver.active_candidate
                            else None
                        ),
                    },
                )
                self._dispatch_event(
                    "devices_updated",
                    {"devices": self.device_manager.list_all()},
                )
                await self.job_runner.async_resume_jobs(client, self.base_url)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Builder reconnect attempt failed: %s", err)
                self._dispatch_event(
                    "status_changed",
                    {"status": self.resolver.status, "candidate": None},
                )

    async def async_setup(self) -> None:
        """Initialize all subsystems and connect to ESPHome Builder."""
        # 1. Load persisted data
        await self.device_manager.async_load()
        await self.job_runner.async_load()

        # 2. Register HTTP view and custom panel
        self.hass.http.register_view(self.upload_view)
        await self.panel_manager.async_register()

        # 3. Attempt Builder resolution & initial device refresh
        try:
            client = await self.resolver.async_resolve()
            self._attach_connection_listener(client)
            devices = await client.list_devices()
            self.device_manager.update_builder_devices(devices)
            await self.job_runner.async_resume_jobs(client, self.base_url)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Initial ESPHome Builder connection deferred: %s", err)
            self._start_reconnect_loop()

        # 4. Start installation monitor
        await self.monitor.async_setup()

    async def async_unload(self) -> None:
        """Clean up resources on integration unload."""
        self._unloaded = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self.monitor.async_unload()
        self.panel_manager.async_unregister()
        await self.resolver.async_disconnect()
        self._subscribers.clear()

    async def async_reconnect(self) -> None:
        """Trigger manual re-discovery and re-connection to Builder."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_backoff_index = 0
        await self.resolver.async_disconnect()
        try:
            client = await self.resolver.async_resolve()
            self._attach_connection_listener(client)
            devices = await client.list_devices()
            self.device_manager.update_builder_devices(devices)
            self._dispatch_event(
                "status_changed",
                {
                    "status": self.resolver.status,
                    "candidate": (
                        self.resolver.active_candidate.slug
                        if self.resolver.active_candidate
                        else None
                    ),
                },
            )
            self._dispatch_event("devices_updated", {"devices": self.device_manager.list_all()})
            await self.job_runner.async_resume_jobs(client, self.base_url)
        except Exception as err:
            _LOGGER.warning("Manual reconnect attempt failed: %s", err)
            self._start_reconnect_loop()
            raise

    async def refresh_devices(self) -> None:
        """Fetch updated device list from Builder."""
        client = self.resolver.active_client
        if client:
            try:
                devices = await client.list_devices()
                self.device_manager.update_builder_devices(devices)
                self._dispatch_event(
                    "devices_updated", {"devices": self.device_manager.list_all()}
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Failed refreshing devices: %s", err)
