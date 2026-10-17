"""Isolation adapter for Home Assistant ESPHome dashboard and Supervisor discovery."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant

from ..models import BuilderCandidate

_LOGGER = logging.getLogger(__name__)

KNOWN_ESPHOME_SLUGS = (
    "5c53de3b_esphome",
    "5c53de3b_esphome-dev",
    "5c53de3b_esphome-beta",
    "esphome",
)


def _is_loopback(host: str) -> bool:
    """Check if host is a loopback address."""
    return host in ("127.0.0.1", "localhost", "::1")


def _sanitize_host(host: str) -> str:
    """Ensure host resolves to local loopback if it refers to local container/host."""
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return "127.0.0.1"
    return host


class HaDiscoveryAdapter:
    """Discovers ESPHome Builder instances from Home Assistant runtime and Supervisor."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_discover_all(self) -> list[BuilderCandidate]:
        """Collect all candidate Builders from all discovery sources."""
        candidates: list[BuilderCandidate] = []
        seen_keys: set[tuple[str, int]] = set()

        # 1. HA ESPHome integration dashboard
        dashboard_candidates = await self.async_discover_from_esphome_dashboard()
        for c in dashboard_candidates:
            key = (c.host, c.port)
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(c)

        # 2. Supervisor discovery services
        service_candidates = await self.async_discover_from_supervisor_services()
        for c in service_candidates:
            key = (c.host, c.port)
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(c)

        # 3. Supervisor installed add-ons
        addon_candidates = await self.async_discover_from_supervisor_addons()
        for c in addon_candidates:
            key = (c.host, c.port)
            if key not in seen_keys:
                seen_keys.add(key)
                candidates.append(c)

        return candidates

    async def async_discover_from_esphome_dashboard(self) -> list[BuilderCandidate]:
        """Discover candidate from HA's built-in ESPHome integration dashboard manager."""
        candidates: list[BuilderCandidate] = []
        try:
            from homeassistant.components.esphome.dashboard import (  # noqa: PLC0415
                async_get_dashboard,
            )

            coordinator = async_get_dashboard(self.hass)
            if coordinator and getattr(coordinator, "url", None):
                parsed = urlparse(coordinator.url)
                host = _sanitize_host(parsed.hostname or "127.0.0.1")
                port = parsed.port
                slug = getattr(coordinator, "addon_slug", "esphome")
                if port:
                    candidates.append(
                        BuilderCandidate(
                            slug=slug,
                            name=f"ESPHome Dashboard ({slug})",
                            host=host,
                            port=port,
                            source="dashboard",
                            is_running=True,
                        )
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("ESPHome dashboard discovery unavailable: %s", err)

        # Also attempt to read stored dashboard info if manager hasn't initialized coordinator yet
        if not candidates:
            try:
                from homeassistant.helpers.storage import Store  # noqa: PLC0415

                store: Store[dict[str, Any]] = Store(self.hass, 1, "esphome.dashboard")
                data = await store.async_load()
                if data and (info := data.get("info")):
                    host = _sanitize_host(info.get("host", "127.0.0.1"))
                    port = info.get("port")
                    slug = info.get("addon_slug", "esphome")
                    if port and isinstance(port, int):
                        candidates.append(
                            BuilderCandidate(
                                slug=slug,
                                name=f"ESPHome Dashboard ({slug})",
                                host=host,
                                port=port,
                                source="dashboard",
                                is_running=True,
                            )
                        )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("ESPHome dashboard storage check failed: %s", err)

        return candidates

    async def async_discover_from_supervisor_services(self) -> list[BuilderCandidate]:
        """Discover candidate from Supervisor discovery API."""
        candidates: list[BuilderCandidate] = []
        try:
            from homeassistant.helpers.hassio import is_hassio  # noqa: PLC0415

            if not is_hassio(self.hass):
                return []

            from homeassistant.components.hassio import (  # noqa: PLC0415
                get_supervisor_client,
            )

            client = get_supervisor_client(self.hass)
            discoveries = await client.discovery.list()
            for disc in discoveries:
                if disc.service == "esphome" or "esphome" in disc.addon.lower():
                    cfg = disc.config or {}
                    host = _sanitize_host(cfg.get("host", "127.0.0.1"))
                    port = cfg.get("port")
                    if port and isinstance(port, int):
                        candidates.append(
                            BuilderCandidate(
                                slug=disc.addon,
                                name=f"ESPHome ({disc.addon})",
                                host=host,
                                port=port,
                                source="supervisor_discovery",
                                is_running=True,
                            )
                        )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Supervisor service discovery failed: %s", err)

        return candidates

    async def async_discover_from_supervisor_addons(self) -> list[BuilderCandidate]:
        """Discover candidates from installed add-on info in Supervisor."""
        candidates: list[BuilderCandidate] = []
        try:
            from homeassistant.helpers.hassio import is_hassio  # noqa: PLC0415

            if not is_hassio(self.hass):
                return []

            from homeassistant.components.hassio import (  # noqa: PLC0415
                get_addons_info,
                get_supervisor_client,
            )

            addons = get_addons_info(self.hass)
            client = get_supervisor_client(self.hass)

            for slug, info in addons.items():
                if not info:
                    continue
                is_esphome = (
                    slug in KNOWN_ESPHOME_SLUGS
                    or "esphome" in slug.lower()
                    or "esphome" in str(info.get("name", "")).lower()
                )
                if not is_esphome:
                    continue

                state = info.get("state")
                is_running = state in ("started", "running")

                # Trusted loopback listener port is typically the ingress_port
                ingress_port = info.get("ingress_port")
                if not ingress_port and is_running:
                    # Query detailed addon info if ingress_port wasn't populated in summary
                    try:
                        detailed = await client.addons.addon_info(slug)
                        ingress_port = detailed.ingress_port
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.debug(
                            "Failed querying addon_info for %s: %s", slug, err
                        )

                if ingress_port and isinstance(ingress_port, int) and ingress_port > 0:
                    candidates.append(
                        BuilderCandidate(
                            slug=slug,
                            name=str(info.get("name") or slug),
                            host="127.0.0.1",
                            port=ingress_port,
                            source="supervisor_addon",
                            is_running=is_running,
                            version=str(info.get("version") or ""),
                        )
                    )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Supervisor add-on discovery failed: %s", err)

        return candidates
