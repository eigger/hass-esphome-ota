"""Isolation adapter for Supervisor-based ESPHome Builder discovery.

Only public Supervisor interfaces (discovery services and add-on info) are used;
the core ESPHome integration's private storage and runtime objects are not.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from ..models import BuilderCandidate

_LOGGER = logging.getLogger(__name__)

KNOWN_ESPHOME_SLUGS = (
    "5c53de3b_esphome",
    "5c53de3b_esphome-dev",
    "5c53de3b_esphome-beta",
    "esphome",
)


def _sanitize_host(host: str) -> str:
    """Ensure host resolves to local loopback if it refers to local container/host."""
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return "127.0.0.1"
    return host


class HaDiscoveryAdapter:
    """Discovers ESPHome Builder instances through the Supervisor."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def async_discover_all(self) -> list[BuilderCandidate]:
        """Collect all candidate Builders from all discovery sources.

        Candidates from the Supervisor discovery service can outlive
        the add-on they point to, so every candidate is dropped when its add-on is
        no longer installed. Candidates for the same add-on slug are merged into one.
        """
        installed = await self._async_installed_addon_slugs()
        by_slug: dict[str, BuilderCandidate] = {}
        seen_keys: set[tuple[str, int]] = set()
        candidates: list[BuilderCandidate] = []

        sources = (
            # 1. Supervisor discovery services
            await self.async_discover_from_supervisor_services(),
            # 2. Supervisor installed add-ons
            await self.async_discover_from_supervisor_addons(),
        )
        for source_candidates in sources:
            for c in source_candidates:
                if installed is not None and c.slug not in installed:
                    _LOGGER.debug(
                        "Ignoring stale %s candidate for uninstalled add-on %s",
                        c.source,
                        c.slug,
                    )
                    continue
                existing = by_slug.get(c.slug)
                if existing is not None:
                    if not existing.version and c.version:
                        existing.version = c.version
                    continue
                key = (c.host, c.port)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                by_slug[c.slug] = c
                candidates.append(c)

        return candidates

    async def _async_installed_addon_slugs(self) -> set[str] | None:
        """Return installed Supervisor add-on slugs, or None when unknown."""
        try:
            from homeassistant.helpers.hassio import is_hassio  # noqa: PLC0415

            if not is_hassio(self.hass):
                return None

            from homeassistant.components.hassio import (  # noqa: PLC0415
                get_addons_info,
            )

            addons = get_addons_info(self.hass)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Installed add-on lookup failed: %s", err)
            return None
        # An empty result usually means Supervisor data is not loaded yet
        return set(addons) if addons else None

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
