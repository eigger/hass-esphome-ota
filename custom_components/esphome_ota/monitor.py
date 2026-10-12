"""Installation monitor tracking HA Update entity states and binary expiration."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DEFAULT_AUTO_CLEANUP_HOURS
from .devices import DeviceManager
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
        self._cleanup_tasks: dict[str, asyncio.Task[Any]] = {}

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
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if art.cleanup_hours is None:
                        art.cleanup_hours = self.cleanup_hours
                    if art.expires_at is None and art.cleanup_hours > 0:
                        art.expires_at = (pub_dt + timedelta(hours=art.cleanup_hours)).isoformat()
                    await self.device_manager.storage.async_save_artifact(art.device_id, art)
                    dev = self.device_manager.get_device(art.device_id)
                    if dev and dev.expires_at != art.expires_at:
                        dev.expires_at = art.expires_at
                        await self.device_manager.storage.async_save_devices(
                            self.device_manager._managed_devices
                        )
                    slug = dev.slug if dev else art.device_id
                    self.publisher._active_artifacts[slug] = art.published_at
                    if not art.expires_at:
                        continue
                    expiry_dt = datetime.fromisoformat(art.expires_at)
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                    remaining = (expiry_dt - now).total_seconds()
                    if remaining <= 0:
                        self.hass.async_create_task(
                            self._async_deactivate_artifact(art.device_id, slug, art.published_at)
                        )
                    else:
                        self.schedule_cleanup(
                            art.device_id,
                            slug,
                            delay_seconds=remaining,
                            artifact_id=art.published_at,
                        )
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.debug(
                        "Could not restore cleanup timer for %s: %s", art.device_id, ex
                    )

    async def async_refresh_monitoring(self) -> None:
        """Scan devices and attach listeners to any newly discovered Update entities."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        devices = self.device_manager.list_all()

        for dev_data in devices:
            device_id = dev_data["device_id"]
            dev_name = dev_data["name"]
            dev_friendly = dev_data.get("friendly_name") or dev_name
            norm_name = dev_name.lower().replace("-", "_")
            norm_title = re.sub(
                r"[^a-z0-9_]",
                "",
                dev_friendly.lower().replace(" ", "_").replace("-", "_"),
            )

            matched_entity_id: str | None = None
            dev = self.device_manager.get_device(device_id)

            # 1. Identify matching HA device in Device Registry
            matching_ha_device_id: str | None = None
            # Pass A: Match via explicit device identifiers (e.g. esphome, mqtt, etc.)
            for ha_dev in dev_reg.devices:
                for _domain, ident in ha_dev.identifiers:
                    if str(ident).lower() in (
                        dev_name.lower(),
                        device_id.lower(),
                        norm_name,
                        norm_title,
                    ):
                        matching_ha_device_id = ha_dev.id
                        break
                if matching_ha_device_id:
                    break

            # Pass B: Match via device name if no identifier matched directly
            if not matching_ha_device_id:
                for ha_dev in dev_reg.devices:
                    if (
                        ha_dev.name
                        and ha_dev.name.lower()
                        in (
                            dev_name.lower(),
                            norm_name,
                            dev_friendly.lower(),
                            norm_title,
                        )
                    ):
                        # Avoid matching a device whose identifier explicitly belongs to a different node
                        has_conflicting_ident = False
                        for _domain, ident in ha_dev.identifiers:
                            ident_str = str(ident).lower()
                            if ident_str not in (
                                dev_name.lower(),
                                device_id.lower(),
                                norm_name,
                                norm_title,
                            ) and (
                                ident_str.startswith(f"{dev_name.lower()}_")
                                or ident_str.startswith(f"{norm_name}_")
                                or f"_{norm_name}_" in ident_str
                            ):
                                has_conflicting_ident = True
                                break
                        if not has_conflicting_ident:
                            matching_ha_device_id = ha_dev.id
                            break

            # Helper to strictly verify an update entity and its device connection
            def _is_valid_update_entity(ent: er.RegistryEntry | None) -> bool:
                if not ent or ent.domain != "update":
                    return False
                if ent.device_id:
                    ent_dev = dev_reg.async_get(ent.device_id)
                    if not ent_dev:
                        return False
                    if matching_ha_device_id and ent_dev.id != matching_ha_device_id:
                        return False
                    for _domain, ident in ent_dev.identifiers:
                        ident_str = str(ident).lower()
                        if ident_str not in (
                            dev_name.lower(),
                            device_id.lower(),
                            norm_name,
                            norm_title,
                        ) and (
                            ident_str.startswith(f"{dev_name.lower()}_")
                            or ident_str.startswith(f"{norm_name}_")
                            or f"_{norm_name}_" in ident_str
                        ):
                            return False
                return True

            # 0. Check if device already has a valid known update_entity_id
            if dev and dev.update_entity_id:
                known_ent = ent_reg.async_get(dev.update_entity_id)
                if _is_valid_update_entity(known_ent):
                    matched_entity_id = dev.update_entity_id

            # 1. First attempt: match entities attached directly to the matching HA device
            if not matched_entity_id and matching_ha_device_id:
                for entity in ent_reg.entities.values():
                    if (
                        entity.domain == "update"
                        and entity.device_id == matching_ha_device_id
                    ):
                        matched_entity_id = entity.entity_id
                        break

            # 2. Second attempt: match via exact naming patterns with strict device validation
            if not matched_entity_id:
                candidate_eids = [
                    f"update.{norm_name}",
                    f"update.{norm_name}_firmware",
                    f"update.{norm_name}_ota_update",
                    f"update.{norm_name}_update",
                ]
                if norm_title and norm_title != norm_name:
                    candidate_eids.extend([
                        f"update.{norm_title}",
                        f"update.{norm_title}_firmware",
                        f"update.{norm_title}_ota_update",
                        f"update.{norm_title}_update",
                    ])

                for cand in candidate_eids:
                    ent = ent_reg.async_get(cand)
                    if _is_valid_update_entity(ent):
                        matched_entity_id = cand
                        break

            # 3. Third attempt: match via entity original_name or unique_id
            if not matched_entity_id:
                for entity in ent_reg.entities.values():
                    if not _is_valid_update_entity(entity):
                        continue

                    obj_id = entity.entity_id.split(".", 1)[-1].lower()
                    if obj_id in (
                        norm_name,
                        f"{norm_name}_firmware",
                        f"{norm_name}_ota_update",
                        f"{norm_name}_update",
                        norm_title,
                        f"{norm_title}_firmware",
                        f"{norm_title}_ota_update",
                        f"{norm_title}_update",
                    ):
                        matched_entity_id = entity.entity_id
                        break
                    if entity.unique_id:
                        u_id = entity.unique_id.lower()
                        if u_id.startswith(
                            (
                                f"{norm_name}_",
                                f"{norm_name}-",
                                f"{norm_title}_",
                                f"{norm_title}-",
                            )
                        ):
                            matched_entity_id = entity.entity_id
                            break
                    if entity.original_name:
                        orig = entity.original_name.lower()
                        # Device-specific names matching node or friendly name
                        if orig in (
                            norm_name,
                            f"{norm_name} firmware",
                            f"{norm_name} update",
                            dev_friendly.lower(),
                            f"{dev_friendly.lower()} firmware",
                            f"{dev_friendly.lower()} update",
                        ):
                            matched_entity_id = entity.entity_id
                            break
                        # Generic common names like "Firmware" ONLY if confirmed attached to matching HA device
                        if matching_ha_device_id and entity.device_id == matching_ha_device_id:
                            if orig in ("firmware", "firmware update", "ota update"):
                                matched_entity_id = entity.entity_id
                                break

            if matched_entity_id:
                dev = self.device_manager.get_device(device_id)
                if dev and dev.update_entity_id != matched_entity_id:
                    dev.update_entity_id = matched_entity_id
                    self.hass.async_create_task(
                        self.device_manager.storage.async_save_devices(
                            self.device_manager._managed_devices
                        )
                    )
                if matched_entity_id not in self._monitored_entities:
                    self._monitored_entities.add(matched_entity_id)
                    self._attach_listener(device_id, matched_entity_id)

                # Immediately sync initial state if entity is already active in HA
                current_state = self.hass.states.get(matched_entity_id)
                if current_state and current_state.state not in (
                    "unavailable",
                    "unknown",
                ):
                    attrs = current_state.attributes
                    installed_ver = attrs.get("installed_version")
                    in_progress = attrs.get("in_progress", False)
                    if dev and installed_ver and not in_progress:
                        if dev.last_installed_version != installed_ver:
                            await self.device_manager.async_mark_installed(
                                device_id, installed_ver
                            )
                            if (
                                dev.last_published_version
                                and installed_ver == dev.last_published_version
                            ):
                                if self.event_callback:
                                    self.event_callback(
                                        "installation_verified",
                                        {
                                            "device_id": device_id,
                                            "version": installed_ver,
                                            "devices": self.device_manager.list_all(),
                                        },
                                    )
                            elif self.event_callback:
                                self.event_callback(
                                    "devices_updated",
                                    {"devices": self.device_manager.list_all()},
                                )

    async def async_refresh_entity(self, device_id: str) -> None:
        """Trigger immediate state update for the device's Update entity."""
        dev = self.device_manager.get_device(device_id)
        entity_id = dev.update_entity_id if dev else None
        if not entity_id:
            await self.async_refresh_monitoring()
            dev = self.device_manager.get_device(device_id)
            entity_id = dev.update_entity_id if dev else None

        if entity_id:
            try:
                await self.hass.services.async_call(
                    "homeassistant",
                    "update_entity",
                    {"entity_id": entity_id},
                    blocking=False,
                )
                _LOGGER.info(
                    "Triggered immediate update check for %s (%s)",
                    device_id,
                    entity_id,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Could not trigger update_entity for %s: %s",
                    entity_id,
                    err,
                )

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

            if in_progress:
                return

            dev = self.device_manager.get_device(device_id)
            if not dev or not installed_version:
                return

            # Check if device installed the published firmware
            if (
                dev.last_published_version
                and installed_version == dev.last_published_version
                and not in_progress
                and dev.last_installed_version != installed_version
            ):
                _LOGGER.info(
                    "Installation verified for %s at version %s",
                    device_id,
                    installed_version,
                )

                async def _mark_and_notify_verified() -> None:
                    async with self.device_manager.get_lock(device_id):
                        current_dev = self.device_manager.get_device(device_id)
                        artifacts = await self.device_manager.storage.async_load_artifacts()
                        art = artifacts.get(device_id)
                        # The state event may have been queued just before a new
                        # publication completed. Only act on the artifact that
                        # actually matches the installed version now.
                        if (
                            not current_dev
                            or current_dev.last_published_version != installed_version
                            or not art
                            or art.version != installed_version
                            or current_dev.last_installed_version == installed_version
                        ):
                            return
                        publication_id = art.published_at
                        await self.device_manager.async_mark_installed(
                            device_id, installed_version
                        )
                        if art.is_public and art.auto_hide and publication_id:
                            if await self._async_deactivate_artifact(
                                device_id,
                                current_dev.slug,
                                publication_id,
                                lock_held=True,
                            ):
                                timer = self._cleanup_timers.pop(device_id, None)
                                if timer:
                                    timer.cancel()
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

                self.hass.async_create_task(_mark_and_notify_verified())
            elif dev.last_installed_version != installed_version:
                _LOGGER.info(
                    "Discovered installed version %s for %s",
                    installed_version,
                    device_id,
                )

                async def _mark_and_notify_updated() -> None:
                    await self.device_manager.async_mark_installed(
                        device_id, installed_version
                    )
                    if self.event_callback:
                        self.event_callback(
                            "devices_updated",
                            {"devices": self.device_manager.list_all()},
                        )

                self.hass.async_create_task(_mark_and_notify_updated())

        unsub = async_track_state_change_event(self.hass, [entity_id], _state_changed)
        self._unsub_listeners.append(unsub)

    def schedule_cleanup(
        self,
        device_id: str,
        slug: str,
        delay_seconds: float | None = None,
        artifact_id: str | None = None,
        cleanup_hours: int | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Schedule automatic public binary deactivation after expiry period."""
        self.cancel_cleanup(device_id)

        target_artifact_id = artifact_id
        if target_artifact_id is None:
            target_artifact_id = self.publisher.get_current_artifact_id(slug)

        if delay_seconds is None and expires_at:
            expiry_dt = datetime.fromisoformat(expires_at)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            delay_seconds = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
        if delay_seconds is None:
            resolved_hours = self.cleanup_hours if cleanup_hours is None else cleanup_hours
            if resolved_hours <= 0:
                return
            delay = max(0.0, float(resolved_hours * 3600))
        else:
            delay = max(0.0, float(delay_seconds))

        @callback
        def _run_cleanup() -> None:
            _LOGGER.info(
                "Running automatic cleanup for %s (slug=%s, target_artifact=%s)",
                device_id,
                slug,
                target_artifact_id,
            )

            async def _deactivate_and_notify() -> None:
                await self._async_deactivate_artifact(
                    device_id,
                    slug,
                    target_artifact_id,
                    expected_expires_at=expires_at,
                )

            task = self.hass.async_create_task(_deactivate_and_notify())
            self._cleanup_tasks[device_id] = task

        timer = self.hass.loop.call_later(delay, _run_cleanup)
        self._cleanup_timers[device_id] = timer

    async def _async_deactivate_artifact(
        self,
        device_id: str,
        slug: str,
        artifact_id: str | None,
        *,
        lock_held: bool = False,
        expected_expires_at: str | None = None,
    ) -> bool:
        """Hide only the publication that still matches the requested artifact ID."""
        artifacts = await self.device_manager.storage.async_load_artifacts()
        art = artifacts.get(device_id)
        if not art or (artifact_id and art.published_at != artifact_id):
            return False
        if art.is_public:
            marked_private = await self.device_manager.storage.async_mark_artifact_private_if_current(
                device_id,
                art.published_at,
                expected_expires_at=expected_expires_at,
            )
            if not marked_private:
                return False
        removed = await self.publisher.async_deactivate(slug, expected_artifact_id=artifact_id)
        public_bin = (
            Path(art.public_bin_path)
            if art.public_bin_path
            else self.publisher.www_dir / f"{slug}.ota.bin"
        )
        if not public_bin.exists():
            public_bin = self.publisher.www_dir / f"{slug}.ota.bin"
        is_private = removed or not public_bin.exists()
        if is_private and art.is_public:
            if self.event_callback:
                # Notify immediately after removing the public file; metadata
                # cleanup below can wait for a build's device lock.
                self.event_callback("devices_updated", {"devices": self.device_manager.list_all()})

            async def _clear_expiry_if_still_current() -> None:
                current_artifacts = await self.device_manager.storage.async_load_artifacts()
                current_art = current_artifacts.get(device_id)
                dev = self.device_manager.get_device(device_id)
                if (
                    current_art
                    and current_art.published_at == art.published_at
                    and not current_art.is_public
                    and dev
                    and dev.last_published_version == art.version
                    and dev.expires_at == art.expires_at
                ):
                    dev.expires_at = None
                    await self.device_manager.storage.async_save_devices(
                        self.device_manager._managed_devices
                    )

            if lock_held:
                await _clear_expiry_if_still_current()
            else:
                # File deactivation and the conditional artifact update happen
                # before this lock, so a long-running build cannot extend the
                # public lifetime past its deadline.
                async with self.device_manager.get_lock(device_id):
                    await _clear_expiry_if_still_current()
        return is_private

    def cancel_cleanup(self, device_id: str) -> None:
        """Cancel any scheduled cleanup timer for a device."""
        timer = self._cleanup_timers.pop(device_id, None)
        if timer:
            timer.cancel()
        task = self._cleanup_tasks.pop(device_id, None)
        if task and not task.done():
            task.cancel()

    def async_unload(self) -> None:
        """Clean up all listeners and timers on unload."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        self._monitored_entities.clear()

        for timer in self._cleanup_timers.values():
            timer.cancel()
        self._cleanup_timers.clear()

        for task in self._cleanup_tasks.values():
            if not task.done():
                task.cancel()
        self._cleanup_tasks.clear()
