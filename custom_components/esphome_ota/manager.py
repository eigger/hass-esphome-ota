"""Central orchestrator manager for ESPHome OTA integration."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .builder.client import BuilderClient
from .builder.resolver import BuilderResolver
from .const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_HOST,
    CONF_BUILDER_NAME,
    CONF_BUILDER_PORT,
    CONF_BUILDER_SLUG,
    DEFAULT_AUTO_CLEANUP_HOURS,
    DEFAULT_PUBLISH_DIR,
    DOMAIN,
    STATUS_RECONNECTING,
    STATUS_SELECTION_REQUIRED,
)
from .devices import DeviceManager
from .jobs import JobRunner
from .models import BuilderAuthError, BuilderForbiddenError, BuilderSelection
from .monitor import InstallationMonitor
from .packages import generate_token, is_valid_token, public_slug
from .panel import PanelManager
from .publisher import ArtifactPublisher, async_unlink_paths
from .redaction import install_redaction, mask_slug
from .storage import StorageManager

_LOGGER = logging.getLogger(__name__)
install_redaction(_LOGGER)

BACKOFF_STEPS = [2, 5, 10, 30, 60]
# Failures that need user action (Builder requires auth, several Builders and none
# selected) are re-checked rarely instead of hammering the Builder every minute.
PERMANENT_FAILURE_INTERVAL = 600


class OtaManager:
    """Coordinates discovery, builder connection, devices, jobs, publisher, and UI."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)

        # Config entry values
        self.base_url = (
            entry.options.get(CONF_BASE_URL) or entry.data.get(CONF_BASE_URL) or ""
        )
        self.cleanup_hours = entry.options.get(
            CONF_AUTO_CLEANUP_HOURS, DEFAULT_AUTO_CLEANUP_HOURS
        )

        saved_selection = None
        opt_slug = entry.options.get(CONF_BUILDER_SLUG)
        if opt_slug in (None, "", "auto"):
            opt_slug = None
        data_slug = entry.data.get(CONF_BUILDER_SLUG)
        if data_slug in (None, "", "auto"):
            data_slug = None

        slug = opt_slug or data_slug
        if slug:
            name = (
                entry.options.get(CONF_BUILDER_NAME)
                or entry.data.get(CONF_BUILDER_NAME)
                or slug
            )
            host_hint = entry.options.get(CONF_BUILDER_HOST) or entry.data.get(
                CONF_BUILDER_HOST, ""
            )
            port_hint = entry.options.get(CONF_BUILDER_PORT) or entry.data.get(
                CONF_BUILDER_PORT, 0
            )
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
        self.device_manager.public_scan_listener = self._on_public_scan_changed
        self.monitor = InstallationMonitor(
            hass,
            self.device_manager,
            self.publisher,
            self.cleanup_hours,
            self.dispatch_event,
        )
        self.job_runner = JobRunner(
            hass,
            self.storage,
            self.device_manager,
            self.publisher,
            self.dispatch_event,
            self.monitor,
        )
        self.resolver = BuilderResolver(hass, self.session, saved_selection)
        self.panel_manager = PanelManager(hass)

        self._subscribers: list[Callable[[str, dict[str, Any]], None]] = []
        self._refresh_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._unloaded = False
        self.ready = False
        self._reconnect_backoff_index = 0
        self._permanent_failure = False
        self._suppress_reload_count = 0

    def should_suppress_reload(self) -> bool:
        """Check and consume a suppress reload request."""
        if self._suppress_reload_count > 0:
            self._suppress_reload_count -= 1
            return True
        return False

    def add_subscriber(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Add WebSocket subscriber callback."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    def _on_public_scan_changed(self) -> None:
        """Push the refreshed device list after a background publish-dir rescan."""
        if self._unloaded:
            return
        self.dispatch_event(
            "devices_updated", {"devices": self.device_manager.list_all()}
        )

    def dispatch_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Dispatch event to all active WebSocket subscribers."""
        for sub in list(self._subscribers):
            try:
                sub(event_type, data)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error notifying subscriber: %s", err)

    def _candidates_payload(self) -> list[dict[str, Any]]:
        """Serialize the discovered Builder candidates for status events."""
        return [
            {
                "slug": cand.slug,
                "name": cand.name,
                "host": cand.host,
                "port": cand.port,
                "source": cand.source,
                "is_running": cand.is_running,
            }
            for cand in self.resolver.candidates
        ]

    def _attach_connection_listener(self, client: BuilderClient) -> None:
        """Attach connection drop listener to client connection."""
        client.conn.on_disconnect = self._handle_connection_lost

    def _handle_connection_lost(self) -> None:
        """Handle unexpected disconnect from Builder."""
        if self._unloaded:
            return
        _LOGGER.warning(
            "ESPHome Builder connection lost. Initiating automatic reconnect."
        )
        self.resolver.status = STATUS_RECONNECTING
        self.dispatch_event(
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
        self._reconnect_task = self.entry.async_create_background_task(
            self.hass, self._reconnect_loop(), "esphome_ota_reconnect"
        )

    def _note_connect_failure(self, err: Exception) -> None:
        """Remember whether a failure needs user action rather than a quick retry."""
        self._permanent_failure = (
            isinstance(err, (BuilderAuthError, BuilderForbiddenError))
            or self.resolver.status == STATUS_SELECTION_REQUIRED
        )

    async def _cancel_reconnect_task(self) -> None:
        """Cancel the reconnect loop and wait until it has finished."""
        task = self._reconnect_task
        self._reconnect_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _reconnect_loop(self) -> None:
        """Repeatedly attempt re-discovery and re-connection with backoff and jitter."""
        while not self._unloaded:
            if (
                self.resolver.active_client
                and self.resolver.active_client.conn.is_connected
            ):
                return

            base_delay = (
                PERMANENT_FAILURE_INTERVAL
                if self._permanent_failure
                else BACKOFF_STEPS[
                    min(self._reconnect_backoff_index, len(BACKOFF_STEPS) - 1)
                ]
            )
            delay = base_delay * random.uniform(0.8, 1.2)
            self._reconnect_backoff_index += 1
            _LOGGER.debug(
                "Waiting %.1fs before retrying ESPHome Builder connection...", delay
            )

            await asyncio.sleep(delay)

            if self._unloaded:
                return

            try:
                client = await self.resolver.async_resolve()
                if self._unloaded:
                    await self.resolver.async_disconnect()
                    return
                self._attach_connection_listener(client)
                devices = await client.list_devices()
                if self._unloaded:
                    await self.resolver.async_disconnect()
                    return
                self.device_manager.update_builder_devices(devices)
                self._reconnect_backoff_index = 0
                self._permanent_failure = False
                _LOGGER.info(
                    "Successfully reconnected to ESPHome Builder (%s)",
                    self.resolver.active_candidate.slug
                    if self.resolver.active_candidate
                    else "",
                )
                self.dispatch_event(
                    "status_changed",
                    {
                        "status": self.resolver.status,
                        "candidate": (
                            self.resolver.active_candidate.slug
                            if self.resolver.active_candidate
                            else None
                        ),
                        "candidates": self._candidates_payload(),
                    },
                )
                self.dispatch_event(
                    "devices_updated",
                    {"devices": self.device_manager.list_all()},
                )
                if self._unloaded:
                    await self.resolver.async_disconnect()
                    return
                await self.job_runner.async_resume_jobs(client, self.base_url)
                return
            except Exception as err:  # noqa: BLE001
                if self._unloaded:
                    return
                self._note_connect_failure(err)
                _LOGGER.debug("Builder reconnect attempt failed: %s", err)

                self.dispatch_event(
                    "status_changed",
                    {
                        "status": self.resolver.status,
                        "candidate": None,
                        "candidates": self._candidates_payload(),
                    },
                )

    async def async_setup(self) -> None:
        """Initialize all subsystems and connect to ESPHome Builder."""
        # 1. Load persisted data
        await self.device_manager.async_load()
        try:
            await self.storage.async_remove_migration_record()
        except OSError as err:
            _LOGGER.debug("Could not remove the legacy import record: %s", err)
        await self._async_rotate_weak_tokens()
        await self._async_warn_guessable_public_files()
        await self.job_runner.async_load()

        # 2. Register custom panel (the upload view is registered once in async_setup)
        await self.panel_manager.async_register()

        # 3. Attempt Builder resolution & initial device refresh
        try:
            client = await self.resolver.async_resolve()
            self._attach_connection_listener(client)
            devices = await client.list_devices()
            self.device_manager.update_builder_devices(devices)
            await self.job_runner.async_resume_jobs(client, self.base_url)
        except Exception as err:  # noqa: BLE001
            self._note_connect_failure(err)
            _LOGGER.warning("Initial ESPHome Builder connection deferred: %s", err)
            self._start_reconnect_loop()

        # 4. Start installation monitor
        await self.monitor.async_setup()
        self.ready = True

    async def _async_rotate_weak_tokens(self) -> None:
        """Give every managed device a strong public-URL token.

        Records from older releases (including devices imported from the
        legacy add-on, whose import has since been removed) may have no token
        or a short one, which makes ``/local/<publish dir>/<slug>``
        guessable. Such firmware contains Wi-Fi and API secrets, so the weak
        public files are taken down and a fresh random token is assigned. The
        next build re-patches the device YAML with the new ``ota_slug``; the
        device must then be installed once through ESPHome Builder.
        """
        devices = self.device_manager.managed_devices
        weak = [dev for dev in devices.values() if not is_valid_token(dev.token)]
        if not weak:
            return
        artifacts = await self.storage.async_load_artifacts()
        rotated: list[str] = []
        for dev in weak:
            old_slug = dev.slug
            # Rotate even when the cleanup below fails, so nothing is ever
            # published again under the guessable slug.
            try:
                await self.publisher.async_deactivate(old_slug)
                www = self.publisher.www_dir
                await async_unlink_paths(
                    self.hass,
                    www / f"{old_slug}.ota.bin",
                    www / f"{old_slug}.ota.bin.md5",
                    www / f"{old_slug}.json",
                    www / f"{old_slug}.ota.json",
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Could not remove the public files of %s at its old guessable "
                    "URL; delete %s.* from www/%s manually: %s",
                    dev.name,
                    mask_slug(old_slug),
                    DEFAULT_PUBLISH_DIR,
                    err,
                )
            dev.token = generate_token()
            dev.slug = public_slug(dev.name, dev.token)
            dev.expires_at = None
            artifact = artifacts.get(dev.device_id)
            if artifact is not None and artifact.is_public:
                artifact.is_public = False
                artifact.public_bin_path = None
                await self.storage.async_save_artifact(dev.device_id, artifact)
            rotated.append(dev.name)
        if not rotated:
            return
        await self.storage.async_save_devices(devices)
        _LOGGER.warning(
            "Assigned a new random public URL token to %s; rebuild these devices "
            "and install the firmware once through ESPHome Builder so they use "
            "the new URL",
            ", ".join(sorted(rotated)),
        )

    @staticmethod
    def _guessable_public_slugs_sync(www: Path) -> list[str]:
        """List public binaries whose slug has no strong token (blocking)."""
        found: list[str] = []
        try:
            with os.scandir(www) as entries:
                for entry in entries:
                    name = entry.name
                    if not name.endswith(".ota.bin") or not entry.is_file():
                        continue
                    slug = name[: -len(".ota.bin")]
                    token = slug.rsplit("_", 1)[-1] if "_" in slug else ""
                    if not is_valid_token(token):
                        found.append(slug)
        except OSError:
            return []
        return sorted(found)

    async def _async_warn_guessable_public_files(self) -> None:
        """Warn about public firmware (e.g. left by the legacy add-on) at guessable URLs."""
        slugs = await self.hass.async_add_executor_job(
            self._guessable_public_slugs_sync, self.publisher.www_dir
        )
        if slugs:
            _LOGGER.warning(
                "Public firmware with a guessable URL was found in www/%s (%s). "
                "It is served without authentication and may contain Wi-Fi and "
                "API secrets; delete these files if they are not needed",
                DEFAULT_PUBLISH_DIR,
                ", ".join(mask_slug(slug) for slug in slugs),
            )

    async def async_unload(self) -> None:
        """Clean up resources on integration unload."""
        self._unloaded = True
        self._suppress_reload_count = 0
        # Tell open panels so they can resubscribe once the entry is back.
        self.dispatch_event("unloaded", {})
        self.publisher.async_unload()
        await self._cancel_reconnect_task()
        await self.job_runner.async_unload()
        self.monitor.async_unload()
        self.device_manager.async_unload()
        self.panel_manager.async_unregister()
        await self.resolver.async_disconnect()
        self._subscribers.clear()

    async def async_select_builder(self, slug: str) -> None:
        """Select a builder candidate post-installation, persist to entry, and reconnect."""
        if slug == "auto":
            slug = ""

        name = slug or "ESPHome Builder"
        host_hint = ""
        port_hint = 0
        if slug:
            for c in self.resolver.candidates:
                if c.slug == slug:
                    name = c.name
                    host_hint = c.host
                    port_hint = c.port
                    break

        new_data = dict(self.entry.data)
        new_options = dict(self.entry.options)
        if slug:
            new_data[CONF_BUILDER_SLUG] = slug
            new_data[CONF_BUILDER_NAME] = name
            if host_hint:
                new_data[CONF_BUILDER_HOST] = host_hint
            if port_hint:
                new_data[CONF_BUILDER_PORT] = port_hint
            new_options[CONF_BUILDER_SLUG] = slug
            new_options[CONF_BUILDER_NAME] = name
            if host_hint:
                new_options[CONF_BUILDER_HOST] = host_hint
            if port_hint:
                new_options[CONF_BUILDER_PORT] = port_hint
            self.resolver.saved_selection = BuilderSelection(
                slug=slug,
                name=name,
                source="config_entry",
                host_hint=host_hint,
                port_hint=port_hint,
            )
        else:
            new_data.pop(CONF_BUILDER_SLUG, None)
            new_data.pop(CONF_BUILDER_NAME, None)
            new_data.pop(CONF_BUILDER_HOST, None)
            new_data.pop(CONF_BUILDER_PORT, None)
            new_options.pop(CONF_BUILDER_SLUG, None)
            new_options.pop(CONF_BUILDER_NAME, None)
            new_options.pop(CONF_BUILDER_HOST, None)
            new_options.pop(CONF_BUILDER_PORT, None)
            self.resolver.saved_selection = None

        self._suppress_reload_count += 1
        try:
            changed = self.hass.config_entries.async_update_entry(
                self.entry,
                data=new_data,
                options=new_options,
            )
            if not changed:
                self._suppress_reload_count = max(0, self._suppress_reload_count - 1)
        except Exception:
            self._suppress_reload_count = max(0, self._suppress_reload_count - 1)
            raise

        if self._unloaded:
            return

        await self.async_reconnect()

    async def async_reconnect(self) -> None:
        """Trigger manual re-discovery and re-connection to Builder."""
        if self._unloaded:
            return
        await self._cancel_reconnect_task()
        self._reconnect_backoff_index = 0
        self._permanent_failure = False
        await self.resolver.async_disconnect()
        if self._unloaded:
            return
        try:
            client = await self.resolver.async_resolve()
            if self._unloaded:
                await self.resolver.async_disconnect()
                return
            self._attach_connection_listener(client)
            devices = await client.list_devices()
            if self._unloaded:
                await self.resolver.async_disconnect()
                return
            self.device_manager.update_builder_devices(devices)
            self.dispatch_event(
                "status_changed",
                {
                    "status": self.resolver.status,
                    "candidate": (
                        self.resolver.active_candidate.slug
                        if self.resolver.active_candidate
                        else None
                    ),
                    "candidates": self._candidates_payload(),
                },
            )
            self.dispatch_event(
                "devices_updated", {"devices": self.device_manager.list_all()}
            )
            if self._unloaded:
                await self.resolver.async_disconnect()
                return
            await self.job_runner.async_resume_jobs(client, self.base_url)
        except Exception as err:
            if self._unloaded:
                return
            self._note_connect_failure(err)
            _LOGGER.warning("Manual reconnect attempt failed: %s", err)
            self.dispatch_event(
                "status_changed",
                {
                    "status": self.resolver.status,
                    "candidate": None,
                    "candidates": self._candidates_payload(),
                    "error": str(err),
                },
            )
            self._start_reconnect_loop()
            raise

    async def refresh_devices(self) -> bool:
        """Fetch updated device list from Builder.

        Returns True when the list was refreshed, False when there is no active
        Builder connection or the fetch failed.
        """
        if self._unloaded:
            return False
        client = self.resolver.active_client
        if not client:
            return False
        try:
            devices = await client.list_devices()
            if self._unloaded:
                return False
            self.device_manager.update_builder_devices(devices)
            self.dispatch_event(
                "devices_updated", {"devices": self.device_manager.list_all()}
            )
        except Exception as err:  # noqa: BLE001
            if self._unloaded:
                return False
            _LOGGER.debug("Failed refreshing devices: %s", err)
            return False
        return True


type OtaConfigEntry = ConfigEntry[OtaManager]


def get_loaded_manager(hass: HomeAssistant) -> OtaManager | None:
    """Return the live manager, or None when not set up or already unloaded.

    The manager is usable (and the panel visible) while the entry is still in
    SETUP_IN_PROGRESS, so liveness is decided by runtime_data plus ``_unloaded``
    rather than by the entry state.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        manager = getattr(entry, "runtime_data", None)
        if manager is not None and not manager._unloaded:
            return manager
    return None
