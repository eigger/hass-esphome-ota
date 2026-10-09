"""Resolver for locating and selecting ESPHome Builder instances."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant

from ..const import (
    STATUS_CONNECTING,
    STATUS_DISCOVERING,
    STATUS_READY,
    STATUS_RECONNECTING,
    STATUS_SELECTION_REQUIRED,
    STATUS_UNSUPPORTED,
    STATUS_WAITING,
)
from ..models import (
    BuilderAuthError,
    BuilderCandidate,
    BuilderConnectionError,
    BuilderSelection,
)
from .client import BuilderClient
from .connection import BuilderConnection
from .ha_discovery import HaDiscoveryAdapter, KNOWN_ESPHOME_SLUGS

_LOGGER = logging.getLogger(__name__)


class BuilderResolver:
    """Discovers, validates, and resolves the target ESPHome Builder instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        saved_selection: BuilderSelection | None = None,
    ) -> None:
        self.hass = hass
        self.session = session
        self.saved_selection = saved_selection
        self.discovery_adapter = HaDiscoveryAdapter(hass)
        self.status = STATUS_DISCOVERING
        self.active_candidate: BuilderCandidate | None = None
        self.active_client: BuilderClient | None = None
        self.candidates: list[BuilderCandidate] = []

    async def async_resolve(self) -> BuilderClient:
        """Resolve and connect to the chosen Builder instance.

        Returns an active, verified BuilderClient.
        """
        self.status = STATUS_DISCOVERING
        self.candidates = await self.discovery_adapter.async_discover_all()

        candidate = self._choose_candidate()
        if not candidate:
            if len(self.candidates) > 1 and not self.saved_selection:
                self.status = STATUS_SELECTION_REQUIRED
                raise BuilderConnectionError("Multiple Builder candidates found. Selection required.")
            self.status = STATUS_WAITING
            raise BuilderConnectionError("No ESPHome Builder candidate found. Waiting for Builder to start.")

        self.status = STATUS_CONNECTING
        client = await self._connect_and_probe(candidate)
        self.active_candidate = candidate
        self.active_client = client
        self.status = STATUS_READY
        return client

    def _choose_candidate(self) -> BuilderCandidate | None:
        """Apply selection rules to choose a candidate."""
        # 1. Saved selection takes precedence
        if self.saved_selection:
            for c in self.candidates:
                if c.slug == self.saved_selection.slug:
                    return c

            # Check if saved slug is a known alias matching discovered candidates
            if self.saved_selection.slug in KNOWN_ESPHOME_SLUGS:
                matching = [c for c in self.candidates if c.slug in KNOWN_ESPHOME_SLUGS]
                if len(matching) == 1:
                    return matching[0]

            # If a single candidate was discovered, use it with its discovered port
            if len(self.candidates) == 1:
                return self.candidates[0]

            # If no candidates discovered at all, use stored host/port hint
            if not self.candidates and self.saved_selection.host_hint and self.saved_selection.port_hint:
                return BuilderCandidate(
                    slug=self.saved_selection.slug,
                    name=self.saved_selection.name,
                    host=self.saved_selection.host_hint,
                    port=self.saved_selection.port_hint,
                    source="hint",
                )
            return None

        # 2. HA ESPHome dashboard candidate currently in use
        dashboard_candidates = [c for c in self.candidates if c.source == "dashboard"]
        if len(dashboard_candidates) == 1:
            return dashboard_candidates[0]

        # 3. Single candidate
        if len(self.candidates) == 1:
            return self.candidates[0]

        # Multiple candidates with no saved choice
        return None

    async def _connect_and_probe(self, candidate: BuilderCandidate) -> BuilderClient:
        """Connect to candidate and run read-only probe."""
        conn = BuilderConnection(candidate.host, candidate.port, self.session)
        try:
            await conn.connect()
            client = BuilderClient(conn)
            # Read-only probe
            await client.list_devices()
            return client
        except BuilderAuthError:
            self.status = STATUS_UNSUPPORTED
            await conn.disconnect()
            raise
        except (BuilderConnectionError, Exception):
            await conn.disconnect()
            raise

    async def async_disconnect(self) -> None:
        """Disconnect active connection."""
        if self.active_client and self.active_client.conn:
            await self.active_client.conn.disconnect()
        self.active_client = None
        self.active_candidate = None
        self.status = STATUS_WAITING
