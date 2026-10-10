"""Custom sidebar panel and static frontend assets registration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN, FRONTEND_URL_PATH, PANEL_ICON, PANEL_NAME, PANEL_TITLE

_LOGGER = logging.getLogger(__name__)


class PanelManager:
    """Manages the ESPHome OTA custom frontend panel and static routes."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._panel_registered = False
        self._static_paths_registered = False

    async def async_register(self) -> None:
        """Register frontend static routes and custom sidebar panel."""
        integration = await async_get_integration(self.hass, DOMAIN)
        version = str(integration.version)

        # 1. Register static paths once
        if not self._static_paths_registered and getattr(self.hass, "http", None) is not None:
            frontend_dir = Path(__file__).parent / "frontend"
            try:
                await self.hass.http.async_register_static_paths(
                    [
                        StaticPathConfig(
                            f"{FRONTEND_URL_PATH}/{version}",
                            str(frontend_dir),
                            False,
                        )
                    ]
                )
                self._static_paths_registered = True
            except (RuntimeError, ValueError) as err:
                _LOGGER.debug("Static paths already registered or router frozen: %s", err)

        # 2. Register panel
        if not self._panel_registered:
            try:
                await panel_custom.async_register_panel(
                    self.hass,
                    PANEL_NAME,
                    "esphome-ota-manager",
                    sidebar_title=PANEL_TITLE,
                    sidebar_icon=PANEL_ICON,
                    module_url=f"{FRONTEND_URL_PATH}/{version}/manager.js",
                    config={"version": version},
                    require_admin=True,
                )
                self._panel_registered = True
                _LOGGER.debug("Registered ESPHome OTA sidebar panel")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Panel already registered or registration failed: %s", err)

    def async_unregister(self) -> None:
        """Remove the custom sidebar panel."""
        if self._panel_registered:
            frontend.async_remove_panel(self.hass, PANEL_NAME)
            self._panel_registered = False
            _LOGGER.debug("Unregistered ESPHome OTA sidebar panel")
