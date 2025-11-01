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
        SonClouTRVNumber(
            hass,
            config_entry,
            "proportional_gain",
            "P-Verstärkung",
            5.0,
            50.0,
            1.0,
            "%/°C",
            "mdi:tune-vertical",
            20.0,  # Default: 20% per °C
            "Proportionale Verstärkung: Wie stark das Ventil pro °C Temperaturdifferenz öffnet. Höhere Werte = aggressiver. Standard: 20%/°C.",
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
        
        # Load value from config_entry.options (user-set) or use default
        saved_value = config_entry.options.get(setting_id)
        self._attr_native_value = saved_value if saved_value is not None else default_value
        
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
        
        try:
            # Get the climate entity from registry
            found = False
            for entity in self.hass.data[DOMAIN].get(self._config_entry.entry_id, {}).get("entities", []):
                if hasattr(entity, '_entity_id_base'):
                    found = True
                    if self._setting_id == "hysteresis":
                        entity._hysteresis = value
                        _LOGGER.info("%s: Hysteresis set to %.1f°C", entity.name, value)
                    elif self._setting_id == "min_valve_update_interval":
                        # Convert minutes to seconds
                        entity._min_valve_update_interval = int(value * 60)
                        _LOGGER.info("%s: Min valve update interval set to %d minutes", entity.name, int(value))
                    elif self._setting_id == "proportional_gain":
                        entity._proportional_gain = value
                        _LOGGER.info("%s: Proportional gain set to %.1f%%/°C", entity.name, value)
                    break
            
            if not found:
                _LOGGER.warning("%s: Climate entity not found in registry, value not applied", self._attr_name)
            
            # Persist the value to config_entry.options
            # This ensures the value survives a restart
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                options={**self._config_entry.options, self._setting_id: value},
            )
            _LOGGER.debug("%s: Saved %s = %.1f to config_entry", self._attr_name, self._setting_id, value)
        except Exception as err:
            _LOGGER.error("%s: Error setting native value: %s", self._attr_name, err)
        
        self.async_write_ha_state()
