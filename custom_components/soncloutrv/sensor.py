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
    # Use the original SONOFF TRV entity from config
    # This is more reliable and works with any naming scheme
    valve_entity = config_entry.data.get('valve_entity')
    if not valve_entity:
        _LOGGER.error("No valve_entity found in config")
        return
    
    # Derive base name for sensors from valve entity
    # e.g. climate.heizung_wohnzimmer_fussboden -> heizung_wohnzimmer_fussboden
    base_entity_id = valve_entity.replace('climate.', '')
    
    # Create proxy sensors that reference the original TRV sensors
    # Try to find the actual sensor entities (Zigbee2MQTT may use different naming)
    sensors = []
    
    # Battery sensor - try multiple possible names
    for battery_suffix in ["_battery", "battery", "_battery_level"]:
        battery_entity = f"sensor.{base_entity_id}{battery_suffix}"
        if hass.states.get(battery_entity):
            sensors.append(SonClouTRVProxySensor(
                hass,
                config_entry,
                battery_entity,
                "TRV Batterie",
                "mdi:battery",
                "Batterieladung des SONOFF TRVZB.",
            ))
            _LOGGER.info("Found battery sensor: %s", battery_entity)
            break
    else:
        _LOGGER.warning("No battery sensor found for %s", base_entity_id)
    
    # Temperature sensor - try multiple possible names
    for temp_suffix in ["_local_temperature", "local_temperature", "_temperature", "temperature"]:
        temp_entity = f"sensor.{base_entity_id}{temp_suffix}"
        if hass.states.get(temp_entity):
            sensors.append(SonClouTRVProxySensor(
                hass,
                config_entry,
                temp_entity,
                "TRV Temperatur",
                "mdi:thermometer",
                "Vom SONOFF TRVZB gemessene Temperatur.",
            ))
            _LOGGER.info("Found temperature sensor: %s", temp_entity)
            break
    else:
        _LOGGER.warning("No temperature sensor found for %s", base_entity_id)
    
    # Valve position - always add (required for operation)
    valve_entity = f"number.{base_entity_id}_valve_opening_degree"
    if hass.states.get(valve_entity):
        sensors.append(SonClouTRVProxySensor(
            hass,
            config_entry,
            valve_entity,
            "Ventilposition",
            "mdi:valve",
            "Aktuelle Ventilöffnung (0-100%).",
        ))
        _LOGGER.info("Found valve position: %s", valve_entity)
    else:
        _LOGGER.error("Valve opening degree entity not found: %s", valve_entity)
    
    async_add_entities(sensors, True)


class SonClouTRVProxySensor(SensorEntity):
    """Proxy sensor that mirrors an existing TRV sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        source_entity_id: str,
        name: str,
        icon: str,
        description: str | None = None,
    ) -> None:
        """Initialize the proxy sensor."""
        self.hass = hass
        self._source_entity_id = source_entity_id
        self._attr_name = f"{config_entry.data['name']} {name}"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{name.lower().replace(' ', '_')}"
        self._attr_icon = icon
        self._attr_native_value = None
        self._remove_listener = None
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data['name']}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.1.0",
        )
        
        if description:
            self._attr_extra_state_attributes = {"description": description, "source": source_entity_id}

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Track source entity state changes
        self._remove_listener = async_track_state_change_event(
            self.hass,
            [self._source_entity_id],
            self._async_source_changed,
        )
        
        # Initial update
        await self._async_update_from_source()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        if self._remove_listener:
            self._remove_listener()

    @callback
    async def _async_source_changed(self, event) -> None:
        """Handle source entity state changes."""
        await self._async_update_from_source()
        self.async_write_ha_state()

    async def _async_update_from_source(self) -> None:
        """Update sensor value from source entity."""
        source_state = self.hass.states.get(self._source_entity_id)
        if source_state and source_state.state not in ("unavailable", "unknown"):
            self._attr_native_value = source_state.state
            # Copy unit and device class from source
            self._attr_native_unit_of_measurement = source_state.attributes.get("unit_of_measurement")
            self._attr_device_class = source_state.attributes.get("device_class")
            self._attr_state_class = source_state.attributes.get("state_class")
