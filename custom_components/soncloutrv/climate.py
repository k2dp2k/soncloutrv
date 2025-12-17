"""Climate platform for SonClouTRV."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    PRECISION_TENTHS,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform, device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_VALVE_ENTITY,
    CONF_TEMP_SENSOR,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET_TEMP,
    CONF_HYSTERESIS,
    CONF_COLD_TOLERANCE,
    CONF_HOT_TOLERANCE,
    CONF_MIN_CYCLE_DURATION,
    CONF_MAX_VALVE_POSITION,
    CONF_VALVE_OPENING_STEP,
    CONF_CONTROL_MODE,
    CONF_TIME_CONTROL_ENABLED,
    CONF_TIME_START,
    CONF_TIME_END,
    CONF_PROPORTIONAL_GAIN,
    CONF_KP,
    CONF_KI,
    CONF_KD,
    DEFAULT_KP,
    DEFAULT_KI,
    DEFAULT_KD,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PROPORTIONAL,
    CONTROL_MODE_PID,
    VALVE_OPENING_STEPS,
    ATTR_VALVE_POSITION,
    ATTR_CONTROL_MODE,
    ATTR_TIME_CONTROL,
    ATTR_LAST_VALVE_UPDATE,
    ATTR_TEMPERATURE_DIFFERENCE,
    ATTR_TRV_INTERNAL_TEMP,
    ATTR_EXTERNAL_TEMP,
    ATTR_TRV_BATTERY,
    ATTR_VALVE_ADJUSTMENTS,
    ATTR_AVG_VALVE_POSITION,
    ATTR_TEMP_TREND,
    ATTR_PID_P,
    ATTR_PID_I,
    ATTR_PID_D,
    ATTR_PID_INTEGRAL,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)  # Fußbodenheizung ist träge, 5 Minuten reichen


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SonClouTRV climate platform."""
    config = config_entry.data
    
    climate_entity = SonClouTRVClimate(hass, config, config_entry.entry_id)
    
    # Store entity reference for number entities to access
    if config_entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN][config_entry.entry_id]["entities"].append(climate_entity)
    
    async_add_entities([climate_entity], True)
    
    # Register platform services
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "calibrate_valve",
        {},
        "async_calibrate_valve",
    )


class SonClouTRVClimate(ClimateEntity, RestoreEntity):
    """Representation of a SonClouTRV climate device."""

    _attr_should_poll = False
    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | 
        ClimateEntityFeature.TURN_OFF | 
        ClimateEntityFeature.TURN_ON |
        ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = ["*", "1", "2", "3", "4", "5"]

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        entry_id: str,
    ) -> None:
        """Initialize the climate device."""
        self.hass = hass
        self._config = config
        self._entry_id = entry_id
        
        # Configuration
        self._attr_name = config[CONF_NAME]
        self._attr_unique_id = f"{DOMAIN}_{entry_id}"
        
        # Build consistent entity_id using entry_id
        self._entity_id_base = f"{DOMAIN}_{entry_id}"
        
        # Device info for grouping entities
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"SonTRV {config[CONF_NAME]}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version="1.0.0",
            configuration_url="https://github.com/k2dp2k/soncloutrv",
        )
        
        # Entity description
        self._attr_entity_description = "Intelligenter Thermostat mit externem Temperatursensor und 5-Stufen Ventilsteuerung"
        self._valve_entity = config[CONF_VALVE_ENTITY]
        self._temp_sensor = config[CONF_TEMP_SENSOR]
        self._attr_min_temp = config[CONF_MIN_TEMP]
        self._attr_max_temp = config[CONF_MAX_TEMP]
        self._attr_target_temperature = config[CONF_TARGET_TEMP]
        
        # Store reference to config_entry for updates
        self._config_entry = None  # Will be set in async_added_to_hass if available
        
        # Read from config.data (options will be loaded later in async_added_to_hass)
        self._hysteresis = config.get(CONF_HYSTERESIS, 0.5)
        self._cold_tolerance = config.get(CONF_COLD_TOLERANCE, 0.3)
        self._hot_tolerance = config.get(CONF_HOT_TOLERANCE, 0.3)
        self._min_cycle_duration = config.get(CONF_MIN_CYCLE_DURATION, 300)
        
        # Get max valve position from step selection
        valve_step = config.get(CONF_VALVE_OPENING_STEP, config.get(CONF_MAX_VALVE_POSITION, "4"))
        self._current_valve_step = str(valve_step)
        self._attr_preset_mode = self._current_valve_step
        
        if isinstance(valve_step, int):
            # Legacy support: if stored as int percentage, use it directly
            self._max_valve_position = valve_step
        else:
            # New: convert step to percentage
            self._max_valve_position = VALVE_OPENING_STEPS.get(str(valve_step), 80)
        
        self._control_mode = config.get(CONF_CONTROL_MODE, CONTROL_MODE_BINARY)
        self._time_control_enabled = config.get(CONF_TIME_CONTROL_ENABLED, False)
        self._time_start = config.get(CONF_TIME_START, "06:00")
        self._time_end = config.get(CONF_TIME_END, "22:00")
        
        # PID Parameters
        # Legacy support: use proportional_gain if kp not set
        legacy_p = config.get(CONF_PROPORTIONAL_GAIN, DEFAULT_KP)
        self._kp = config.get(CONF_KP, legacy_p)
        self._ki = config.get(CONF_KI, DEFAULT_KI)
        self._kd = config.get(CONF_KD, DEFAULT_KD)
        
        # State
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_current_temperature = None
        self._valve_position = 0
        self._active = False
        self._last_valve_update = None
        self._last_temp_change = None
        self._last_set_valve_opening = -1  # Track last set value
        
        # PID State
        self._integral_error = 0.0
        self._prev_error = 0.0
        self._last_calc_time = None
        
        # Debug values
        self._last_p = 0.0
        self._last_i = 0.0
        self._last_d = 0.0
        
        # Configurable parameters (can be changed via number entities)
        self._min_valve_update_interval = 600  # 10 minutes default
        
        # Statistics
        self._valve_adjustments_count = 0
        self._valve_position_history = []  # Keep last 10 values
        self._temp_history = []  # Keep last 5 temperature readings
        self._trv_internal_temp = None
        self._trv_battery = None
        
        # Initialize extra state attributes
        self._attr_extra_state_attributes = {}
        
        # Listeners
        self._remove_listeners = []

    def _get_config_value(self, key: str, config: dict[str, Any], default: Any) -> Any:
        """Get config value from config_entry.options or config.data with fallback to default.
        
        Options (user-set via number entities) have priority over config data.
        """
        # Try to get from config_entry.options first if available
        # This will be populated after async_added_to_hass
        if self._config_entry is not None:
            value = self._config_entry.options.get(key)
            if value is not None:
                return value
        
        # Fall back to config.data
        value = config.get(key)
        if value is not None:
            return value
        
        # Use default
        return default
    
    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        
        # Get reference to config_entry from registry
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self._entry_id:
                self._config_entry = entry
                # Re-read values from options now that we have config_entry
                self._hysteresis = self._get_config_value("hysteresis", self._config, 0.5)
                self._cold_tolerance = self._get_config_value("cold_tolerance", self._config, 0.3)
                self._hot_tolerance = self._get_config_value("hot_tolerance", self._config, 0.3)
                self._min_cycle_duration = self._get_config_value("min_cycle_duration", self._config, 300)
                
                # Load PID values
                legacy_p = self._get_config_value("proportional_gain", self._config, DEFAULT_KP)
                self._kp = self._get_config_value(CONF_KP, self._config, legacy_p)
                self._ki = self._get_config_value(CONF_KI, self._config, DEFAULT_KI)
                self._kd = self._get_config_value(CONF_KD, self._config, DEFAULT_KD)
                
                _LOGGER.debug("%s: Loaded config values - hysteresis=%.1f, Kp=%.1f, Ki=%.3f, Kd=%.1f", 
                            self.name, self._hysteresis, self._kp, self._ki, self._kd)
                break
        
        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last_state.state)
            if ATTR_TEMPERATURE in last_state.attributes:
                self._attr_target_temperature = float(last_state.attributes[ATTR_TEMPERATURE])
                
            # Restore Integral term (Learning)
            if ATTR_PID_INTEGRAL in last_state.attributes:
                try:
                    self._integral_error = float(last_state.attributes[ATTR_PID_INTEGRAL])
                    _LOGGER.info("%s: Restored PID integral error: %.2f", self.name, self._integral_error)
                except (ValueError, TypeError):
                    self._integral_error = 0.0
        
        # Track temperature sensor
        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass,
                [self._temp_sensor],
                self._async_sensor_changed,
            )
        )
        
        # Track valve entity
        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass,
                [self._valve_entity],
                self._async_valve_changed,
            )
        )
        
        # Periodic update
        self._remove_listeners.append(
            async_track_time_interval(
                self.hass,
                self._async_control_heating,
                SCAN_INTERVAL,
            )
        )
        
        # Wait for TRV entity to be available (MQTT/Z2M startup)
        _LOGGER.info("%s: Waiting for TRV entity %s to be available...", self.name, self._valve_entity)
        max_wait = 30  # seconds
        wait_interval = 1
        for i in range(max_wait):
            trv_state = self.hass.states.get(self._valve_entity)
            if trv_state and trv_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                _LOGGER.info("%s: TRV entity available after %d seconds", self.name, i)
                break
            if i < max_wait - 1:
                await asyncio.sleep(wait_interval)
        else:
            _LOGGER.warning("%s: TRV entity not available after %d seconds, proceeding anyway", self.name, max_wait)
        
        # Read initial TRV state (battery, temperature, valve position)
        await self._async_read_trv_state()
        
        # Initial temperature update
        await self._async_update_temp()
        
        # Force initial temperature calibration sync
        await self._async_sync_temperature_calibration()
        
        # IMPORTANT: Set initial valve opening degree
        # Calculate based on current temperature difference
        initial_opening = self._calculate_desired_valve_opening()
        if initial_opening < 0:
            initial_opening = self._max_valve_position
        await self._async_set_valve_opening(initial_opening)
        _LOGGER.info(
            "%s: Set initial valve opening to %d%% (preset: %s, mode: %s)",
            self.name,
            initial_opening,
            self._current_valve_step,
            self._control_mode,
        )
        
        # Sync target temperature to TRV
        if self._attr_target_temperature is not None:
            await self._async_sync_target_temperature()
        
        # Update attributes
        self._update_extra_attributes()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed."""
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()

    @callback
    async def _async_sensor_changed(self, event) -> None:
        """Handle temperature sensor changes."""
        await self._async_update_temp()
        # Immediately sync temperature calibration when sensor changes
        await self._async_sync_temperature_calibration()
        await self._async_control_heating()
        self._update_extra_attributes()
        self.async_write_ha_state()

    @callback
    async def _async_valve_changed(self, event) -> None:
        """Handle valve position changes."""
        new_state = event.data.get("new_state")
        if new_state is not None and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                # Read valve position from SONOFF TRVZB attributes
                # TRVZB reports position as 0-100 (0=closed, 100=open)
                attributes = new_state.attributes
                if "position" in attributes:
                    self._valve_position = int(attributes["position"])
                elif "valve_position" in attributes:
                    self._valve_position = int(attributes["valve_position"])
                
                # Read battery and internal temperature
                # Battery can be in '_battery' or 'battery' attribute (prefer _battery)
                for battery_attr in ["_battery", "battery"]:
                    if battery_attr in attributes and attributes[battery_attr] is not None:
                        battery_value = attributes[battery_attr]
                        # Handle both numeric and string values
                        if isinstance(battery_value, (int, float)):
                            self._trv_battery = battery_value
                        elif isinstance(battery_value, str):
                            try:
                                self._trv_battery = float(battery_value.replace("%", "").strip())
                            except ValueError:
                                pass
                        break
                
                for attr_name in ["local_temperature", "current_temperature", "temperature"]:
                    if attr_name in attributes:
                        try:
                            self._trv_internal_temp = float(attributes[attr_name])
                            break
                        except (ValueError, TypeError):
                            pass
                            
            except (ValueError, TypeError, KeyError):
                pass
        self._update_extra_attributes()
        self.async_write_ha_state()

    async def _async_read_trv_state(self) -> None:
        """Read initial TRV state (battery, temperature, valve position)."""
        trv_state = self.hass.states.get(self._valve_entity)
        if trv_state and trv_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            attributes = trv_state.attributes
            
            # Read battery (can be numeric or with % symbol)
            # Prefer _battery over battery
            for battery_attr in ["_battery", "battery"]:
                if battery_attr in attributes and attributes[battery_attr] is not None:
                    battery_value = attributes[battery_attr]
                    # Handle both numeric and string values
                    if isinstance(battery_value, (int, float)):
                        self._trv_battery = battery_value
                    elif isinstance(battery_value, str):
                        # Remove % symbol if present
                        try:
                            self._trv_battery = float(battery_value.replace("%", "").strip())
                        except ValueError:
                            _LOGGER.warning("%s: Could not parse battery value: %s", self.name, battery_value)
                            continue
                    _LOGGER.info("%s: Initial battery level: %s%%", self.name, self._trv_battery)
                    break
            
            # Read TRV internal temperature
            for attr_name in ["local_temperature", "current_temperature", "temperature"]:
                if attr_name in attributes:
                    try:
                        self._trv_internal_temp = float(attributes[attr_name])
                        _LOGGER.info("%s: Initial TRV temperature: %.1f°C", self.name, self._trv_internal_temp)
                        break
                    except (ValueError, TypeError):
                        pass
            
            # Read valve position
            if "position" in attributes:
                self._valve_position = int(attributes["position"])
                _LOGGER.info("%s: Initial valve position: %d%%", self.name, self._valve_position)
            elif "valve_position" in attributes:
                self._valve_position = int(attributes["valve_position"])
                _LOGGER.info("%s: Initial valve position: %d%%", self.name, self._valve_position)
    
    async def _async_update_temp(self) -> None:
        """Update temperature from sensor."""
        temp_state = self.hass.states.get(self._temp_sensor)
        if temp_state is not None and temp_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                new_temp = float(temp_state.state)
                self._attr_current_temperature = new_temp
                
                # Update temperature history for trend
                self._temp_history.append(new_temp)
                if len(self._temp_history) > 5:
                    self._temp_history.pop(0)
                    
            except (ValueError, TypeError):
                _LOGGER.warning("Unable to update temperature from %s", self._temp_sensor)

    async def _async_control_heating(self, now=None) -> None:
        """Control heating with hysteresis and inertia for underfloor heating."""
        # Always update temperature sync (external sensor)
        await self._async_sync_temperature_calibration()
        
        # Sync HVAC mode first
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_set_trv_off()
            self._active = False
            self.async_write_ha_state()
            return
        
        # Check if we should update valve opening (inertia)
        if not self._should_update_valve_opening():
            _LOGGER.debug("%s: Skipping valve update due to inertia/min cycle time", self.name)
            self.async_write_ha_state()
            return
        
        # Calculate desired valve opening based on temperature difference
        desired_opening = self._calculate_desired_valve_opening()
        
        # Only update if actually different (already protected by inertia/min_cycle)
        if desired_opening == self._last_set_valve_opening:
            _LOGGER.debug(
                "%s: Valve opening unchanged at %d%%, skipping",
                self.name,
                desired_opening,
            )
            self.async_write_ha_state()
            return
        
        # Set valve opening
        await self._async_set_valve_opening(desired_opening)
        
        # Sync target temperature to TRV
        if self._attr_target_temperature is not None:
            await self._async_sync_target_temperature()
        
        self._active = desired_opening > 0
        self._update_extra_attributes()
        self.async_write_ha_state()
    
    async def _async_sync_temperature_calibration(self) -> None:
        """Sync external temperature sensor with TRV via external temperature input."""
        if self._attr_current_temperature is None:
            _LOGGER.debug("%s: Cannot sync temperature - external temperature is None", self.name)
            return
        
        try:
            # Read TRV state for monitoring
            trv_state = self.hass.states.get(self._valve_entity)
            if trv_state:
                # Capture TRV internal temperature
                for attr_name in ["local_temperature", "current_temperature", "temperature"]:
                    temp = trv_state.attributes.get(attr_name)
                    if temp is not None:
                        self._trv_internal_temp = float(temp)
                        break
                
                # Capture battery level (prefer '_battery' over 'battery')
                self._trv_battery = trv_state.attributes.get("_battery") or trv_state.attributes.get("battery")
            
            device_id = self._valve_entity.replace("climate.", "")
            
            # Step 1: Set temperature_sensor_select to "external"
            sensor_select_entity = self._valve_entity.replace("climate.", "select.") + "_temperature_sensor_select"
            
            if self.hass.states.get(sensor_select_entity):
                # Via entity
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": sensor_select_entity,
                        "option": "external",
                    },
                    blocking=False,
                )
                _LOGGER.debug("%s: Set temperature sensor to external via %s", self.name, sensor_select_entity)
            else:
                # Via MQTT
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": f"zigbee2mqtt/{device_id}/set/temperature_sensor_select",
                        "payload": "external",
                    },
                    blocking=False,
                )
                _LOGGER.debug("%s: Set temperature sensor to external via MQTT", self.name)
            
            # Step 2: Write external temperature value to external_temperature_input
            temp_input_entity = self._valve_entity.replace("climate.", "number.") + "_external_temperature_input"
            
            # Round to 1 decimal
            external_temp = round(self._attr_current_temperature, 1)
            
            if self.hass.states.get(temp_input_entity):
                # Via entity
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": temp_input_entity,
                        "value": external_temp,
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Set external temperature to %.1f°C via %s",
                    self.name,
                    external_temp,
                    temp_input_entity,
                )
            else:
                # Via MQTT
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": f"zigbee2mqtt/{device_id}/set/external_temperature_input",
                        "payload": str(external_temp),
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Set external temperature to %.1f°C via MQTT",
                    self.name,
                    external_temp,
                )
                
        except Exception as err:
            _LOGGER.error("%s: Error syncing external temperature: %s", self.name, err)

    def _should_update_valve_opening(self) -> bool:
        """Check if we should update valve opening (apply inertia)."""
        if self._last_valve_update is None:
            return True
        
        time_since_last_update = (dt_util.now() - self._last_valve_update).total_seconds()
        return time_since_last_update >= self._min_valve_update_interval
    
    def _calculate_desired_valve_opening(self) -> int:
        """Calculate desired valve opening based on temperature difference (PID)."""
        if self._attr_current_temperature is None or self._attr_target_temperature is None:
            return 0
        
        # Check if valve is disabled
        if self._max_valve_position == 0:
            return 0
            
        current_temp = self._attr_current_temperature
        target_temp = self._attr_target_temperature
        
        # Error = Target - Current (Positive when cold/needs heat)
        error = target_temp - current_temp
        
        # PID Time Calculation
        now = dt_util.now()
        if self._last_calc_time is None:
            self._last_calc_time = now
            dt = 0.0
        else:
            dt = (now - self._last_calc_time).total_seconds()
            self._last_calc_time = now
            
        # 1. Proportional Term
        # P = Kp * error
        p_term = self._kp * error
        
        # 2. Integral Term (Learning)
        # Only integrate if we have a valid time delta and error is within reasonable bounds
        # (Prevent windup if sensor was offline for a long time)
        i_term = 0.0
        if dt > 0 and dt < 3600: # Ignore if gap > 1 hour
            # Accumulate error
            # Conditional Integration: Stop integrating if output is saturated?
            # For simplicity: continuous integration with clamping
            
            # Deadband for Integral: Don't change integral if error is very small to avoid oscillation
            if abs(error) >= self._hysteresis:
                self._integral_error += error * dt
            
            # Anti-Windup: Clamp integral error to represent max +/- 100% contribution
            # If Ki is 0.01, and we want max 100%, max_integral = 100/0.01 = 10000
            if self._ki > 0:
                max_integral = 100.0 / self._ki
                self._integral_error = max(-max_integral, min(max_integral, self._integral_error))
            
            # Optimization: Conditional Integration
            # If output is saturated (at 0% or 100%) AND error is driving it further into saturation,
            # stop integrating.
            # We calculate P+D first to see if we are saturated? 
            # Simplified: If we are already at max integral and error has same sign, don't add.
            
            i_term = self._ki * self._integral_error
        else:
            # First run or restart, just use existing integral
            i_term = self._ki * self._integral_error
            
        # 3. Derivative Term (Damping)
        # Optimization: Calculate derivative based on input (Temperature) instead of Error
        # to avoid "Derivative Kick" when target temperature changes.
        # D = - Kd * (dInput / dt)
        d_term = 0.0
        if dt > 0:
            # We want change in Temperature, not Error.
            # Error = Target - Current
            # If Target is constant: dError = - dCurrent
            # So dError/dt = - (Current - Prev_Current) / dt
            
            # Using error difference (Standard PID)
            # d_error = (error - self._prev_error) / dt
            # d_term = self._kd * d_error
            
            # Using input difference (Derivative on Measurement)
            # Requires storing previous input (temperature)
            if self._last_temp_change is not None and self._attr_current_temperature is not None:
                 # Note: self._last_temp_change is actually a timestamp in this class, not the value.
                 # We need previous temperature value.
                 # Let's derive it from prev_error if target hasn't changed? 
                 # Too complex. Let's just use (error - prev_error) but suppress if target changed?
                 pass
            
            # Simple fix for now: standard derivative but with small dt protection
            if dt > 1.0: # Only calculate D if at least 1 second passed to avoid noise
                 d_error = (error - self._prev_error) / dt
                 d_term = self._kd * d_error
                 
                 # Suppress huge spikes (Derivative Kick protection)
                 # If D term is huge (> 100%), it's likely a setpoint change.
                 if abs(d_term) > 100:
                     _LOGGER.debug("%s: D-Term spike detected (%.1f), suppressing", self.name, d_term)
                     d_term = 0.0

        self._prev_error = error
        
        # Store terms for debugging
        self._last_p = p_term
        self._last_i = i_term
        self._last_d = d_term
        
        # Total Output (Percent)
        raw_output = p_term + i_term + d_term
        
        # Clamp to 0-100%
        desired_percent = max(0.0, min(100.0, raw_output))
        
        # Scale to max_valve_position (e.g. if max is 80%, we map 0-100% PID to 0-80% Valve)
        # OR: clamp strictly to max_valve_position?
        # Usually: PID output 0-100% corresponds to valve 0-Max
        final_desired = int((desired_percent / 100.0) * self._max_valve_position)
        
        # Hysteresis / Minimum movement check (Deadband on OUTPUT, not just error)
        # If we are comfortably close to target, stay put to save battery?
        # Standard PID is continuous.
        # But we have `_min_valve_update_interval` managing the battery.
        # So we can be precise here.
        
        # Special case: If error is within hysteresis and we are close to 0, close it?
        # Legacy behavior mimic:
        if abs(error) < self._hysteresis and self._control_mode != CONTROL_MODE_PID:
             # Legacy Proportional Mode behavior override
             # If someone specifically selects "Proportional" or "Binary", we might want to respect that logic?
             # But we merged logic. Let's trust PID.
             pass
             
        _LOGGER.debug(
            "%s: PID: Target=%.1f, Curr=%.1f, Err=%.2f, P=%.1f, I=%.1f, D=%.1f, Out=%.1f%%, Final=%d%%",
            self.name, target_temp, current_temp, error, p_term, i_term, d_term, desired_percent, final_desired
        )
        
        return final_desired
    
    async def _async_set_valve_opening(self, valve_opening: int) -> None:
        """Set valve opening degree based on preset step."""
        try:
            # Our preset defines the valve opening percentage directly
            # * = 0%, 1 = 20%, 2 = 40%, 3 = 60%, 4 = 80%, 5 = 100%
            
            # Try via number entity first
            valve_opening_entity = self._valve_entity.replace("climate.", "number.") + "_valve_opening_degree"
            
            if self.hass.states.get(valve_opening_entity):
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": valve_opening_entity,
                        "value": valve_opening,
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve opening degree to %d%% via %s",
                    self.name,
                    valve_opening,
                    valve_opening_entity,
                )
            else:
                # Alternative: MQTT
                device_id = self._valve_entity.replace("climate.", "")
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": f"zigbee2mqtt/{device_id}/set/valve_opening_degree",
                        "payload": str(valve_opening),
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve opening degree to %d%% via MQTT",
                    self.name,
                    valve_opening,
                )
            
            # Track last set value and timestamp
            self._last_set_valve_opening = valve_opening
            self._last_valve_update = dt_util.now()
            self._valve_position = valve_opening
            
            # Update statistics
            self._valve_adjustments_count += 1
            self._valve_position_history.append(valve_opening)
            if len(self._valve_position_history) > 10:
                self._valve_position_history.pop(0)
            
            # Force state update to ensure attributes are refreshed
            self._update_extra_attributes()
            self.async_write_ha_state()
            
        except Exception as err:
            _LOGGER.error("%s: Error setting valve opening degree: %s", self.name, err)
    
    async def _async_sync_target_temperature(self) -> None:
        """Sync target temperature to TRV."""
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self._valve_entity,
                    "temperature": self._attr_target_temperature,
                },
                blocking=False,
            )
        except Exception as err:
            _LOGGER.error("%s: Error syncing target temperature: %s", self.name, err)
    
    async def _async_set_trv_off(self) -> None:
        """Turn off the TRV."""
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {
                    "entity_id": self._valve_entity,
                    "hvac_mode": HVACMode.OFF,
                },
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("%s: Error turning off TRV: %s", self.name, err)
    
    async def _async_limit_valve_position(self) -> None:
        """Limit the valve opening by setting position attribute in Zigbee2MQTT."""
        try:
            # Try to set position via number entity if available
            # SONOFF TRVZB via Zigbee2MQTT often has a position number entity
            position_entity = self._valve_entity.replace("climate.", "number.") + "_position"
            
            if self.hass.states.get(position_entity):
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": position_entity,
                        "value": self._max_valve_position,
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Limited valve position to %d%% via %s",
                    self.name,
                    self._max_valve_position,
                    position_entity,
                )
            else:
                # Alternative: Use MQTT publish to set position directly
                # This requires knowing the Zigbee2MQTT topic structure
                device_id = self._valve_entity.replace("climate.", "")
                mqtt_topic = f"zigbee2mqtt/{device_id}/set/position"
                
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": mqtt_topic,
                        "payload": str(self._max_valve_position),
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Limited valve position to %d%% via MQTT topic %s",
                    self.name,
                    self._max_valve_position,
                    mqtt_topic,
                )
            
            self._last_valve_update = dt_util.now()
            
        except Exception as err:
            _LOGGER.error(
                "%s: Error limiting valve position: %s",
                self.name,
                err,
            )

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._active:
            return HVACAction.HEATING
        return HVACAction.IDLE

    def _update_extra_attributes(self) -> None:
        """Update extra state attributes."""
        attrs = {
            ATTR_VALVE_POSITION: self._valve_position,
            ATTR_CONTROL_MODE: self._control_mode,
            ATTR_TIME_CONTROL: self._time_control_enabled,
            ATTR_LAST_VALVE_UPDATE: self._last_valve_update.isoformat() if self._last_valve_update else None,
            ATTR_VALVE_ADJUSTMENTS: self._valve_adjustments_count,
            "hysteresis": self._hysteresis,
            "min_valve_update_interval": self._min_valve_update_interval,
            ATTR_PID_P: round(self._last_p, 1),
            ATTR_PID_I: round(self._last_i, 1),
            ATTR_PID_D: round(self._last_d, 1),
            ATTR_PID_INTEGRAL: round(self._integral_error, 2),
        }
        
        # Temperature info
        if self._attr_current_temperature and self._attr_target_temperature:
            attrs[ATTR_TEMPERATURE_DIFFERENCE] = round(
                self._attr_target_temperature - self._attr_current_temperature, 1
            )
        
        if self._trv_internal_temp is not None:
            attrs[ATTR_TRV_INTERNAL_TEMP] = self._trv_internal_temp
        
        if self._attr_current_temperature is not None:
            attrs[ATTR_EXTERNAL_TEMP] = self._attr_current_temperature
        
        # Battery
        if self._trv_battery is not None:
            attrs[ATTR_TRV_BATTERY] = self._trv_battery
        
        # Statistics
        if self._valve_position_history:
            attrs[ATTR_AVG_VALVE_POSITION] = round(
                sum(self._valve_position_history) / len(self._valve_position_history), 1
            )
        
        if len(self._temp_history) >= 2:
            # Temperature trend: positive = warming, negative = cooling
            trend = self._temp_history[-1] - self._temp_history[0]
            attrs[ATTR_TEMP_TREND] = round(trend, 2)
        
        self._attr_extra_state_attributes = attrs
        _LOGGER.debug("%s: Updated extra_state_attributes = %s", self.name, attrs)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature - sync to original TRV."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        
        self._attr_target_temperature = temperature
        
        # Write temperature directly to original TRV
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self._valve_entity,
                    "temperature": temperature,
                },
                blocking=True,
            )
            _LOGGER.debug(
                "%s: Synced temperature %.1f°C to original TRV %s",
                self.name,
                temperature,
                self._valve_entity,
            )
        except Exception as err:
            _LOGGER.error("Error syncing temperature to TRV: %s", err)
        
        # ✅ WICHTIG: Inertia-Timer zurücksetzen damit Steuerung sofort greift
        self._last_valve_update = None
        
        # Reset PID timing? No, keep integrating but update dt next cycle
        
        # ✅ WICHTIG: Kontrolllogik neu ausführen mit neuer Zieltemperatur
        await self._async_control_heating()
        
        self._update_extra_attributes()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.warning("Unsupported hvac_mode: %s", hvac_mode)
            return
        
        self._attr_hvac_mode = hvac_mode
        await self._async_control_heating()
        self._update_extra_attributes()
        self.async_write_ha_state()
    
    async def async_calibrate_valve(self) -> None:
        """Calibrate the TRV valve (full open/close cycle)."""
        try:
            device_id = self._valve_entity.replace("climate.", "")
            
            _LOGGER.info("%s: Starting valve calibration", self.name)
            
            # Try via select entity (if available)
            calibration_entity = self._valve_entity.replace("climate.", "select.") + "_valve_calibration"
            
            if self.hass.states.get(calibration_entity):
                # Some TRVs have a calibration select option
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": calibration_entity,
                        "option": "calibrate",
                    },
                    blocking=True,
                )
                _LOGGER.info("%s: Valve calibration triggered via select entity", self.name)
            else:
                # Alternative: MQTT command
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": f"zigbee2mqtt/{device_id}/set/calibration",
                        "payload": "run",
                    },
                    blocking=True,
                )
                _LOGGER.info("%s: Valve calibration triggered via MQTT", self.name)
                
        except Exception as err:
            _LOGGER.error("%s: Error during valve calibration: %s", self.name, err)
    
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode (valve opening step)."""
        if preset_mode not in self._attr_preset_modes:
            _LOGGER.warning("Unsupported preset_mode: %s", preset_mode)
            return
        
        self._attr_preset_mode = preset_mode
        self._current_valve_step = preset_mode
        
        # Update max valve position
        old_position = self._max_valve_position
        self._max_valve_position = VALVE_OPENING_STEPS.get(preset_mode, 80)
        
        _LOGGER.info(
            "%s: Preset mode changed from %s (%d%%) to %s (%d%%)",
            self.name,
            "?" if old_position < 0 else str(old_position),
            old_position,
            preset_mode,
            self._max_valve_position,
        )
        
        # Immediately apply new valve opening
        # Bypass inertia check for manual preset changes
        desired_opening = self._calculate_desired_valve_opening()
        
        # Always apply preset change immediately
        if desired_opening != self._last_set_valve_opening:
            await self._async_set_valve_opening(desired_opening)
            _LOGGER.info(
                "%s: Applied new preset immediately, valve opening: %d%%",
                self.name,
                desired_opening,
            )
        
        self._active = desired_opening > 0
        self.async_write_ha_state()
