"""Sensor platform for SonClouTRV."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from collections import deque
from typing import Any

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
    UnitOfTime,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.util import dt as dt_util
from homeassistant.const import CONF_NAME

from .const import DOMAIN, CONF_VALVE_ENTITY

_LOGGER = logging.getLogger(__name__)

# Constants for calculations
HEATING_POWER_PER_PERCENT = 0.05  # kW per valve % (adjustable estimate)
SCAN_INTERVAL = timedelta(minutes=1)  # Update statistics every minute


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SonClouTRV sensor platform."""
    valve_entity = config_entry.data.get(CONF_VALVE_ENTITY)
    if not valve_entity:
        _LOGGER.error("No valve_entity found in config")
        return
    
    # === BASIC PROXY SENSORS ===
    # Improved Discovery: Look up entities via device registry if possible
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    
    device_id = None
    
    # Resolve device ID from valve entity
    valve_entry = entity_reg.async_get(valve_entity)
    if valve_entry and valve_entry.device_id:
        device_id = valve_entry.device_id
        _LOGGER.debug("Resolved device ID %s for valve %s", device_id, valve_entity)
    
    # Identify sensors from the same device
    battery_entity = None
    temp_entity = None
    valve_pos_entity = None  # Proxy entity from TRV (opening)
    valve_close_entity = None  # Proxy entity from TRV (closing)
    
    if device_id:
        # Iterate over all entities of this device
        device_entities = [
            entry for entry in entity_reg.entities.values() 
            if entry.device_id == device_id
        ]
        
        for entry in device_entities:
            # Skip disabled entities
            if entry.disabled_by:
                continue
                
            # Match Battery
            if (entry.device_class == SensorDeviceClass.BATTERY or 
                entry.original_device_class == SensorDeviceClass.BATTERY or 
                "battery" in entry.entity_id or 
                "battery" in (entry.original_name or "").lower()):
                if not battery_entity: # Take first match
                    battery_entity = entry.entity_id
            
            # Match Temperature (Internal)
            # Exclude the external sensor we are using for control
            if (entry.entity_id != config_entry.data.get("temp_sensor") and 
                (entry.device_class == SensorDeviceClass.TEMPERATURE or 
                 entry.original_device_class == SensorDeviceClass.TEMPERATURE) and 
                 ("local" in entry.entity_id or "internal" in entry.entity_id or 
                  "temperature" in entry.entity_id)):
                 if not temp_entity:
                     temp_entity = entry.entity_id
            
            # Match Valve Position (if exposed as sensor or number)
            # Typically "position" or "valve_opening_degree"
            if ("position" in entry.entity_id or "valve" in entry.entity_id) and \
               entry.domain in ["sensor", "number"] and \
               entry.entity_id != valve_entity: # Don't match the climate entity
                # Avoid matching our own entities (loop)
                if DOMAIN not in entry.entity_id:
                     valve_pos_entity = entry.entity_id

    # Fallback to string manipulation if device lookup failed or entities not found
    base_entity_id = valve_entity.replace('climate.', '')
    
    if not battery_entity:
        for battery_suffix in ["_battery", "battery", "_battery_level"]:
            candidate = f"sensor.{base_entity_id}{battery_suffix}"
            if hass.states.get(candidate):
                battery_entity = candidate
                break
                
    if not temp_entity:
        for temp_suffix in ["_local_temperature", "local_temperature", "_temperature", "temperature"]:
            candidate = f"sensor.{base_entity_id}{temp_suffix}"
            if hass.states.get(candidate):
                temp_entity = candidate
                break
                
    # Register found sensors
    if battery_entity:
        sensors.append(SonClouTRVProxySensor(
            hass, config_entry, battery_entity,
            "TRV Batterie", "mdi:battery",
            "Batterieladung des SONOFF TRVZB.",
        ))
        _LOGGER.info("Found battery sensor: %s", battery_entity)
    else:
        _LOGGER.warning("No battery sensor found for %s", valve_entity)
        
    if temp_entity:
        sensors.append(SonClouTRVProxySensor(
            hass, config_entry, temp_entity,
            "TRV Temperatur", "mdi:thermometer",
            "Vom SONOFF TRVZB gemessene Temperatur.",
        ))
        _LOGGER.info("Found temperature sensor: %s", temp_entity)
    else:
        _LOGGER.warning("No temperature sensor found for %s", valve_entity)
        
    # Valve position proxy (opening degree)
    if not valve_pos_entity:
        candidate = f"number.{base_entity_id}_valve_opening_degree"
        if hass.states.get(candidate):
            valve_pos_entity = candidate
            
    if valve_pos_entity:
        sensors.append(SonClouTRVProxySensor(
            hass, config_entry, valve_pos_entity,
            "Ventilposition (TRV)", "mdi:valve",
            "Aktuelle Ventilöffnung vom TRV (0-100%)..",
        ))
        _LOGGER.info("Found TRV valve position entity (opening): %s", valve_pos_entity)

    # Valve closing degree proxy (closing = 100 - opening at TRV level)
    if not valve_close_entity:
        candidate = f"number.{base_entity_id}_valve_closing_degree"
        if hass.states.get(candidate):
            valve_close_entity = candidate

    if valve_close_entity:
        sensors.append(SonClouTRVProxySensor(
            hass, config_entry, valve_close_entity,
            "Ventilschließgrad (TRV)", "mdi:valve-closed",
            "Aktueller Ventilschließgrad vom TRV (0-100%)..",
        ))
        _LOGGER.info("Found TRV valve closing entity: %s", valve_close_entity)
    
    # === ADVANCED STATISTICS SENSORS ===
    # Find the climate entity ID from entity registry
    entity_reg = er.async_get(hass)
    climate_entity_id = None
    
    # Search for climate entity with matching config_entry_id
    for entity in entity_reg.entities.values():
        if (entity.config_entry_id == config_entry.entry_id and 
            entity.domain == "climate"):
            climate_entity_id = entity.entity_id
            break
    
    # If not found via config entry linkage, try to find by name match or fallback
    if not climate_entity_id:
        # Fallback 1: Try to construct from valve entity input if it is a climate entity
        if valve_entity.startswith("climate."):
             climate_entity_id = valve_entity # Use the wrapped entity? No, we need OUR entity.
        
        # Fallback 2: Construct expected entity ID from name
        climate_name = config_entry.data.get(CONF_NAME, '').lower().replace(' ', '_')
        # Handle default HA naming normalization (umlauts, etc.) somewhat simply
        climate_entity_id = f"climate.sontrv_{climate_name}" if not climate_name.startswith("sontrv") else f"climate.{climate_name}"
        
        _LOGGER.warning("Could not find climate entity in registry. Guessing ID: %s", climate_entity_id)
    
    _LOGGER.info("Using climate entity ID: %s for sensors", climate_entity_id)

    # Always add native SonTRV valve position sensor (reads from climate entity)
    # Pass the found climate_entity_id to avoid looking it up again
    sensors.append(SonClouTRVNativeValvePositionSensor(hass, config_entry, climate_entity_id))
    _LOGGER.info("Added native SonTRV valve position sensor")

    # Native closing sensor (100 - valve_position from climate attributes)
    sensors.append(SonClouTRVNativeValveClosingSensor(hass, config_entry, climate_entity_id))
    _LOGGER.info("Added native SonTRV valve closing sensor")
    
    # 1. Energy & Efficiency
    sensors.extend([
        SonClouTRVHeatingDurationSensor(hass, config_entry, valve_pos_entity, "today"),
        SonClouTRVHeatingDurationSensor(hass, config_entry, valve_pos_entity, "week"),
        SonClouTRVHeatingEnergySensor(hass, config_entry, valve_pos_entity),
        SonClouTRVEfficiencySensor(hass, config_entry, climate_entity_id),
    ])
    
    # 2. Valve Health & Maintenance
    sensors.extend([
        SonClouTRVLastMovementSensor(hass, config_entry, valve_pos_entity),
        SonClouTRVMovementCountSensor(hass, config_entry, valve_pos_entity),
        SonClouTRVTotalRuntimeSensor(hass, config_entry, valve_pos_entity),
    ])
    
    # 3. Temperature Analysis
    sensors.extend([
        SonClouTRVTemperatureTrendSensor(hass, config_entry, climate_entity_id),
        SonClouTRVAvgTemperatureSensor(hass, config_entry, climate_entity_id),
        SonClouTRVMinMaxTemperatureSensor(hass, config_entry, climate_entity_id, "min"),
        SonClouTRVMinMaxTemperatureSensor(hass, config_entry, climate_entity_id, "max"),
    ])
    
    # 4. Comfort & Optimization
    sensors.extend([
        SonClouTRVTimeToTargetSensor(hass, config_entry, climate_entity_id),
        SonClouTRVOverheatWarningSensor(hass, config_entry, climate_entity_id),
        SonClouTRVUnderheatWarningSensor(hass, config_entry, climate_entity_id, valve_pos_entity),
    ])
    
    # 5. System Status
    sensors.extend([
        SonClouTRVConnectionStatusSensor(hass, config_entry, valve_entity),
        SonClouTRVLastUpdateSensor(hass, config_entry, valve_entity),
        SonClouTRVBatteryStatusSensor(hass, config_entry, base_entity_id),
    ])
    
    # 6. PID Debug Sensors
    for pid_attr, name_suffix, icon in [
        ("pid_p", "PID P-Anteil", "mdi:chart-line-variant"),
        ("pid_i", "PID I-Anteil", "mdi:chart-line-variant"),
        ("pid_d", "PID D-Anteil", "mdi:chart-line-variant"),
        ("pid_ff", "PID Feed-Forward", "mdi:weather-cloudy-arrow-right"),
        ("pid_integral_error", "PID Integral Summe", "mdi:sigma"),
    ]:
        sensors.append(SonClouTRVPIDSensor(hass, config_entry, climate_entity_id, pid_attr, name_suffix, icon))
    
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


class SonClouTRVNativeValvePositionSensor(SensorEntity):
    """Native valve position sensor reading from SonTRV climate entity.
    
    This sensor reads the valve position directly from the SonTRV climate entity's
    extra state attributes, ensuring it's always available even if the TRV doesn't
    expose a valve_opening_degree entity.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        climate_entity_id: str | None = None,
    ) -> None:
        """Initialize the native valve position sensor."""
        self.hass = hass
        self._config_entry = config_entry
        self._climate_entity_id = climate_entity_id
        self._remove_listener = None
        
        self._attr_name = f"{config_entry.data[CONF_NAME]} Ventilposition"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_native_valve_position"
        self._attr_icon = "mdi:valve"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = None
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data[CONF_NAME]}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.1.1",
        )
        
        self._attr_extra_state_attributes = {
            "description": "Aktuelle Ventilöffnung von SonTRV (unabhängig vom TRV).",
            "source": "climate entity attributes"
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # If ID was not passed in init, try to find it (fallback)
        if not self._climate_entity_id:
            entity_reg = er.async_get(self.hass)
            for entity in entity_reg.entities.values():
                if (entity.config_entry_id == self._config_entry.entry_id 
                    and entity.domain == "climate"):
                    self._climate_entity_id = entity.entity_id
                    _LOGGER.info(
                        "Native valve position sensor found climate entity: %s",
                        self._climate_entity_id,
                    )
                    break
        
        if not self._climate_entity_id:
            _LOGGER.error(
                "Native valve position sensor could not find climate entity for config_entry_id: %s",
                self._config_entry.entry_id,
            )
            return
        
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
        """Update valve position from climate entity attributes."""
        if not self._climate_entity_id:
            return
        
        climate_state = self.hass.states.get(self._climate_entity_id)
        if not climate_state:
            return
        
        try:
            # Read valve_position from extra_state_attributes
            valve_position = climate_state.attributes.get("valve_position")
            if valve_position is not None:
                self._attr_native_value = int(valve_position)
            else:
                _LOGGER.debug(
                    "valve_position attribute not found in climate entity %s",
                    self._climate_entity_id,
                )
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error reading valve_position from climate entity: %s",
                err,
            )


class SonClouTRVNativeValveClosingSensor(SensorEntity):
    """Native valve closing sensor derived from SonTRV climate entity.

    This sensor computes the closing percentage as ``100 - valve_position``
    based on the SonTRV climate entity's extra state attributes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        climate_entity_id: str | None = None,
    ) -> None:
        """Initialize the native valve closing sensor."""
        self.hass = hass
        self._config_entry = config_entry
        self._climate_entity_id = climate_entity_id
        self._remove_listener = None

        self._attr_name = f"{config_entry.data[CONF_NAME]} Ventilschließgrad"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_native_valve_closing"
        self._attr_icon = "mdi:valve-closed"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = None

        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {config_entry.data[CONF_NAME]}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.1.1",
        )

        self._attr_extra_state_attributes = {
            "description": "Aktueller Ventilschließgrad von SonTRV (100 - Ventilöffnung).",
            "source": "climate entity attributes",
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # If ID was not passed in init, try to find it (fallback)
        if not self._climate_entity_id:
            entity_reg = er.async_get(self.hass)
            for entity in entity_reg.entities.values():
                if (
                    entity.config_entry_id == self._config_entry.entry_id
                    and entity.domain == "climate"
                ):
                    self._climate_entity_id = entity.entity_id
                    _LOGGER.info(
                        "Native valve closing sensor found climate entity: %s",
                        self._climate_entity_id,
                    )
                    break

        if not self._climate_entity_id:
            _LOGGER.error(
                "Native valve closing sensor could not find climate entity for config_entry_id: %s",
                self._config_entry.entry_id,
            )
            return

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
        """Update closing degree from climate entity attributes."""
        if not self._climate_entity_id:
            return

        climate_state = self.hass.states.get(self._climate_entity_id)
        if not climate_state:
            return

        try:
            valve_position = climate_state.attributes.get("valve_position")
            if valve_position is not None:
                opening = int(valve_position)
                closing = max(0, min(100, 100 - opening))
                self._attr_native_value = closing
            else:
                _LOGGER.debug(
                    "valve_position attribute not found in climate entity %s (closing sensor)",
                    self._climate_entity_id,
                )
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error reading valve_position for closing sensor from climate entity: %s",
                err,
            )


# Helper function for device info
def get_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """Get standard device info for all sensors."""
    return DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=f"SonTRV {config_entry.data[CONF_NAME]}",
        manufacturer="k2dp2k",
        model="Smart Thermostat Control",
        sw_version="1.1.1",
    )


# ===== 1. ENERGY & EFFICIENCY SENSORS =====

class SonClouTRVHeatingDurationSensor(RestoreEntity, SensorEntity):
    """Track heating duration (today/week)."""

    def __init__(self, hass, config_entry, valve_entity, period):
        self.hass = hass
        self._valve_entity = valve_entity
        self._period = period
        self._attr_name = f"{config_entry.data['name']} Heizdauer {period.capitalize()}"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_heating_duration_{period}"
        self._attr_icon = "mdi:clock-outline"
        self._attr_native_unit_of_measurement = UnitOfTime.HOURS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_info = get_device_info(config_entry)
        self._duration_seconds = 0
        self._last_valve_state = 0
        self._last_update = None
        self._reset_time = self._get_next_reset()

    def _get_next_reset(self):
        now = dt_util.now()
        if self._period == "today":
            return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        days = (7 - now.weekday()) % 7 or 7
        return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()):
            try:
                self._duration_seconds = float(last.state or 0) * 3600
            except (ValueError, TypeError):
                pass
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._update)
        self._remove_interval = async_track_time_interval(self.hass, self._check_reset, timedelta(minutes=1))
        await self._update()

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _update(self, event=None):
        state = self.hass.states.get(self._valve_entity)
        if not state or state.state in ("unavailable", "unknown"): return
        try:
            pos = float(state.state)
            now = dt_util.now()
            if self._last_update and self._last_valve_state > 0:
                self._duration_seconds += (now - self._last_update).total_seconds()
            self._last_valve_state = pos
            self._last_update = now
            self._attr_native_value = round(self._duration_seconds / 3600, 2)
            self.async_write_ha_state()
        except (ValueError, TypeError):
            pass

    async def _check_reset(self, now=None):
        if dt_util.now() >= self._reset_time:
            self._duration_seconds = 0
            self._reset_time = self._get_next_reset()
            self._attr_native_value = 0
            self.async_write_ha_state()


class SonClouTRVHeatingEnergySensor(RestoreEntity, SensorEntity):
    """Estimate heating energy based on valve position × time."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Geschätzte Heizenergie"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_heating_energy"
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_info = get_device_info(config_entry)
        self._energy_kwh = 0
        self._last_valve_state = 0
        self._last_update = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()):
            try:
                self._energy_kwh = float(last.state or 0)
            except (ValueError, TypeError):
                pass
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._update)
        self._remove_interval = async_track_time_interval(self.hass, self._update, SCAN_INTERVAL)
        await self._update()

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _update(self, event=None):
        state = self.hass.states.get(self._valve_entity)
        if not state or state.state in ("unavailable", "unknown"):
            return
        try:
            pos = float(state.state)
            now = dt_util.now()
            if self._last_update and self._last_valve_state > 0:
                hours = (now - self._last_update).total_seconds() / 3600
                self._energy_kwh += (self._last_valve_state / 100) * HEATING_POWER_PER_PERCENT * hours
            self._last_valve_state = pos
            self._last_update = now
            self._attr_native_value = round(self._energy_kwh, 3)
            self._attr_extra_state_attributes = {
                "power_per_percent_kw": HEATING_POWER_PER_PERCENT,
                "current_power_kw": round((pos / 100) * HEATING_POWER_PER_PERCENT, 3),
            }
            self.async_write_ha_state()
        except (ValueError, TypeError) as err:
            _LOGGER.debug("Error updating energy sensor: %s", err)


class SonClouTRVEfficiencySensor(SensorEntity):
    """Calculate heating efficiency (temp change per valve opening)."""

    def __init__(self, hass, config_entry, climate_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attr_name = f"{config_entry.data['name']} Heizeffizienz"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_efficiency"
        self._attr_icon = "mdi:speedometer"
        self._attr_native_unit_of_measurement = "°C/%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = get_device_info(config_entry)
        self._temp_history = deque(maxlen=10)
        self._valve_history = deque(maxlen=10)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._track)
        self._remove_interval = async_track_time_interval(self.hass, self._calc, timedelta(minutes=5))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _track(self, event):
        state = self.hass.states.get(self._climate_entity)
        if state:
            temp = state.attributes.get("current_temperature")
            valve = state.attributes.get("valve_position")
            if temp is not None and valve is not None:
                self._temp_history.append(float(temp))
                self._valve_history.append(float(valve))

    async def _calc(self, now=None):
        if len(self._temp_history) < 2:
            return
        if not self._valve_history or len(self._valve_history) == 0:
            return
        
        try:
            temp_change = self._temp_history[-1] - self._temp_history[0]
            avg_valve = sum(self._valve_history) / len(self._valve_history)
            if avg_valve > 5:
                self._attr_native_value = round(temp_change / avg_valve, 4)
                self._attr_extra_state_attributes = {
                    "temp_change": round(temp_change, 2),
                    "avg_valve_opening": round(avg_valve, 1),
                }
                self.async_write_ha_state()
        except (ValueError, TypeError, ZeroDivisionError) as err:
            _LOGGER.debug("Error calculating efficiency: %s", err)


# ===== 2. VALVE HEALTH & MAINTENANCE =====

class SonClouTRVLastMovementSensor(RestoreEntity, SensorEntity):
    """Track when valve was last moved."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Letzte Ventilbewegung"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_last_movement"
        self._attr_icon = "mdi:valve"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = get_device_info(config_entry)
        self._last_pos = None
        self._last_movement = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state not in ("unavailable", "unknown"):
            try:
                self._last_movement = dt_util.parse_datetime(last.state)
            except (ValueError, TypeError):
                pass
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._detect)

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _detect(self, event):
        state = event.data.get("new_state")
        if not state or state.state in ("unavailable", "unknown"):
            return
        try:
            pos = float(state.state)
            if self._last_pos is not None and abs(pos - self._last_pos) > 1:
                self._last_movement = dt_util.now()
                self._attr_native_value = self._last_movement
                days = (dt_util.now() - self._last_movement).days if self._last_movement else 0
                self._attr_extra_state_attributes = {"days_since_movement": days}
                self.async_write_ha_state()
            self._last_pos = pos
        except (ValueError, TypeError):
            pass


class SonClouTRVMovementCountSensor(RestoreEntity, SensorEntity):
    """Count valve movements."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Ventilbewegungen"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_movement_count"
        self._attr_icon = "mdi:counter"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_info = get_device_info(config_entry)
        self._count = 0
        self._last_pos = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()):
            try:
                self._count = int(last.state or 0)
            except (ValueError, TypeError):
                pass
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._count_movement)

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _count_movement(self, event):
        state = event.data.get("new_state")
        if not state or state.state in ("unavailable", "unknown"):
            return
        try:
            pos = float(state.state)
            if self._last_pos is not None and abs(pos - self._last_pos) > 1:
                self._count += 1
                self._attr_native_value = self._count
                self.async_write_ha_state()
            self._last_pos = pos
        except (ValueError, TypeError):
            pass


class SonClouTRVTotalRuntimeSensor(RestoreEntity, SensorEntity):
    """Track total valve runtime (lifetime)."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Ventil Gesamtlaufzeit"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_total_runtime"
        self._attr_icon = "mdi:clock-time-eight"
        self._attr_native_unit_of_measurement = UnitOfTime.HOURS
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_info = get_device_info(config_entry)
        self._runtime_seconds = 0
        self._last_valve = 0
        self._last_update = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()):
            try:
                self._runtime_seconds = float(last.state or 0) * 3600
            except (ValueError, TypeError):
                pass
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._update)
        self._remove_interval = async_track_time_interval(self.hass, self._update, SCAN_INTERVAL)

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _update(self, event=None):
        state = self.hass.states.get(self._valve_entity)
        if not state or state.state in ("unavailable", "unknown"):
            return
        try:
            pos = float(state.state)
            now = dt_util.now()
            if self._last_update and self._last_valve > 0:
                delta = (now - self._last_update).total_seconds()
                self._runtime_seconds += delta * (self._last_valve / 100)
            self._last_valve = pos
            self._last_update = now
            self._attr_native_value = round(self._runtime_seconds / 3600, 1)
            self.async_write_ha_state()
        except (ValueError, TypeError):
            pass


# ===== 3. TEMPERATURE ANALYSIS =====

class SonClouTRVTemperatureTrendSensor(SensorEntity):
    """Analyze temperature trend (rising/falling/stable)."""

    def __init__(self, hass, config_entry, climate_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attr_name = f"{config_entry.data['name']} Temperatur-Trend"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_temp_trend"
        self._attr_icon = "mdi:chart-line"
        self._attr_device_info = get_device_info(config_entry)
        self._history = deque(maxlen=30)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._track)
        self._remove_interval = async_track_time_interval(self.hass, self._calc, timedelta(minutes=5))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _track(self, event):
        state = self.hass.states.get(self._climate_entity)
        if state:
            temp = state.attributes.get("current_temperature")
            if temp is not None:
                self._history.append((dt_util.now(), float(temp)))

    async def _calc(self, now=None):
        if len(self._history) < 3: return
        recent = list(self._history)[-10:]
        if len(recent) < 2: return
        change = recent[-1][1] - recent[0][1]
        hours = (recent[-1][0] - recent[0][0]).total_seconds() / 3600
        if hours > 0:
            rate = change / hours
            if rate > 0.1:
                self._attr_native_value, self._attr_icon = "rising", "mdi:trending-up"
            elif rate < -0.1:
                self._attr_native_value, self._attr_icon = "falling", "mdi:trending-down"
            else:
                self._attr_native_value, self._attr_icon = "stable", "mdi:trending-neutral"
            self._attr_extra_state_attributes = {"change_per_hour": round(rate, 3)}
            self.async_write_ha_state()


class SonClouTRVAvgTemperatureSensor(RestoreEntity, SensorEntity):
    """Calculate average daily temperature."""

    def __init__(self, hass, config_entry, climate_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attr_name = f"{config_entry.data['name']} Durchschnittstemperatur"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_avg_temp"
        self._attr_icon = "mdi:thermometer-lines"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = get_device_info(config_entry)
        self._sum, self._count = 0, 0
        self._last_reset = dt_util.now()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._track)
        self._remove_interval = async_track_time_interval(self.hass, self._reset_check, timedelta(hours=1))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _track(self, event):
        state = self.hass.states.get(self._climate_entity)
        if state:
            temp = state.attributes.get("current_temperature")
            if temp is not None:
                self._sum += float(temp)
                self._count += 1
                if self._count > 0:
                    self._attr_native_value = round(self._sum / self._count, 1)
                    self.async_write_ha_state()

    async def _reset_check(self, now=None):
        if dt_util.now().date() != self._last_reset.date():
            self._sum, self._count = 0, 0
            self._last_reset = dt_util.now()
            self._attr_native_value = None
            self.async_write_ha_state()


class SonClouTRVMinMaxTemperatureSensor(RestoreEntity, SensorEntity):
    """Track min/max daily temperature."""

    def __init__(self, hass, config_entry, climate_entity, sensor_type):
        self.hass = hass
        self._climate_entity = climate_entity
        self._type = sensor_type
        self._attr_name = f"{config_entry.data['name']} {'Minimale' if sensor_type == 'min' else 'Maximale'} Temperatur"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_temp_{sensor_type}"
        self._attr_icon = "mdi:thermometer-chevron-down" if sensor_type == "min" else "mdi:thermometer-chevron-up"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = get_device_info(config_entry)
        self._extreme = None
        self._last_reset = dt_util.now()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._track)
        self._remove_interval = async_track_time_interval(self.hass, self._reset_check, timedelta(hours=1))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _track(self, event):
        state = self.hass.states.get(self._climate_entity)
        if state:
            temp = state.attributes.get("current_temperature")
            if temp is not None:
                temp = float(temp)
                if self._extreme is None:
                    self._extreme = temp
                elif (self._type == "min" and temp < self._extreme) or (self._type == "max" and temp > self._extreme):
                    self._extreme = temp
                self._attr_native_value = round(self._extreme, 1)
                self.async_write_ha_state()

    async def _reset_check(self, now=None):
        if dt_util.now().date() != self._last_reset.date():
            self._extreme = None
            self._last_reset = dt_util.now()
            self._attr_native_value = None
            self.async_write_ha_state()


# ===== 4. COMFORT & OPTIMIZATION =====

class SonClouTRVTimeToTargetSensor(SensorEntity):
    """Estimate time to reach target temperature."""

    def __init__(self, hass, config_entry, climate_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attr_name = f"{config_entry.data['name']} Zeit bis Zieltemperatur"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_time_to_target"
        self._attr_icon = "mdi:clock-fast"
        self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_device_info = get_device_info(config_entry)
        self._history = deque(maxlen=10)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._track)
        self._remove_interval = async_track_time_interval(self.hass, self._calc, timedelta(minutes=5))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _track(self, event):
        state = self.hass.states.get(self._climate_entity)
        if state:
            temp = state.attributes.get("current_temperature")
            if temp is not None:
                self._history.append((dt_util.now(), float(temp)))

    async def _calc(self, now=None):
        state = self.hass.states.get(self._climate_entity)
        if not state or len(self._history) < 2: return
        current = state.attributes.get("current_temperature")
        target = state.attributes.get("temperature")
        if current is None or target is None: return
        diff = target - current
        if abs(diff) < 0.2:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"status": "target_reached"}
            self.async_write_ha_state()
            return
        recent = list(self._history)[-5:]
        if len(recent) < 2: return
        time_min = (recent[-1][0] - recent[0][0]).total_seconds() / 60
        temp_change = recent[-1][1] - recent[0][1]
        if time_min > 0 and abs(temp_change) > 0.05:
            rate = temp_change / time_min
            if (diff > 0 and rate > 0) or (diff < 0 and rate < 0):
                self._attr_native_value = round(min(abs(diff / rate), 999))
                self._attr_extra_state_attributes = {"temp_diff": round(diff, 1)}
                self.async_write_ha_state()


class SonClouTRVOverheatWarningSensor(SensorEntity):
    """Warn when temperature exceeds target significantly."""

    def __init__(self, hass, config_entry, climate_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attr_name = f"{config_entry.data['name']} Überhitzungswarnung"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_overheat_warning"
        self._attr_icon = "mdi:alert-circle"
        self._attr_device_info = get_device_info(config_entry)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._check)

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _check(self, event=None):
        state = self.hass.states.get(self._climate_entity)
        if not state: return
        current = state.attributes.get("current_temperature")
        target = state.attributes.get("temperature")
        if current is None or target is None: return
        diff = current - target
        if diff > 2.0:
            self._attr_native_value, self._attr_icon = "warning", "mdi:fire-alert"
        else:
            self._attr_native_value, self._attr_icon = "ok", "mdi:check-circle"
        self._attr_extra_state_attributes = {"temp_difference": round(diff, 1)}
        self.async_write_ha_state()


class SonClouTRVUnderheatWarningSensor(SensorEntity):
    """Warn when valve fully open but temperature not rising."""

    def __init__(self, hass, config_entry, climate_entity, valve_entity):
        self.hass = hass
        self._climate_entity = climate_entity
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Unterheizungswarnung"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_underheat_warning"
        self._attr_icon = "mdi:alert-circle-outline"
        self._attr_device_info = get_device_info(config_entry)
        self._history = deque(maxlen=10)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity, self._valve_entity], self._check)
        self._remove_interval = async_track_time_interval(self.hass, self._check, timedelta(minutes=10))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _check(self, event=None):
        climate = self.hass.states.get(self._climate_entity)
        valve = self.hass.states.get(self._valve_entity)
        if not climate or not valve: return
        current = climate.attributes.get("current_temperature")
        target = climate.attributes.get("temperature")
        try:
            pos = float(valve.state)
        except: return
        if current is None or target is None: return
        self._history.append(float(current))
        if pos > 80 and current < target - 1 and len(self._history) >= 5:
            if self._history[-1] - self._history[0] < 0.2:
                self._attr_native_value, self._attr_icon = "warning", "mdi:alert"
                self.async_write_ha_state()
                return
        self._attr_native_value, self._attr_icon = "ok", "mdi:check-circle-outline"
        self.async_write_ha_state()


# ===== 5. SYSTEM STATUS =====

class SonClouTRVConnectionStatusSensor(SensorEntity):
    """Monitor MQTT/Zigbee connection quality."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Verbindungsstatus"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_connection_status"
        self._attr_icon = "mdi:wifi"
        self._attr_device_info = get_device_info(config_entry)
        self._last_seen = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._check)
        self._remove_interval = async_track_time_interval(self.hass, self._check, timedelta(minutes=5))

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()
        if hasattr(self, '_remove_interval'): self._remove_interval()

    @callback
    async def _check(self, event=None):
        state = self.hass.states.get(self._valve_entity)
        if not state or state.state in ("unavailable", "unknown"):
            self._attr_native_value, self._attr_icon = "offline", "mdi:wifi-off"
        else:
            self._last_seen = dt_util.now()
            self._attr_native_value, self._attr_icon = "online", "mdi:wifi-check"
        self.async_write_ha_state()


class SonClouTRVLastUpdateSensor(SensorEntity):
    """Show when last data was received."""

    def __init__(self, hass, config_entry, valve_entity):
        self.hass = hass
        self._valve_entity = valve_entity
        self._attr_name = f"{config_entry.data['name']} Letztes Update"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_last_update"
        self._attr_icon = "mdi:clock-check"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = get_device_info(config_entry)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._valve_entity], self._update)

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _update(self, event):
        if (state := event.data.get("new_state")) and state.state not in ("unavailable", "unknown"):
            self._attr_native_value = dt_util.now()
            self.async_write_ha_state()


class SonClouTRVBatteryStatusSensor(SensorEntity):
    """Show battery status as text (Gut/Mittel/Schwach)."""

    def __init__(self, hass, config_entry, base_entity_id):
        self.hass = hass
        self._base_entity_id = base_entity_id
        self._battery_entity = None
        self._attr_name = f"{config_entry.data['name']} Batteriestatus"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_battery_status"
        self._attr_icon = "mdi:battery"
        self._attr_device_info = get_device_info(config_entry)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        for suffix in ["_battery", "battery", "_battery_level"]:
            entity = f"sensor.{self._base_entity_id}{suffix}"
            if self.hass.states.get(entity):
                self._battery_entity = entity
                break
        if self._battery_entity:
            self._remove_listener = async_track_state_change_event(self.hass, [self._battery_entity], self._update)
            await self._update()

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _update(self, event=None):
        if not self._battery_entity:
            return
        state = self.hass.states.get(self._battery_entity)
        if not state or state.state in ("unavailable", "unknown"):
            return
        try:
            level = float(state.state)
            if level > 70:
                self._attr_native_value, self._attr_icon = "Gut", "mdi:battery"
            elif level > 30:
                self._attr_native_value, self._attr_icon = "Mittel", "mdi:battery-50"
            else:
                self._attr_native_value, self._attr_icon = "Schwach", "mdi:battery-alert"
            self._attr_extra_state_attributes = {"battery_level": level}
            self.async_write_ha_state()
        except (ValueError, TypeError):
            pass


# ===== 6. PID DEBUG SENSORS =====

class SonClouTRVPIDSensor(SensorEntity):
    """Sensor to track internal PID values."""

    def __init__(self, hass, config_entry, climate_entity, attribute, name_suffix, icon):
        self.hass = hass
        self._climate_entity = climate_entity
        self._attribute = attribute
        self._attr_name = f"{config_entry.data['name']} {name_suffix}"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{attribute}"
        self._attr_icon = icon
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # Integral error has no % unit technically, but others do
        if attribute != "pid_integral_error":
            self._attr_native_unit_of_measurement = PERCENTAGE
            
        self._attr_device_info = get_device_info(config_entry)
        # Enable by default for debugging visibility
        self._attr_entity_registry_enabled_default = True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._remove_listener = async_track_state_change_event(self.hass, [self._climate_entity], self._update)
        # Initial update
        await self._update()

    async def async_will_remove_from_hass(self):
        if hasattr(self, '_remove_listener'): self._remove_listener()

    @callback
    async def _update(self, event=None):
        state = self.hass.states.get(self._climate_entity)
        if not state: return
        
        val = state.attributes.get(self._attribute)
        if val is not None:
            self._attr_native_value = float(val)
            self.async_write_ha_state()
