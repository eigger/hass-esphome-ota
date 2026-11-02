"""Unit tests for ESPHome OTA config flow and options flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.esphome_ota.const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_SLUG,
    DOMAIN,
)
from custom_components.esphome_ota.models import BuilderCandidate


async def test_flow_single_candidate_auto_select(hass: HomeAssistant) -> None:
    """Test flow automatically advances when a single Builder is found."""
    cand = BuilderCandidate(
        slug="5c53de3b_esphome",
        name="ESPHome Device Builder",
        host="127.0.0.1",
        port=6052,
        source="addon",
    )

    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=[cand],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "confirm_settings"

        # Complete step with base_url
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_BASE_URL: "https://my-ha.duckdns.org"},
        )
        assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result2["data"][CONF_BUILDER_SLUG] == "5c53de3b_esphome"
        assert result2["data"][CONF_BASE_URL] == "https://my-ha.duckdns.org"


async def test_flow_multiple_candidates_selection(hass: HomeAssistant) -> None:
    """Test selecting from multiple discovered candidates."""
    cand1 = BuilderCandidate(
        slug="esphome_stable",
        name="ESPHome Stable",
        host="127.0.0.1",
        port=6052,
        source="addon",
    )
    cand2 = BuilderCandidate(
        slug="esphome_dev",
        name="ESPHome Dev",
        host="127.0.0.1",
        port=6053,
        source="addon",
    )

    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=[cand1, cand2],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_builder"

        # Select candidate 2
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_BUILDER_SLUG: "esphome_dev"},
        )
        assert result2["type"] is data_entry_flow.FlowResultType.FORM
        assert result2["step_id"] == "confirm_settings"

        # Confirm settings
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {CONF_BASE_URL: "https://my-dev.duckdns.org"},
        )
        assert result3["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result3["data"][CONF_BUILDER_SLUG] == "esphome_dev"


async def test_single_instance_abort(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test flow aborts if domain is already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test modifying options via options flow."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: "https://updated.duckdns.org", CONF_AUTO_CLEANUP_HOURS: 24},
    )
    assert result2["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_BASE_URL] == "https://updated.duckdns.org"
    assert result2["data"][CONF_AUTO_CLEANUP_HOURS] == 24


async def _run_options_flow(
    hass: HomeAssistant, entry: MockConfigEntry, user_input: dict, candidates: list
) -> dict:
    """Run the options flow with a patched discovery and a counting listener."""
    with patch(
        "custom_components.esphome_ota.config_flow.HaDiscoveryAdapter.async_discover_all",
        return_value=candidates,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )


async def test_options_builder_change_updates_once_and_consistently(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Changing the Builder fires the update listener once with consistent state."""
    mock_config_entry.add_to_hass(hass)
    seen: list[tuple[str | None, str | None]] = []

    async def _listener(hass_: HomeAssistant, entry: MockConfigEntry) -> None:
        seen.append(
            (entry.data.get(CONF_BUILDER_SLUG), entry.options.get(CONF_BUILDER_SLUG))
        )

    mock_config_entry.add_update_listener(_listener)
    cand = BuilderCandidate(
        slug="new_builder", name="New", host="10.0.0.5", port=6052, source="addon"
    )
    result = await _run_options_flow(
        hass,
        mock_config_entry,
        {
            CONF_BASE_URL: "https://my-ha.duckdns.org",
            CONF_AUTO_CLEANUP_HOURS: 12,
            CONF_BUILDER_SLUG: "new_builder",
        },
        [cand],
    )
    await hass.async_block_till_done()

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert seen == [("new_builder", "new_builder")]
    assert mock_config_entry.options[CONF_BUILDER_SLUG] == "new_builder"
    assert mock_config_entry.data[CONF_BUILDER_SLUG] == "new_builder"


async def test_options_auto_clears_legacy_data_slug_once(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Selecting auto removes the legacy data slug so the manager really auto-detects."""
    mock_config_entry.add_to_hass(hass)
    calls = 0

    async def _listener(hass_: HomeAssistant, entry: MockConfigEntry) -> None:
        nonlocal calls
        calls += 1

    mock_config_entry.add_update_listener(_listener)
    await _run_options_flow(
        hass,
        mock_config_entry,
        {
            CONF_BASE_URL: "https://my-ha.duckdns.org",
            CONF_AUTO_CLEANUP_HOURS: 12,
            CONF_BUILDER_SLUG: "auto",
        },
        [],
    )
    await hass.async_block_till_done()

    assert calls == 1
    assert CONF_BUILDER_SLUG not in mock_config_entry.data
    assert CONF_BUILDER_SLUG not in mock_config_entry.options
