"""Button platform for SonClouTRV."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SonClouTRV button platform."""
    
    button = ValveExerciseButton(hass, config_entry)
    async_add_entities([button], True)


class ValveExerciseButton(ButtonEntity):
    """Button to manually trigger valve exercise."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = f"{config_entry.data['name']} Ventil Durchbewegen"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_valve_exercise"
        self._attr_icon = "mdi:valve"
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data['name']}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
        )
        
        # Entity description in attributes
        self._attr_extra_state_attributes = {
            "description": "Führt ein sofortiges Ventil-Durchbewegen durch (5 Min 100%, 5 Min 0%, dann zurück). Dauer: 10 Minuten."
        }

    async def async_press(self) -> None:
        """Handle button press - execute valve exercise (5 min open, 5 min closed)."""
        # Find the climate entity from registry
        try:
            found = False
            for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
                if hasattr(entity, '_entity_id_base'):
                    found = True
                    _LOGGER.info("%s: Manual valve exercise started", entity.name)
                    
                    # Delegate to climate entity
                    await entity.async_trigger_valve_exercise()
                    break
            
            if not found:
                _LOGGER.warning("%s: Climate entity not found in registry, manual exercise skipped", self._attr_name)
        except Exception as err:
            _LOGGER.error("%s: Error in manual exercise lookup: %s", self._attr_name, err)
    
