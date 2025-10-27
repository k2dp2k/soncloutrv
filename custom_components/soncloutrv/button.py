"""Button platform for SonClouTRV."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

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
            "description": "Führt ein sofortiges Ventil-Durchbewegen durch (100% → 0% → zurück). Dauer: ca. 1 Minute."
        }

    async def async_press(self) -> None:
        """Handle button press - execute valve exercise."""
        # Find the climate entity
        climate_entity_id = f"climate.{self._config_entry.data['name'].lower().replace(' ', '_')}"
        
        for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
            if entity.entity_id == climate_entity_id:
                _LOGGER.info("%s: Manual valve exercise started", entity.name)
                
                try:
                    # Save current valve position
                    original_position = entity._valve_position
                    
                    # Step 1: Fully open (100%)
                    await entity._async_set_valve_opening(100)
                    _LOGGER.info("%s: Valve fully opened", entity.name)
                    
                    # Wait 30 seconds
                    await asyncio.sleep(30)
                    
                    # Step 2: Fully close (0%)
                    await entity._async_set_valve_opening(0)
                    _LOGGER.info("%s: Valve fully closed", entity.name)
                    
                    # Wait 30 seconds
                    await asyncio.sleep(30)
                    
                    # Step 3: Restore original position
                    await entity._async_set_valve_opening(original_position)
                    _LOGGER.info("%s: Valve restored to %d%% after manual exercise", entity.name, original_position)
                    
                except Exception as err:
                    _LOGGER.error("%s: Error during manual valve exercise: %s", entity.name, err)
                
                break
