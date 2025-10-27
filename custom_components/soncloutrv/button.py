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
            "description": "Führt ein sofortiges Ventil-Durchbewegen durch (5 Min 100%, 5 Min 0%, dann zurück). Dauer: 10 Minuten."
        }

    async def async_press(self) -> None:
        """Handle button press - execute valve exercise (5 min open, 5 min closed)."""
        # Find the climate entity
        climate_entity_id = f"climate.{self._config_entry.data['name'].lower().replace(' ', '_')}"
        
        for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
            if entity.entity_id == climate_entity_id:
                _LOGGER.info("%s: Manual valve exercise started", entity.name)
                
                try:
                    # Save current valve position and preset mode
                    original_position = entity._valve_position
                    original_preset = entity._attr_preset_mode
                    
                    _LOGGER.info("%s: Saved current state - Position: %d%%, Preset: %s", 
                               entity.name, original_position, original_preset)
                    
                    # Step 1: Fully open (100%) for 5 minutes
                    await entity._async_set_valve_opening(100)
                    _LOGGER.info("%s: Valve fully opened (100%%) for 5 minutes", entity.name)
                    await asyncio.sleep(300)  # 5 minutes
                    
                    # Step 2: Fully close (0%) for 5 minutes
                    await entity._async_set_valve_opening(0)
                    _LOGGER.info("%s: Valve fully closed (0%%) for 5 minutes", entity.name)
                    await asyncio.sleep(300)  # 5 minutes
                    
                    # Step 3: Restore original position and trigger normal control
                    await entity._async_set_valve_opening(original_position)
                    entity._attr_preset_mode = original_preset
                    _LOGGER.info("%s: Manual valve exercise complete - restored to %d%% (Preset: %s)", 
                               entity.name, original_position, original_preset)
                    
                    # Trigger normal heating control to resume
                    await entity._async_control_heating()
                    
                except Exception as err:
                    _LOGGER.error("%s: Error during manual valve exercise: %s", entity.name, err)
                
                break
