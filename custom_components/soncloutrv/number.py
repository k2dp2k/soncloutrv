"""Number platform for SonClouTRV."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
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
    """Set up SonClouTRV number platform."""
    
    numbers = [
        SonClouTRVNumber(
            hass,
            config_entry,
            "hysteresis",
            "Hysterese",
            0.1,
            2.0,
            0.1,
            "°C",
            "mdi:thermometer-lines",
            0.5,  # Default value
            "Temperaturbereich, in dem das Ventil nicht verändert wird. Verhindert ständiges Schalten. Empfehlung: 0,3-0,7°C.",
        ),
        SonClouTRVNumber(
            hass,
            config_entry,
            "min_valve_update_interval",
            "Trägheit (Min. Update-Intervall)",
            1,
            60,
            1,
            UnitOfTime.MINUTES,
            "mdi:timer-sand",
            10,  # Default: 10 minutes
            "Minimale Zeit zwischen Ventil-Anpassungen. Höhere Werte = träger. Empfehlung: 10-20 Min für Fußbodenheizung.",
        ),
    ]
    
    async_add_entities(numbers, True)


class SonClouTRVNumber(NumberEntity):
    """Representation of a SonClouTRV number setting."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        setting_id: str,
        name: str,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
        icon: str,
        default_value: float,
        description: str | None = None,
    ) -> None:
        """Initialize the number entity."""
        self.hass = hass
        self._config_entry = config_entry
        self._setting_id = setting_id
        self._attr_name = f"{config_entry.data['name']} {name}"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{setting_id}"
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX
        self._attr_native_value = default_value
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data['name']}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
        )
        
        # Store description
        if description:
            self._attr_extra_state_attributes = {"description": description}

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        
        # Find the climate entity and update its settings
        climate_entity_id = f"climate.{self._config_entry.data['name'].lower().replace(' ', '_')}"
        
        # Get the climate entity from registry
        for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
            if entity.entity_id == climate_entity_id:
                if self._setting_id == "hysteresis":
                    entity._hysteresis = value
                    _LOGGER.info("%s: Hysteresis set to %.1f°C", entity.name, value)
                elif self._setting_id == "min_valve_update_interval":
                    # Convert minutes to seconds
                    entity._min_valve_update_interval = int(value * 60)
                    _LOGGER.info("%s: Min valve update interval set to %d minutes", entity.name, int(value))
                break
        
        self.async_write_ha_state()
