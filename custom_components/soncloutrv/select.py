"""Select platform for SonClouTRV."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PROPORTIONAL,
    CONTROL_MODE_PID,
    DEFAULT_CONTROL_MODE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SonClouTRV select platform."""
    config = config_entry.data
    name = config[CONF_NAME]
    
    async_add_entities([
        SonClouTRVControlModeSelect(hass, config_entry, name),
    ])


class SonClouTRVControlModeSelect(SelectEntity):
    """Select entity for control mode."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:tune-variant"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        name: str,
    ) -> None:
        """Initialize the select entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = "Steuermodus"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_control_mode"
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {name}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
            configuration_url="https://github.com/k2dp2k/soncloutrv",
        )
        
        # Options
        self._attr_options = [
            CONTROL_MODE_BINARY,
            CONTROL_MODE_PROPORTIONAL,
            CONTROL_MODE_PID,
        ]
        
        # Current value (default: PID, see DEFAULT_CONTROL_MODE)
        self._attr_current_option = config_entry.data.get(
            "control_mode", DEFAULT_CONTROL_MODE
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._attr_options:
            _LOGGER.error("Invalid control mode: %s", option)
            return
        
        old_option = self._attr_current_option
        self._attr_current_option = option
        
        # Update config entry data
        new_data = dict(self._config_entry.data)
        new_data["control_mode"] = option

        # Trigger a config_entry update. Our update listener in __init__.py
        # (`entry.add_update_listener(async_reload_entry)`) will take care of
        # unloading/reloading the integration. We do NOT call async_reload
        # directly here to avoid double reloads and potential race conditions.
        self.hass.config_entries.async_update_entry(
            self._config_entry, data=new_data
        )

        _LOGGER.info(
            "Control mode changed from %s to %s (reload handled by update listener)",
            old_option,
            option,
        )

        # Update our own state immediately; new climate entity will be created
        # by the reload triggered via the update listener.
        self.async_write_ha_state()
