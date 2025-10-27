"""Switch platform for SonClouTRV."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SonClouTRV switch platform."""
    
    switch = AntiCalcificationSwitch(hass, config_entry)
    async_add_entities([switch], True)


class AntiCalcificationSwitch(SwitchEntity):
    """Switch to enable/disable anti-calcification protection."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_name = f"{config_entry.data['name']} Verkalkungsschutz"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_anti_calcification"
        self._attr_icon = "mdi:water-off"
        self._attr_is_on = True  # Default: ON (enabled)
        self._last_exercise = None
        self._remove_listener = None
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data['name']}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
        )
        

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Schedule daily check for Sunday 3:00 AM (enabled by default)
        if self._attr_is_on:
            self._remove_listener = async_track_time_interval(
                self.hass,
                self._async_check_exercise,
                timedelta(hours=24),  # Check daily
            )
            _LOGGER.info("%s: Anti-calcification protection enabled by default", self._attr_name)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        if self._remove_listener:
            self._remove_listener()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on anti-calcification protection."""
        self._attr_is_on = True
        
        # Start periodic check
        if self._remove_listener:
            self._remove_listener()
        
        self._remove_listener = async_track_time_interval(
            self.hass,
            self._async_check_exercise,
            timedelta(hours=24),
        )
        
        _LOGGER.info("%s: Anti-calcification protection enabled", self._attr_name)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off anti-calcification protection."""
        self._attr_is_on = False
        
        # Stop periodic check
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        
        _LOGGER.info("%s: Anti-calcification protection disabled", self._attr_name)
        self.async_write_ha_state()

    async def _async_check_exercise(self, now=None) -> None:
        """Check if valve exercise is needed (Sundays at 3:00 AM)."""
        if not self._attr_is_on:
            return
        
        current_time = datetime.now()
        
        # Check if it's Sunday (weekday 6) and between 3:00-3:59 AM
        if current_time.weekday() != 6:  # Not Sunday
            return
        
        if current_time.hour != 3:  # Not 3 AM hour
            return
        
        # Check if already exercised this week
        if self._last_exercise is not None:
            days_since_last = (current_time - self._last_exercise).days
            if days_since_last < 7:  # Already done this week
                return
        
        # Execute valve exercise
        await self._async_exercise_valve()

    async def _async_exercise_valve(self) -> None:
        """Exercise the valve to prevent calcification (5 min open, 5 min closed)."""
        # Find the climate entity
        climate_entity_id = f"climate.{self._config_entry.data['name'].lower().replace(' ', '_')}"
        
        for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
            if entity.entity_id == climate_entity_id:
                _LOGGER.info("%s: Starting anti-calcification valve exercise (Sunday 3:00 AM)", entity.name)
                
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
                    _LOGGER.info("%s: Valve exercise complete - restored to %d%% (Preset: %s)", 
                               entity.name, original_position, original_preset)
                    
                    # Update last exercise time
                    self._last_exercise = datetime.now()
                    self.async_write_ha_state()
                    
                    # Trigger normal heating control to resume
                    await entity._async_control_heating()
                    
                except Exception as err:
                    _LOGGER.error("%s: Error during valve exercise: %s", entity.name, err)
                
                break

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        attrs = {
            "description": "Automatisches Ventil-Durchbewegen jeden Sonntag um 3:00 Uhr (5 Min offen, 5 Min geschlossen)."
        }
        if self._last_exercise:
            attrs["last_exercise"] = self._last_exercise.isoformat()
            days_since = (datetime.now() - self._last_exercise).days
            attrs["days_since_last_exercise"] = days_since
            attrs["next_exercise_in_days"] = max(0, 7 - days_since)
        return attrs
