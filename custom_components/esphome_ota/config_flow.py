"""Config flow for ESPHome OTA integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url
import voluptuous as vol

from .builder.ha_discovery import HaDiscoveryAdapter
from .const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_NAME,
    CONF_BUILDER_SLUG,
    DEFAULT_AUTO_CLEANUP_HOURS,
    DOMAIN,
)
from .models import BuilderCandidate

_LOGGER = logging.getLogger(__name__)


class EsphomeOtaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ESPHome OTA."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_candidates: list[BuilderCandidate] = []
        self._selected_candidate: BuilderCandidate | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle initial setup step."""
        # Enforce singleton config entry
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        adapter = HaDiscoveryAdapter(self.hass)
        self._discovered_candidates = await adapter.async_discover_all()

        if len(self._discovered_candidates) == 1:
            self._selected_candidate = self._discovered_candidates[0]
            return await self.async_step_confirm_settings()

        if len(self._discovered_candidates) > 1:
            return await self.async_step_select_builder()

        # No builder candidate found yet
        return await self.async_step_confirm_settings()

    async def async_step_select_builder(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select among multiple discovered Builder candidates."""
        errors: dict[str, str] = {}
        if user_input is not None:
            slug = user_input.get(CONF_BUILDER_SLUG)
            for cand in self._discovered_candidates:
                if cand.slug == slug:
                    self._selected_candidate = cand
                    return await self.async_step_confirm_settings()
            errors["base"] = "builder_not_found"

        choices = {
            c.slug: f"{c.name} ({c.host}:{c.port})"
            for c in self._discovered_candidates
        }

        return self.async_show_form(
            step_id="select_builder",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BUILDER_SLUG): vol.In(choices),
                }
            ),
            errors=errors,
        )

    async def async_step_confirm_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm base URL and create the config entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            cand = self._selected_candidate

            data: dict[str, Any] = {
                CONF_BASE_URL: base_url,
            }
            title = "ESPHome OTA"
            if cand and cand.slug:
                data[CONF_BUILDER_SLUG] = cand.slug
                data[CONF_BUILDER_NAME] = cand.name
                title = f"ESPHome OTA ({cand.name})"

            return self.async_create_entry(
                title=title,
                data=data,
                options={
                    CONF_BASE_URL: base_url,
                    CONF_AUTO_CLEANUP_HOURS: DEFAULT_AUTO_CLEANUP_HOURS,
                },
            )

        # Propose HA external or internal URL as base_url default
        default_url = ""
        try:
            default_url = get_url(self.hass, allow_internal=False, allow_ip=False)
        except Exception:  # noqa: BLE001
            try:
                default_url = get_url(self.hass)
            except Exception:  # noqa: BLE001
                default_url = ""

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=default_url): str,
            }
        )

        return self.async_show_form(
            step_id="confirm_settings",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "builder_name": self._selected_candidate.name if self._selected_candidate else "Auto-detect",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow handler."""
        return EsphomeOtaOptionsFlowHandler()


class EsphomeOtaOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for ESPHome OTA."""


    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage ESPHome OTA options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_base_url = (
            self.config_entry.options.get(CONF_BASE_URL)
            or self.config_entry.data.get(CONF_BASE_URL, "")
        )
        current_hours = self.config_entry.options.get(
            CONF_AUTO_CLEANUP_HOURS, DEFAULT_AUTO_CLEANUP_HOURS
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=current_base_url): str,
                vol.Required(
                    CONF_AUTO_CLEANUP_HOURS, default=current_hours
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
