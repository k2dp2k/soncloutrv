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
        ]
        
        # Current value
        self._attr_current_option = config_entry.data.get(
            "control_mode", CONTROL_MODE_BINARY
        )

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in self._attr_options:
            _LOGGER.error("Invalid control mode: %s", option)
            return
        
        self._attr_current_option = option
        
        # Update config entry data
        new_data = dict(self._config_entry.data)
        new_data["control_mode"] = option
        
        self.hass.config_entries.async_update_entry(
            self._config_entry, data=new_data
        )
        
        # Update climate entity
        if self._config_entry.entry_id in self.hass.data[DOMAIN]:
            entities = self.hass.data[DOMAIN][self._config_entry.entry_id].get("entities", [])
            for entity in entities:
                if hasattr(entity, "_control_mode"):
                    entity._control_mode = option
                    _LOGGER.info(
                        "%s: Control mode changed to %s",
                        entity.name,
                        option,
                    )
                    # Trigger immediate valve update
                    await entity._async_control_heating()
        
        self.async_write_ha_state()
        
        _LOGGER.info("Control mode changed to: %s", option)
