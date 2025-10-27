"""Sensor platform for SonClouTRV."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SonClouTRV sensor platform."""
    # Find the climate entity - use the correct entity_id with sontrv prefix
    name_slug = config_entry.data['name'].lower().replace(' ', '_')
    climate_entity_id = f"climate.sontrv_{name_slug}"
    
    sensors = [
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "valve_position",
            "Ventilposition",
            PERCENTAGE,
            "mdi:valve",
            SensorStateClass.MEASUREMENT,
            None,
            "Aktuelle Öffnung des Ventils (0-100%). Je höher, desto mehr Heizleistung.",
        ),
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "trv_internal_temperature",
            "TRV Temperatur",
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer",
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.TEMPERATURE,
            "Vom TRV-Sensor gemessene Temperatur (nur zum Vergleich mit externem Sensor).",
        ),
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "trv_battery",
            "TRV Batterie",
            PERCENTAGE,
            "mdi:battery",
            SensorStateClass.MEASUREMENT,
            SensorDeviceClass.BATTERY,
            "Batterieladung des TRV-Thermostats. Warnung bei unter 20%.",
        ),
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "temperature_difference",
            "Temperaturdifferenz",
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer-lines",
            SensorStateClass.MEASUREMENT,
            None,
            "Differenz zwischen Soll- und Ist-Temperatur. Positiv = zu kalt, negativ = zu warm.",
        ),
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "average_valve_position",
            "Ø Ventilposition",
            PERCENTAGE,
            "mdi:gauge",
            SensorStateClass.MEASUREMENT,
            None,
            "Durchschnittliche Ventilöffnung der letzten 10 Anpassungen.",
        ),
        SonClouTRVSensor(
            hass,
            config_entry,
            climate_entity_id,
            "preset_mode",
            "Aktuelle Stufe",
            None,
            "mdi:numeric",
            None,
            None,
            "Aktuell gewählte Ventilöffnungsstufe (* = 0%, 1-5 = 20%-100%).",
        ),
    ]
    
    async_add_entities(sensors, True)


class SonClouTRVSensor(SensorEntity):
    """Representation of a SonClouTRV sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        climate_entity_id: str,
        attribute_name: str,
        name: str,
        unit: str,
        icon: str,
        state_class: SensorStateClass | None = None,
        device_class: SensorDeviceClass | None = None,
        description: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._climate_entity_id = climate_entity_id
        self._attribute_name = attribute_name
        self._attr_name = f"{config_entry.data['name']} {name}"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{attribute_name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_state_class = state_class
        self._attr_device_class = device_class
        self._attr_native_value = None
        self._remove_listener = None
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data['name']}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
        )
        
        # Entity description
        if description:
            self._attr_entity_description = SensorEntityDescription(
                key=attribute_name,
                name=name,
                native_unit_of_measurement=unit,
                icon=icon,
                state_class=state_class,
                device_class=device_class,
            )
            self._attr_extra_state_attributes = {"description": description}

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Track climate entity state changes
        self._remove_listener = async_track_state_change_event(
            self.hass,
            [self._climate_entity_id],
            self._async_climate_changed,
        )
        
        # Initial update
        await self._async_update_from_climate()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        if self._remove_listener:
            self._remove_listener()

    @callback
    async def _async_climate_changed(self, event) -> None:
        """Handle climate entity state changes."""
        await self._async_update_from_climate()
        self.async_write_ha_state()

    async def _async_update_from_climate(self) -> None:
        """Update sensor value from climate entity attribute."""
        climate_state = self.hass.states.get(self._climate_entity_id)
        if climate_state:
            self._attr_native_value = climate_state.attributes.get(self._attribute_name)
