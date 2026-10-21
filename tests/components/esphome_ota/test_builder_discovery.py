"""Unit tests for ESPHome Builder discovery and resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.core import HomeAssistant
import pytest

from custom_components.esphome_ota.builder.ha_discovery import HaDiscoveryAdapter
from custom_components.esphome_ota.builder.resolver import BuilderResolver
from custom_components.esphome_ota.models import (
    BuilderCandidate,
    BuilderConnectionError,
    BuilderSelection,
)
from tests.components.esphome_ota.conftest import MockBuilderServer


async def test_discovery_from_esphome_dashboard(hass: HomeAssistant) -> None:
    """Test discovery from ESPHome component dashboard coordinator."""
    mock_coord = MagicMock()
    mock_coord.url = "http://127.0.0.1:6052"
    mock_coord.addon_slug = "5c53de3b_esphome"

    with patch(
        "homeassistant.components.esphome.dashboard.async_get_dashboard",
        return_value=mock_coord,
    ):
        adapter = HaDiscoveryAdapter(hass)
        candidates = await adapter.async_discover_from_esphome_dashboard()
        assert len(candidates) == 1
        assert candidates[0].slug == "5c53de3b_esphome"
        assert candidates[0].port == 6052
        assert candidates[0].source == "dashboard"


async def test_discovery_from_supervisor_services(hass: HomeAssistant) -> None:
    """Test discovery from Supervisor discovery service list."""
    mock_disc = MagicMock()
    mock_disc.service = "esphome"
    mock_disc.addon = "5c53de3b_esphome"
    mock_disc.config = {"host": "127.0.0.1", "port": 6053}

    mock_client = MagicMock()
    mock_client.discovery.list = AsyncMock(return_value=[mock_disc])

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_supervisor_client",
            return_value=mock_client,
        ),
    ):
        adapter = HaDiscoveryAdapter(hass)
        candidates = await adapter.async_discover_from_supervisor_services()
        assert len(candidates) == 1
        assert candidates[0].slug == "5c53de3b_esphome"
        assert candidates[0].port == 6053
        assert candidates[0].source == "supervisor_discovery"


async def test_discovery_from_supervisor_addons(hass: HomeAssistant) -> None:
    """Test discovery from Supervisor installed addons."""
    addons_info = {
        "5c53de3b_esphome": {
            "name": "ESPHome",
            "state": "started",
            "ingress_port": 61234,
            "version": "2026.10.0",
        },
        "core_mosquitto": {
            "name": "Mosquitto",
            "state": "started",
            "ingress_port": 1883,
        },
    }

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_addons_info", return_value=addons_info
        ),
        patch(
            "homeassistant.components.hassio.get_supervisor_client",
            return_value=MagicMock(),
        ),
    ):
        adapter = HaDiscoveryAdapter(hass)
        candidates = await adapter.async_discover_from_supervisor_addons()
        assert len(candidates) == 1
        assert candidates[0].slug == "5c53de3b_esphome"
        assert candidates[0].port == 61234
        assert candidates[0].source == "supervisor_addon"


async def test_discover_all_drops_stale_and_merges_by_slug(
    hass: HomeAssistant,
) -> None:
    """Candidates of uninstalled add-ons are dropped; same-slug ones are merged."""
    dashboard = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Dashboard",
        host="127.0.0.1",
        port=6052,
        source="dashboard",
    )
    stale_dashboard = BuilderCandidate(
        slug="a0d7b954_esphome",
        name="ESPHome Dashboard",
        host="a0d7b954-esphome",
        port=6052,
        source="dashboard",
    )
    stale_discovery = BuilderCandidate(
        slug="a0d7b954_esphome",
        name="ESPHome",
        host="a0d7b954-esphome",
        port=6053,
        source="supervisor_discovery",
    )
    addon = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome",
        host="127.0.0.1",
        port=61234,
        source="supervisor_addon",
        version="2026.10.0",
    )
    with (
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_esphome_dashboard",
            return_value=[dashboard, stale_dashboard],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_services",
            return_value=[stale_discovery],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_addons",
            return_value=[addon],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "_async_installed_addon_slugs",
            return_value={"5c53de3b_esphome", "core_mosquitto"},
        ),
    ):
        candidates = await HaDiscoveryAdapter(hass).async_discover_all()

    assert [c.slug for c in candidates] == ["5c53de3b_esphome"]
    assert candidates[0].source == "dashboard"
    assert candidates[0].port == 6052
    assert candidates[0].version == "2026.10.0"


async def test_discover_all_keeps_candidates_when_installed_unknown(
    hass: HomeAssistant,
) -> None:
    """Without Supervisor data nothing is filtered out."""
    dashboard = BuilderCandidate(
        slug="esphome", name="ESPHome", host="127.0.0.1", port=6052, source="dashboard"
    )
    with (
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_esphome_dashboard",
            return_value=[dashboard],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_services",
            return_value=[],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_addons",
            return_value=[],
        ),
        patch.object(
            HaDiscoveryAdapter, "_async_installed_addon_slugs", return_value=None
        ),
    ):
        candidates = await HaDiscoveryAdapter(hass).async_discover_all()

    assert candidates == [dashboard]


async def test_installed_addon_slugs(hass: HomeAssistant) -> None:
    """Installed add-on lookup returns None whenever the result is unreliable."""
    adapter = HaDiscoveryAdapter(hass)

    with patch("homeassistant.helpers.hassio.is_hassio", return_value=False):
        assert await adapter._async_installed_addon_slugs() is None

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_addons_info",
            side_effect=RuntimeError("not ready"),
        ),
    ):
        assert await adapter._async_installed_addon_slugs() is None

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch("homeassistant.components.hassio.get_addons_info", return_value={}),
    ):
        assert await adapter._async_installed_addon_slugs() is None

    with (
        patch("homeassistant.helpers.hassio.is_hassio", return_value=True),
        patch(
            "homeassistant.components.hassio.get_addons_info",
            return_value={"5c53de3b_esphome": {}, "core_mosquitto": {}},
        ),
    ):
        assert await adapter._async_installed_addon_slugs() == {
            "5c53de3b_esphome",
            "core_mosquitto",
        }


async def test_discover_all_fills_version_from_duplicate_endpoint(
    hass: HomeAssistant,
) -> None:
    """The version is filled in even when the duplicate shares the endpoint."""
    dashboard = BuilderCandidate(
        slug="esphome", name="ESPHome", host="127.0.0.1", port=6052, source="dashboard"
    )
    addon = BuilderCandidate(
        slug="esphome",
        name="ESPHome",
        host="127.0.0.1",
        port=6052,
        source="supervisor_addon",
        version="2026.10.0",
    )
    with (
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_esphome_dashboard",
            return_value=[dashboard],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_services",
            return_value=[],
        ),
        patch.object(
            HaDiscoveryAdapter,
            "async_discover_from_supervisor_addons",
            return_value=[addon],
        ),
        patch.object(
            HaDiscoveryAdapter, "_async_installed_addon_slugs", return_value=None
        ),
    ):
        candidates = await HaDiscoveryAdapter(hass).async_discover_all()

    assert len(candidates) == 1
    assert candidates[0].version == "2026.10.0"


async def test_resolver_selection_priorities(
    hass: HomeAssistant, mock_builder: MockBuilderServer
) -> None:
    """Test candidate selection rules and saved selection priority."""
    async with aiohttp.ClientSession() as session:
        # 1. No candidates -> waiting
        with patch.object(HaDiscoveryAdapter, "async_discover_all", return_value=[]):
            resolver = BuilderResolver(hass, session)
            with pytest.raises(
                BuilderConnectionError, match="No ESPHome Builder candidate found"
            ):
                await resolver.async_resolve()
            assert resolver.status == "waiting"

        # 2. Multiple candidates with no saved selection -> selection_required
        cand1 = BuilderCandidate(
            slug="esphome1", name="B1", host="127.0.0.1", port=1111, source="addon"
        )
        cand2 = BuilderCandidate(
            slug="esphome2", name="B2", host="127.0.0.1", port=2222, source="addon"
        )
        with patch.object(
            HaDiscoveryAdapter, "async_discover_all", return_value=[cand1, cand2]
        ):
            resolver = BuilderResolver(hass, session)
            with pytest.raises(BuilderConnectionError, match="Selection required"):
                await resolver.async_resolve()
            assert resolver.status == "selection_required"

        # 3. Saved selection matches discovered candidate
        saved = BuilderSelection(
            slug="esphome_mock",
            name="Mock",
            source="saved",
            host_hint="127.0.0.1",
            port_hint=mock_builder.port,
        )
        cand_mock = BuilderCandidate(
            slug="esphome_mock",
            name="Mock",
            host="127.0.0.1",
            port=mock_builder.port,
            source="dashboard",
        )
        with patch.object(
            HaDiscoveryAdapter, "async_discover_all", return_value=[cand1, cand_mock]
        ):
            resolver = BuilderResolver(hass, session, saved_selection=saved)
            client = await resolver.async_resolve()
            assert resolver.status == "ready"
            assert resolver.active_candidate.slug == "esphome_mock"
            assert client.is_connected
            await resolver.async_disconnect()
            assert not client.is_connected
