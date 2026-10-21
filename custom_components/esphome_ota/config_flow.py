"""Config flow for ESPHome OTA integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.network import get_url

from .builder.ha_discovery import HaDiscoveryAdapter
from .const import (
    CONF_AUTO_CLEANUP_HOURS,
    CONF_BASE_URL,
    CONF_BUILDER_HOST,
    CONF_BUILDER_NAME,
    CONF_BUILDER_PORT,
    CONF_BUILDER_SLUG,
    DEFAULT_AUTO_CLEANUP_HOURS,
    DOMAIN,
)
from .models import BuilderCandidate

_LOGGER = logging.getLogger(__name__)


def _normalize_base_url(value: str) -> str | None:
    """Return the cleaned base URL, or None when it is not a valid http(s) URL."""
    cleaned = value.strip().rstrip("/")
    try:
        parsed = urlsplit(cleaned)
        parsed.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if (
        parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or any(ch.isspace() for ch in cleaned)
    ):
        return None
    return cleaned


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
            c.slug: f"{c.name} ({c.host}:{c.port}, {c.source})"
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
            base_url = _normalize_base_url(user_input.get(CONF_BASE_URL, ""))
            if base_url is None:
                errors[CONF_BASE_URL] = "invalid_url"
            else:
                cand = self._selected_candidate

                data: dict[str, Any] = {
                    CONF_BASE_URL: base_url,
                }
                options: dict[str, Any] = {
                    CONF_BASE_URL: base_url,
                    CONF_AUTO_CLEANUP_HOURS: DEFAULT_AUTO_CLEANUP_HOURS,
                }
                title = "ESPHome OTA"
                if cand and cand.slug:
                    data[CONF_BUILDER_SLUG] = cand.slug
                    data[CONF_BUILDER_NAME] = cand.name
                    options[CONF_BUILDER_SLUG] = cand.slug
                    options[CONF_BUILDER_NAME] = cand.name
                    title = f"ESPHome OTA ({cand.name})"

                return self.async_create_entry(
                    title=title,
                    data=data,
                    options=options,
                )

        # Propose HA external or internal URL as base_url default
        default_url = ""
        if user_input is not None:
            default_url = user_input.get(CONF_BASE_URL, "")
        else:
            default_url = self._default_base_url()

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
                "builder_name": self._selected_candidate.name
                if self._selected_candidate
                else "ESPHome Builder",
            },
        )

    def _default_base_url(self) -> str:
        """Propose HA's external, else internal, URL as the default base URL."""
        default_url = ""
        try:
            default_url = get_url(self.hass, allow_internal=False, allow_ip=False)
        except Exception:  # noqa: BLE001
            try:
                default_url = get_url(self.hass)
            except Exception:  # noqa: BLE001
                default_url = ""
        return default_url

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
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = _normalize_base_url(user_input.get(CONF_BASE_URL, ""))
            if base_url is None:
                errors[CONF_BASE_URL] = "invalid_url"
        if user_input is not None and not errors:
            clean_options = dict(user_input)
            clean_options[CONF_BASE_URL] = base_url
            # Sync builder selection to config entry data
            if CONF_BUILDER_SLUG in user_input:
                slug = user_input[CONF_BUILDER_SLUG]
                new_data = dict(self.config_entry.data)
                if slug and slug != "auto":
                    new_data[CONF_BUILDER_SLUG] = slug
                    clean_options[CONF_BUILDER_SLUG] = slug
                    discovery = HaDiscoveryAdapter(self.hass)
                    candidates = await discovery.async_discover_all()
                    for c in candidates:
                        if c.slug == slug:
                            new_data[CONF_BUILDER_NAME] = c.name
                            clean_options[CONF_BUILDER_NAME] = c.name
                            if c.host:
                                new_data[CONF_BUILDER_HOST] = c.host
                                clean_options[CONF_BUILDER_HOST] = c.host
                            if c.port:
                                new_data[CONF_BUILDER_PORT] = c.port
                                clean_options[CONF_BUILDER_PORT] = c.port
                            break
                    else:
                        new_data.setdefault(CONF_BUILDER_NAME, slug)
                        clean_options.setdefault(CONF_BUILDER_NAME, slug)
                else:
                    new_data.pop(CONF_BUILDER_SLUG, None)
                    new_data.pop(CONF_BUILDER_NAME, None)
                    new_data.pop(CONF_BUILDER_HOST, None)
                    new_data.pop(CONF_BUILDER_PORT, None)
                    clean_options.pop(CONF_BUILDER_SLUG, None)
                    clean_options.pop(CONF_BUILDER_NAME, None)
                    clean_options.pop(CONF_BUILDER_HOST, None)
                    clean_options.pop(CONF_BUILDER_PORT, None)
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
            return self.async_create_entry(title="", data=clean_options)

        current_base_url = self.config_entry.options.get(
            CONF_BASE_URL
        ) or self.config_entry.data.get(CONF_BASE_URL, "")
        current_hours = self.config_entry.options.get(
            CONF_AUTO_CLEANUP_HOURS, DEFAULT_AUTO_CLEANUP_HOURS
        )
        current_slug = (
            self.config_entry.options.get(CONF_BUILDER_SLUG)
            or self.config_entry.data.get(CONF_BUILDER_SLUG)
            or "auto"
        )
        if user_input is not None:
            current_base_url = user_input.get(CONF_BASE_URL, current_base_url)
            current_hours = user_input.get(CONF_AUTO_CLEANUP_HOURS, current_hours)
            current_slug = user_input.get(CONF_BUILDER_SLUG, current_slug)

        discovery = HaDiscoveryAdapter(self.hass)
        candidates = await discovery.async_discover_all()

        # "auto" is labelled through the selector translations; discovered builders
        # carry their own (non-translatable) names.
        builder_options = [
            selector.SelectOptionDict(value="auto", label="auto"),
            *(
                selector.SelectOptionDict(
                    value=c.slug, label=f"{c.name} ({c.host}:{c.port}, {c.source})"
                )
                for c in candidates
            ),
        ]
        if all(opt["value"] != current_slug for opt in builder_options):
            builder_options.append(
                selector.SelectOptionDict(value=current_slug, label=current_slug)
            )

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_BASE_URL, default=current_base_url): str,
            vol.Required(CONF_AUTO_CLEANUP_HOURS, default=current_hours): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=168)
            ),
            vol.Optional(
                CONF_BUILDER_SLUG, default=current_slug
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=builder_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="builder_slug",
                )
            ),
        }

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema_dict), errors=errors
        )
