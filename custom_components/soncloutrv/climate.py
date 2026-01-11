"""Climate platform for SonClouTRV."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import csv
import os
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
    async_track_point_in_time,
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
    CONF_ROOM_ID,
    CONF_KP,
    CONF_KI,
    CONF_KD,
    CONF_KA,
    DEFAULT_HYSTERESIS,
    DEFAULT_CONTROL_MODE,
    DEFAULT_KP,
    DEFAULT_KI,
    DEFAULT_KD,
    DEFAULT_KA,
    CONF_ROOM_LOGGING_ENABLED,
    CONF_ROOM_LOG_FILE,
    DEFAULT_ROOM_LOGGING_ENABLED,
    DEFAULT_ROOM_LOG_FILE,
    CONF_WINDOW_DROP_THRESHOLD,
    CONF_WINDOW_STABLE_BAND,
    CONF_WINDOW_MAX_FREEZE,
    DEFAULT_WINDOW_DROP_THRESHOLD,
    DEFAULT_WINDOW_STABLE_BAND,
    DEFAULT_WINDOW_MAX_FREEZE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
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


class RoomPIDState:
    """Shared PID state for all SonTRV climates in the same room.

    A room is currently defined by the external temperature sensor entity id
    (or the explicit ``room_id`` if configured). This class holds the
    integral term, previous error, last calculation timestamp and the last
    computed PID output (room heating demand) so that multiple valves in the
    same room learn together and expose a common debug state.
    """

    def __init__(self) -> None:
        # Integral of the room error over time (shared across all TRVs in room)
        self.integral_error: float = 0.0
        # Previous error value for derivative calculation
        self.prev_error: float = 0.0
        # Timestamp of last PID calculation
        self.last_calc_time = None
        # Last computed PID output in percent (0-100) representing the
        # *room-level* heating demand. This is used for room debug sensors.
        self.last_output: float = 0.0


SCAN_INTERVAL = timedelta(minutes=5)  # Fußbodenheizung ist träge, 5 Minuten reichen

# Detection thresholds for sudden temperature drops (e.g. window open).
# Instance-level values are configurable via options; these are only
# module-level fallbacks and usually overridden in __init__/async_added.
WINDOW_DROP_THRESHOLD = DEFAULT_WINDOW_DROP_THRESHOLD
WINDOW_STABLE_BAND = DEFAULT_WINDOW_STABLE_BAND
WINDOW_MAX_FREEZE = DEFAULT_WINDOW_MAX_FREEZE
# Time window (in seconds) to look back for sudden drop detection
WINDOW_DROP_WINDOW = 300  # 5 minutes


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
    _attr_target_temperature_step = 0.2
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
        # Support both legacy sensor and new weather entity
        self._outside_temp_sensor = config.get(CONF_WEATHER_ENTITY, config.get(CONF_OUTSIDE_TEMP_SENSOR))

        # Room grouping key: prefer explicit room_id if configured, otherwise
        # fall back to the external temperature sensor (backwards compatible
        # for existing installations without room_id in the config entry).
        self._room_id = config.get(CONF_ROOM_ID)
        self._room_key = self._room_id or self._temp_sensor

        # Room logging configuration (for external ML / analysis).
        # We initialize with defaults here; final values (including options
        # from the config entry) are loaded in async_added_to_hass via
        # _get_config_value so that changes in the options flow take effect
        # without re-creating the config entry.
        self._room_logging_enabled: bool = DEFAULT_ROOM_LOGGING_ENABLED
        room_log_file = DEFAULT_ROOM_LOG_FILE
        # Resolve to absolute path inside HA config directory
        self._room_log_path = hass.config.path(room_log_file)
        
        # Cache derived entity IDs to avoid repeated string manipulation
        self._device_id = self._valve_entity.replace("climate.", "")
        self._sensor_select_entity = self._valve_entity.replace("climate.", "select.") + "_temperature_sensor_select"
        self._temp_input_entity = self._valve_entity.replace("climate.", "number.") + "_external_temperature_input"
        self._valve_opening_entity = self._valve_entity.replace("climate.", "number.") + "_valve_opening_degree"
        # New: explicit entity for valve_closing_degree so we can keep open/close in sync
        self._valve_closing_entity = self._valve_entity.replace("climate.", "number.") + "_valve_closing_degree"
        self._calibration_entity = self._valve_entity.replace("climate.", "select.") + "_valve_calibration"
        self._position_entity = self._valve_entity.replace("climate.", "number.") + "_position"
        
        # MQTT Topics
        self._mqtt_topic_sensor_select = f"zigbee2mqtt/{self._device_id}/set/temperature_sensor_select"
        self._mqtt_topic_ext_temp = f"zigbee2mqtt/{self._device_id}/set/external_temperature_input"
        self._mqtt_topic_valve_open = f"zigbee2mqtt/{self._device_id}/set/valve_opening_degree"
        # New: MQTT topic for valve_closing_degree (inverse of opening)
        self._mqtt_topic_valve_close = f"zigbee2mqtt/{self._device_id}/set/valve_closing_degree"
        self._mqtt_topic_calibration = f"zigbee2mqtt/{self._device_id}/set/calibration"
        self._mqtt_topic_position = f"zigbee2mqtt/{self._device_id}/set/position"

        self._attr_min_temp = config[CONF_MIN_TEMP]
        self._attr_max_temp = config[CONF_MAX_TEMP]
        self._attr_target_temperature = config[CONF_TARGET_TEMP]
        
        # Store reference to config_entry for updates
        self._config_entry = None  # Will be set in async_added_to_hass if available
        
        # Read from config.data (options will be loaded later in async_added_to_hass)
        self._hysteresis = config.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)
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
        
        # Use configured control mode or fall back to global default (PID)
        self._control_mode = config.get(CONF_CONTROL_MODE, DEFAULT_CONTROL_MODE)
        self._time_control_enabled = config.get(CONF_TIME_CONTROL_ENABLED, False)
        self._time_start = config.get(CONF_TIME_START, "06:00")
        self._time_end = config.get(CONF_TIME_END, "22:00")
        
        # PID Parameters
        # Legacy support: use proportional_gain if kp not set
        legacy_p = config.get(CONF_PROPORTIONAL_GAIN, DEFAULT_KP)
        self._kp = config.get(CONF_KP, legacy_p)
        self._ki = config.get(CONF_KI, DEFAULT_KI)
        self._kd = config.get(CONF_KD, DEFAULT_KD)
        self._ka = config.get(CONF_KA, DEFAULT_KA)
        
        # State
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_current_temperature = None
        self._outside_temperature = None  # Store outside temp
        self._valve_position = 0
        self._active = False
        self._is_exercising = False  # Flag to suppress control loop during valve exercise
        self._last_valve_update = None
        self._next_update_time = None # For adaptive polling
        self._update_timer = None # Handle to cancel timer
        self._last_temp_change = None
        self._last_set_valve_opening = -1  # Track last set value
        self._last_synced_temp = None  # For traffic optimization
        
        # PID State
        self._integral_error = 0.0
        self._prev_error = 0.0
        self._last_calc_time = None
        
        # Window / sudden-drop detection state
        self._window_freeze_active = False
        self._window_freeze_start = None
        self._window_drop_threshold = DEFAULT_WINDOW_DROP_THRESHOLD
        self._window_stable_band = DEFAULT_WINDOW_STABLE_BAND
        self._window_max_freeze = DEFAULT_WINDOW_MAX_FREEZE
        
        # Debug values
        self._last_p = 0.0
        self._last_i = 0.0
        self._last_d = 0.0
        self._last_ff = 0.0
        
        # Configurable parameters (can be changed via number entities)
        self._min_valve_update_interval = 600  # 10 minutes default
        
        # Statistics
        self._valve_adjustments_count = 0
        self._valve_position_history = []  # Keep last 10 values
        self._temp_history = []  # Keep last N temperature readings
        self._temp_time_history = []  # Timestamps for temperature readings
        self._trv_internal_temp = None
        self._trv_battery = None
        
        # Initialize extra state attributes
        self._attr_extra_state_attributes = {}
        
        # Listeners
        self._remove_listeners = []

        # Room membership (filled in async_added_to_hass)
        self._is_room_leader = False

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

        # Register in room registry (grouped by external temp sensor).
        # This does not change behaviour yet, it only tracks which
        # SonTRV climates share the same room.
        rooms = self.hass.data.setdefault(DOMAIN, {}).setdefault("rooms", {})
        room_entities = rooms.setdefault(self._room_key, [])
        if self not in room_entities:
            room_entities.append(self)
        # First entity in list is the temporary "leader" which can be
        # used later for coordinated room-level PID control.
        self._is_room_leader = room_entities[0] is self
        
        # Get reference to config_entry from registry
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self._entry_id:
                self._config_entry = entry
                # Re-read values from options now that we have config_entry
                self._hysteresis = self._get_config_value("hysteresis", self._config, DEFAULT_HYSTERESIS)
                self._cold_tolerance = self._get_config_value("cold_tolerance", self._config, 0.3)
                self._hot_tolerance = self._get_config_value("hot_tolerance", self._config, 0.3)
                self._min_cycle_duration = self._get_config_value("min_cycle_duration", self._config, 300)
                
                # Load PID values
                legacy_p = self._get_config_value("proportional_gain", self._config, DEFAULT_KP)
                self._kp = self._get_config_value(CONF_KP, self._config, legacy_p)
                self._ki = self._get_config_value(CONF_KI, self._config, DEFAULT_KI)
                self._kd = self._get_config_value(CONF_KD, self._config, DEFAULT_KD)
                self._ka = self._get_config_value(CONF_KA, self._config, DEFAULT_KA)

                # Migration: Wenn noch die alten, sehr aggressiven Standardwerte
                # (Kp=20, Ki=0.01, Kd=500, Ka=0) aktiv sind, stelle einmalig
                # auf die neuen, einfacheren P-Standardwerte um.
                if (
                    self._kp == 20.0
                    and self._ki == 0.01
                    and self._kd == 500.0
                    and self._ka == 0.0
                ):
                    self._kp = 3.0
                    self._ki = 0.0
                    self._kd = 0.0
                    self._ka = 0.0
                    _LOGGER.info(
                        "%s: Migrated legacy PID gains to P-only defaults (Kp=3.0, Ki=0, Kd=0, Ka=0)",
                        self.name,
                    )
                # Neue Migration: Wenn der Regler bereits auf den einfachen P-Defaults
                # (Kp=3, Ki=0, Kd=0, Ka=0) steht, aktiviere einen kleinen I-Anteil
                # für höhere Genauigkeit, ohne bestehende manuelle Tunings zu überschreiben.
                elif (
                    self._kp == 3.0
                    and self._ki == 0.0
                    and self._kd == 0.0
                    and self._ka == 0.0
                ):
                    self._ki = DEFAULT_KI
                    _LOGGER.info(
                        "%s: Enabled small integral gain Ki=%.4f for more precise control",
                        self.name,
                        self._ki,
                    )

                # Window detection configuration
                self._window_drop_threshold = self._get_config_value(
                    CONF_WINDOW_DROP_THRESHOLD,
                    self._config,
                    DEFAULT_WINDOW_DROP_THRESHOLD,
                )
                self._window_stable_band = self._get_config_value(
                    CONF_WINDOW_STABLE_BAND,
                    self._config,
                    DEFAULT_WINDOW_STABLE_BAND,
                )
                self._window_max_freeze = self._get_config_value(
                    CONF_WINDOW_MAX_FREEZE,
                    self._config,
                    DEFAULT_WINDOW_MAX_FREEZE,
                )

                # Room logging configuration (may come from options)
                self._room_logging_enabled = self._get_config_value(
                    CONF_ROOM_LOGGING_ENABLED,
                    self._config,
                    DEFAULT_ROOM_LOGGING_ENABLED,
                )
                room_log_file = self._get_config_value(
                    CONF_ROOM_LOG_FILE,
                    self._config,
                    DEFAULT_ROOM_LOG_FILE,
                )
                self._room_log_path = self.hass.config.path(room_log_file)
                
                # Update outside sensor from config if changed in options (re-merge)
                # Check for weather entity first, then legacy sensor
                self._outside_temp_sensor = self._get_config_value(CONF_WEATHER_ENTITY, self._config, 
                                            self._get_config_value(CONF_OUTSIDE_TEMP_SENSOR, self._config, None))
                
                _LOGGER.debug("%s: Loaded config values - hysteresis=%.1f, Kp=%.1f, Ki=%.3f, Kd=%.1f, Ka=%.1f", 
                            self.name, self._hysteresis, self._kp, self._ki, self._kd, self._ka)
                break
        
        # Auto-discover weather entity if not configured
        if not self._outside_temp_sensor:
            weather_entities = self.hass.states.async_entity_ids("weather")
            if weather_entities:
                # Pick the first one (usually weather.forecast_home or similar)
                self._outside_temp_sensor = weather_entities[0]
                _LOGGER.info("%s: Auto-discovered weather entity for Feed-Forward: %s", self.name, self._outside_temp_sensor)
        
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
        
        # Track outside temperature sensor if configured
        if self._outside_temp_sensor:
            self._remove_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [self._outside_temp_sensor],
                    self._async_outside_sensor_changed,
                )
            )
            # Initial read
            outside_state = self.hass.states.get(self._outside_temp_sensor)
            if outside_state and outside_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                try:
                    if outside_state.domain == "weather":
                        temp = outside_state.attributes.get("temperature")
                        if temp is not None:
                            self._outside_temperature = float(temp)
                    else:
                        self._outside_temperature = float(outside_state.state)
                except ValueError:
                    pass

        # Track valve entity
        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass,
                [self._valve_entity],
                self._async_valve_changed,
            )
        )
        
        # Start Adaptive Polling Loop
        await self._async_schedule_next_update()
        
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
        if self._update_timer:
            self._update_timer()
            self._update_timer = None

        # Unregister from room registry
        domain_data = self.hass.data.get(DOMAIN)
        if domain_data is not None:
            rooms = domain_data.get("rooms")
            if rooms is not None:
                room_entities = rooms.get(self._room_key)
                if room_entities and self in room_entities:
                    room_entities.remove(self)
                    # If room is now empty, remove it from registry
                    if not room_entities:
                        rooms.pop(self._room_key, None)

        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()

    @callback
    async def _async_outside_sensor_changed(self, event) -> None:
        """Handle outside temperature sensor changes."""
        new_state = event.data.get("new_state")
        if new_state is not None and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                # Handle weather entities vs sensors
                if new_state.domain == "weather":
                    # Try standard attributes first
                    temp = new_state.attributes.get("temperature")
                    
                    # Fallback: Try 'current_temperature' (some integrations)
                    if temp is None:
                        temp = new_state.attributes.get("current_temperature")
                        
                    if temp is not None:
                        self._outside_temperature = float(temp)
                        _LOGGER.debug("%s: Updated outside temp from weather entity %s: %.1f°C", 
                                    self.name, new_state.entity_id, self._outside_temperature)
                    else:
                        _LOGGER.warning("%s: Weather entity %s has no 'temperature' attribute", 
                                      self.name, new_state.entity_id)
                else:
                    # Legacy sensor support
                    self._outside_temperature = float(new_state.state)
                    _LOGGER.debug("%s: Updated outside temp from sensor %s: %.1f°C", 
                                self.name, new_state.entity_id, self._outside_temperature)
                    
                # Note: We don't trigger immediate control loop for outside temp changes
                # as feed-forward is slow-reacting anyway.
            except ValueError:
                _LOGGER.warning("%s: Could not parse outside temperature from %s", self.name, new_state.entity_id)

    @callback
    async def _async_sensor_changed(self, event) -> None:
        """Handle temperature sensor changes."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        # Update internal state
        await self._async_update_temp()
        
        # Optimization: Noise Filter + Window detection
        # Only trigger immediate control loop if temperature changed significantly (> 0.1°C)
        # Small fluctuations are handled in the next regular interval to save battery/motor.
        should_trigger_immediate = False
        sudden_drop_detected = False
        
        if old_state and new_state and old_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                old_temp = float(old_state.state)
                new_temp = float(new_state.state)
                delta = new_temp - old_temp
                if abs(delta) >= 0.1:
                    should_trigger_immediate = True
                
                # 1) Single-step Erkennung: sehr plötzlicher Sprung
                if delta <= -self._window_drop_threshold:
                    sudden_drop_detected = True
                
                # 2) Zeitfenster-Erkennung: Wenn die Temperatur innerhalb der
                #    letzten WINDOW_DROP_WINDOW Sekunden deutlich gefallen ist
                #    (bezogen auf das Maximum in diesem Fenster), werten wir
                #    das ebenfalls als Fenster-/Tür-Öffnung.
                if self._temp_history and self._temp_time_history:
                    now = dt_util.now()
                    window_start = now - timedelta(seconds=WINDOW_DROP_WINDOW)
                    recent_values: list[float] = []
                    for value, ts in zip(self._temp_history, self._temp_time_history):
                        if ts >= window_start:
                            recent_values.append(value)
                    if recent_values:
                        recent_max = max(recent_values)
                        if recent_max - new_temp >= self._window_drop_threshold:
                            sudden_drop_detected = True
            except ValueError:
                should_trigger_immediate = True # Fallback on error
        else:
            should_trigger_immediate = True # First update or unavailable state
            
        if sudden_drop_detected:
            self._window_freeze_active = True
            self._window_freeze_start = dt_util.now()
            _LOGGER.info(
                "%s: Sudden temperature drop detected (possible window open) - freezing valve control",
                self.name,
            )

            # Sofort Ventil schließen, damit während des vermuteten
            # Fenster-Events definitiv nicht weiter geheizt wird.
            if self._last_set_valve_opening != 0:
                await self._async_set_valve_opening(0)
            self._active = False
            self._update_extra_attributes()
            self.async_write_ha_state()
        
        # Immediately sync temperature calibration when sensor changes (keep display updated)
        # Only if change is significant to reduce traffic
        if should_trigger_immediate:
            await self._async_sync_temperature_calibration()
        
            # Trigger immediate update (cancel sleep)
            if self._update_timer:
                self._update_timer() # Cancel existing timer
                self._update_timer = None
                
            await self._async_control_heating()
        else:
            # Just update attributes without triggering control logic
            self.async_write_ha_state()
            
        self._update_extra_attributes()

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
                
                # Update temperature history for trend and window detection
                now = dt_util.now()
                self._temp_history.append(new_temp)
                self._temp_time_history.append(now)
                # Keep a reasonable history length (e.g. last 20 readings)
                if len(self._temp_history) > 20:
                    self._temp_history.pop(0)
                    self._temp_time_history.pop(0)
                    
            except (ValueError, TypeError):
                _LOGGER.warning("Unable to update temperature from %s", self._temp_sensor)

    async def _async_schedule_next_update(self) -> None:
        """Schedule the next update based on stability (Adaptive Polling)."""
        if self._update_timer:
            self._update_timer()
            self._update_timer = None
            
        # Determine Interval
        # Default: 10 minutes (600s)
        # Stable: 30 minutes (1800s)
        
        interval = self._min_valve_update_interval
        
        # Check for stability to relax interval
        if (self._attr_current_temperature and self._attr_target_temperature and
            abs(self._attr_target_temperature - self._attr_current_temperature) < 0.2 and
            not self._is_exercising):
             # System is stable, relax polling
             # Only if we are in PID mode (steady state)
             if self._control_mode == CONTROL_MODE_PID:
                 interval = 1800 # 30 mins
                 _LOGGER.debug("%s: System stable, relaxing update interval to %ds", self.name, interval)
        
        next_update = dt_util.now() + timedelta(seconds=interval)
        self._next_update_time = next_update
        
        self._update_timer = async_track_point_in_time(
            self.hass,
            self._async_control_heating,
            next_update,
        )

    async def _async_control_heating(self, now=None) -> None:
        """Control heating with hysteresis and inertia for underfloor heating."""
        # Block control if exercising
        if self._is_exercising:
            _LOGGER.debug("%s: Skipping control loop - Valve exercise in progress", self.name)
            # Schedule next check
            await self._async_schedule_next_update()
            return

        # If we previously detected a sudden temperature drop (window open),
        # keep the current valve state until the temperature stabilizes again
        # or a maximum freeze duration has passed.
        if self._window_freeze_active:
            if self._is_window_freeze_over():
                _LOGGER.info("%s: Temperature stabilized after suspected window event - resuming PID control", self.name)
                self._window_freeze_active = False
            else:
                _LOGGER.debug(
                    "%s: Window event active, keeping valve at %d%%",
                    self.name,
                    self._last_set_valve_opening,
                )
                await self._async_schedule_next_update()
                return

        # Always update temperature sync (external sensor)
        await self._async_sync_temperature_calibration()
        
        # Sync HVAC mode first
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_set_trv_off()
            self._active = False
            self.async_write_ha_state()
            # Still schedule next update to check for mode changes
            await self._async_schedule_next_update()
            return
        
        # Check if we should update valve opening (inertia)
        # Note: In adaptive polling, we usually only run when scheduled or triggered.
        # But if triggered by sensor change, we still respect min_valve_update_interval
        # for the actual VALVE WRITE, but we re-calc PID.
        
        # Calculate desired valve opening based on temperature difference
        desired_opening = self._calculate_desired_valve_opening()
        
        # Only update if actually different OR if enough time passed
        should_write = False
        
        if self._last_valve_update is None:
            should_write = True
        else:
            time_since_last = (dt_util.now() - self._last_valve_update).total_seconds()
            if time_since_last >= self._min_valve_update_interval:
                # Time criterion met, check if value changed
                if desired_opening != self._last_set_valve_opening:
                    should_write = True
                else:
                    _LOGGER.debug("%s: Valve opening unchanged at %d%%, skipping write", self.name, desired_opening)
            else:
                _LOGGER.debug("%s: Min update interval not reached (%ds < %ds), skipping write", 
                              self.name, time_since_last, self._min_valve_update_interval)

        if should_write:
            await self._async_set_valve_opening(desired_opening)
        
        # Sync target temperature to TRV
        if self._attr_target_temperature is not None:
            await self._async_sync_target_temperature()
        
        self._active = desired_opening > 0
        self._update_extra_attributes()
        self.async_write_ha_state()
        
        # Schedule next run
        await self._async_schedule_next_update()
    
    def _is_window_freeze_over(self) -> bool:
        """Return True if the window/sudden-drop freeze should end.

        We consider the situation "stable" again if:
        - The freeze has been active longer than WINDOW_MAX_FREEZE seconds, or
        - The last few temperature readings are within WINDOW_STABLE_BAND.
        """
        if not self._window_freeze_active:
            return True

        now = dt_util.now()
        if self._window_freeze_start is not None:
            if (now - self._window_freeze_start).total_seconds() > self._window_max_freeze:
                return True

        # Check recent temperature history for stability
        if len(self._temp_history) >= 3:
            recent = self._temp_history[-3:]
            if max(recent) - min(recent) <= self._window_stable_band:
                return True

        return False
    
    async def _async_sync_temperature_calibration(self) -> None:
        """Sync external temperature sensor with TRV via external temperature input."""
        if self._attr_current_temperature is None:
            _LOGGER.debug("%s: Cannot sync temperature - external temperature is None", self.name)
            return
        
        # Optimization: Only sync if temp changed significantly or enough time passed (e.g. 10 mins)
        # to reduce Zigbee traffic
        current_temp = round(self._attr_current_temperature, 1)
        now = dt_util.now()
        
        should_sync = False
        if self._last_synced_temp is None:
            should_sync = True
        elif abs(current_temp - self._last_synced_temp) >= 0.1:
            should_sync = True
        # Force sync every 30 mins just in case
        # Note: We rely on SCAN_INTERVAL (5 mins) for the loop, so this is just a counter-check
        # Actually, let's just sync on change or every 30 mins.
        # But we don't track last sync time here easily without adding another var.
        # Let's rely on change.
        
        if not should_sync:
             # _LOGGER.debug("%s: Skipping temp sync - change too small", self.name)
             return

        try:
            # Read TRV state for monitoring (existing logic kept)
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
            
            # Step 1: Set temperature_sensor_select to "external"
            if self.hass.states.get(self._sensor_select_entity):
                # Via entity
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": self._sensor_select_entity,
                        "option": "external",
                    },
                    blocking=False,
                )
            else:
                # Via MQTT
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": self._mqtt_topic_sensor_select,
                        "payload": "external",
                    },
                    blocking=False,
                )
            
            # Step 2: Write external temperature value to external_temperature_input
            if self.hass.states.get(self._temp_input_entity):
                # Via entity
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": self._temp_input_entity,
                        "value": current_temp,
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Set external temperature to %.1f°C via %s",
                    self.name,
                    current_temp,
                    self._temp_input_entity,
                )
            else:
                # Via MQTT
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": self._mqtt_topic_ext_temp,
                        "payload": str(current_temp),
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Set external temperature to %.1f°C via MQTT",
                    self.name,
                    current_temp,
                )
            
            self._last_synced_temp = current_temp
                
        except Exception as err:
            _LOGGER.error("%s: Error syncing external temperature: %s", self.name, err)

    def _should_update_valve_opening(self) -> bool:
        """Check if we should update valve opening (apply inertia)."""
        if self._last_valve_update is None:
            return True
        
        time_since_last_update = (dt_util.now() - self._last_valve_update).total_seconds()
        return time_since_last_update >= self._min_valve_update_interval
    
    def _get_room_pid_state(self) -> RoomPIDState:
        """Return (and create if needed) the shared RoomPIDState for this room."""
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        room_states = domain_data.setdefault("room_states", {})
        state = room_states.get(self._room_key)
        if state is None:
            state = RoomPIDState()
            room_states[self._room_key] = state
        return state

    def _calculate_desired_valve_opening(self) -> int:
        """Calculate desired valve opening based on temperature difference (PID).

        The PID state (integral, previous error, last_calc_time) is shared per
        room (i.e. per external temperature sensor). This means multiple SonTRV
        climates in the same room learn together instead of independently.
        """
        if self._attr_current_temperature is None or self._attr_target_temperature is None:
            return 0
        
        # Check if valve is disabled
        if self._max_valve_position == 0:
            return 0
            
        current_temp = self._attr_current_temperature
        target_temp = self._attr_target_temperature
        
        # Error = Target - Current (Positive when cold/needs heat)
        error = target_temp - current_temp

        # Only "learn" (update integral etc.) when heating is actually enabled.
        # Otherwise summer/off-periods would distort the shared room PID state.
        heating_on = self._attr_hvac_mode == HVACMode.HEAT
        
        # Get shared room PID state
        state = self._get_room_pid_state()
        
        # PID Time Calculation
        now = dt_util.now()
        if state.last_calc_time is None:
            state.last_calc_time = now
            dt = 0.0
        else:
            dt = (now - state.last_calc_time).total_seconds()
            state.last_calc_time = now
            
        # 1. Proportional Term
        # Fehlerabhängige Verstärkung: in der Nähe des Sollwerts bleibt Kp wie konfiguriert,
        # bei größeren Abweichungen nach unten (Raum zu kalt) wird Kp schrittweise erhöht,
        # damit der Regler kräftiger heizt. Nach oben (Raum zu warm) bleiben wir konservativ,
        # um Überschwingen zu vermeiden.
        abs_error = abs(error)
        gain_scale = 1.0
        if abs_error > 1.8:
            gain_scale = 2.0
        elif abs_error > 1.2:
            gain_scale = 1.7
        elif abs_error > 0.7:
            gain_scale = 1.4
        elif abs_error > 0.3:
            gain_scale = 1.2

        effective_kp = self._kp * gain_scale

        # Wenn der Raum schon zu warm ist (error < 0), leicht reduzierte Verstärkung,
        # damit wir nicht unnötig aggressiv nach unten regeln.
        if error < 0:
            effective_kp *= 0.8

        p_term = effective_kp * error
        
        # 2. Integral Term (Learning)
        # Only integrate if we have a valid time delta and error is within reasonable bounds
        # (Prevent windup if sensor was offline for a long time). Additionally,
        # only learn when heating is actually enabled (HVACMode.HEAT).
        i_term = 0.0
        if dt > 0 and dt < 3600 and heating_on and self._ki > 0:  # Ignore if gap > 1 hour, heating off oder Ki=0
            abs_err = abs(error)
            # Bereich für I-Anteil:
            # - |error| < hysteresis: Integral langsam abbauen (kein Nachziehen mehr nötig)
            # - hysteresis <= |error| <= 1.0 K: normal integrieren (Feinkorrektur)
            # - |error| > 1.0 K: Aufheizphase, hier übernimmt hauptsächlich P, kein weiteres Aufbauen
            if abs_err < self._hysteresis:
                # Langsames Zurückfahren des Integrals in Richtung 0
                state.integral_error *= 0.9
            elif abs_err <= 1.0:
                state.integral_error += error * dt

            # Anti-Windup: max. +/-100% Beitrag durch I-Anteil
            max_integral = 100.0 / self._ki
            state.integral_error = max(-max_integral, min(max_integral, state.integral_error))

            i_term = self._ki * state.integral_error
        else:
            # First run or restart, just use existing integral
            i_term = self._ki * state.integral_error
            
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
            # d_error = (error - state.prev_error) / dt
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
                 d_error = (error - state.prev_error) / dt
                 d_term = self._kd * d_error
                 
                 # Suppress huge spikes (Derivative Kick protection)
                 # If D term is huge (> 100%), it's likely a setpoint change.
                 if abs(d_term) > 100:
                     _LOGGER.debug("%s: D-Term spike detected (%.1f), suppressing", self.name, d_term)
                     d_term = 0.0

        # Wenn der Fehler das Vorzeichen wechselt (z.B. von zu kalt nach zu warm),
        # Integral zurücksetzen, damit kein Nachschwingen durch aufgelaufenen I-Anteil entsteht.
        if error * state.prev_error < 0:
            state.integral_error = 0.0
        state.prev_error = error
        
        # 4. Feed-Forward Term (Weather Compensation)
        # FF = (Target - Outside) * Ka
        # Only if Ka > 0 and outside temp is available
        ff_term = 0.0
        if self._ka > 0 and self._outside_temperature is not None:
            # Delta between desired room temp and outside
            # The colder outside, the higher this delta -> More heating
            outside_delta = target_temp - self._outside_temperature
            
            # Simple linear model: Ka % per degree difference
            # E.g. Ka = 0.5, Target=21, Outside=0 -> Delta=21 -> FF = 10.5%
            # If Outside=15 -> Delta=6 -> FF = 3%
            if outside_delta > 0:
                ff_term = self._ka * outside_delta
                
        # Store terms for debugging (entity-local mirrors of shared room state)
        self._integral_error = state.integral_error
        self._prev_error = state.prev_error
        self._last_calc_time = state.last_calc_time
        self._last_p = p_term
        self._last_i = i_term
        self._last_d = d_term
        self._last_ff = ff_term
        
        # Total Output (Percent)
        raw_output = p_term + i_term + d_term + ff_term
        
        # Clamp to 0-100%
        desired_percent = max(0.0, min(100.0, raw_output))
        # Store the *room-level* demand in the shared state so that dedicated
        # room debug sensors can expose this without re-implementing PID logic.
        state.last_output = desired_percent
        
        # Scale to max_valve_position (e.g. if max is 80%, we map 0-100% PID to 0-80% Valve)
        # OR: clamp strictly to max_valve_position?
        # Usually: PID output 0-100% corresponds to valve 0-Max
        final_desired = int((desired_percent / 100.0) * self._max_valve_position)

        # Anwenden der Hysterese um den Sollwert:
        # - Wenn der Raum deutlich zu warm ist (error < -hysteresis), Ventil sicher schließen.
        # - Wenn der Raum deutlich zu kalt ist (error > hysteresis), mindestens minimal öffnen,
        #   auch wenn der P-Regler wegen Rundung sonst 0 liefern würde.
        if error < -self._hysteresis:
            final_desired = 0
        elif error > self._hysteresis and final_desired == 0 and self._max_valve_position > 0:
            final_desired = 1  # minimale Öffnungseinheit

        # Optional: append a CSV log row for this room for later ML analysis.
        # We only log when heating is enabled so the dataset reflects periods
        # where the TRVs actually work against the building inertia.
        if self._room_logging_enabled and heating_on:
            # Use the same timestamp "now" used for dt calculation
            self.hass.async_add_executor_job(
                self._append_room_log_row,
                now,
                error,
                desired_percent,
                final_desired,
                current_temp,
                target_temp,
                self._outside_temperature,
            )
        
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

    def _append_room_log_row(
        self,
        timestamp,
        error: float,
        room_demand: float,
        valve_opening: int,
        current_temp: float,
        target_temp: float,
        outside_temp: float | None,
    ) -> None:
        """Append a single CSV row with room / valve state for offline analysis.

        This runs in an executor thread to avoid blocking the event loop with
        file I/O. The file is created on first use and a header row is written
        once.
        """
        try:
            os.makedirs(os.path.dirname(self._room_log_path), exist_ok=True)
        except Exception:
            # If directory creation fails (e.g. empty dirname), ignore and try file write
            pass

        header = [
            "timestamp",
            "room_key",
            "climate_entity",
            "room_temp",
            "target_temp",
            "error",
            "room_demand_percent",
            "valve_opening_percent",
            "max_valve_position",
            "outside_temp",
            "outside_sensor",
            "hvac_mode",
            "hvac_action",
        ]

        row = [
            timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
            self._room_key,
            getattr(self, "entity_id", ""),
            current_temp,
            target_temp,
            error,
            round(room_demand, 3),
            valve_opening,
            self._max_valve_position,
            outside_temp,
            self._outside_temp_sensor,
            getattr(self, "_attr_hvac_mode", None),
            getattr(self, "_attr_hvac_action", None),
        ]

        try:
            file_exists = os.path.isfile(self._room_log_path)
            with open(self._room_log_path, "a", newline="") as csvfile:
                writer = csv.writer(csvfile)
                if not file_exists:
                    writer.writerow(header)
                writer.writerow(row)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.error("%s: Failed to append room log row: %s", self.name, err)
    
    async def _async_set_valve_opening(self, valve_opening: int) -> None:
        """Set valve opening and closing degree on the TRV.

        The TRV expects two complementary values:
        - ``valve_opening_degree``  -> how far the valve is opened in percent
        - ``valve_closing_degree``  -> how far the valve is closed in percent

        By definition: closing = 100 - opening.
        """
        try:
            # Clamp opening value defensively
            valve_opening = max(0, min(100, int(valve_opening)))
            valve_closing = 100 - valve_opening

            # Try via number entities first (preferred: keeps HA + Z2M in sync)
            if self.hass.states.get(self._valve_opening_entity):
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": self._valve_opening_entity,
                        "value": valve_opening,
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve_opening_degree to %d%% via %s",
                    self.name,
                    valve_opening,
                    self._valve_opening_entity,
                )
            else:
                # Fallback: MQTT publish for opening
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": self._mqtt_topic_valve_open,
                        "payload": str(valve_opening),
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve_opening_degree to %d%% via MQTT",
                    self.name,
                    valve_opening,
                )

            # Always try to keep valve_closing_degree in sync as 100 - opening
            if self.hass.states.get(self._valve_closing_entity):
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": self._valve_closing_entity,
                        "value": valve_closing,
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve_closing_degree to %d%% via %s",
                    self.name,
                    valve_closing,
                    self._valve_closing_entity,
                )
            else:
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": self._mqtt_topic_valve_close,
                        "payload": str(valve_closing),
                    },
                    blocking=True,
                )
                _LOGGER.info(
                    "%s: Set valve_closing_degree to %d%% via MQTT",
                    self.name,
                    valve_closing,
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
            _LOGGER.error("%s: Error setting valve opening/closing degree: %s", self.name, err)
    
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
            if self.hass.states.get(self._position_entity):
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": self._position_entity,
                        "value": self._max_valve_position,
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Limited valve position to %d%% via %s",
                    self.name,
                    self._max_valve_position,
                    self._position_entity,
                )
            else:
                # Alternative: Use MQTT publish to set position directly
                await self.hass.services.async_call(
                    "mqtt",
                    "publish",
                    {
                        "topic": self._mqtt_topic_position,
                        "payload": str(self._max_valve_position),
                    },
                    blocking=True,
                )
                _LOGGER.debug(
                    "%s: Limited valve position to %d%% via MQTT topic %s",
                    self.name,
                    self._max_valve_position,
                    self._mqtt_topic_position,
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
            "pid_ff": round(self._last_ff, 1),
            "outside_temperature": self._outside_temperature,
            "next_update": self._next_update_time.isoformat() if self._next_update_time else None,
            "is_exercising": self._is_exercising,
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

        # Window / sudden drop info
        attrs["window_open"] = self._window_freeze_active
        if self._window_freeze_start is not None:
            attrs["window_freeze_since"] = self._window_freeze_start.isoformat()
        else:
            attrs["window_freeze_since"] = None
        attrs["window_drop_threshold"] = self._window_drop_threshold
        attrs["window_stable_band"] = self._window_stable_band
        attrs["window_max_freeze"] = self._window_max_freeze
        
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
        
        # Optimization: Integrator Preloading (Smart Start)
        # If we raise target temp significantly (> 1°C) and I-term is low/zero,
        # preload it to give a head start. Assume we need at least 20% valve for heating.
        if self._attr_current_temperature:
            diff = temperature - self._attr_current_temperature
            if diff > 1.0 and self._control_mode == CONTROL_MODE_PID:
                # Calculate required I-sum for 20% output: 20 = Ki * I_sum -> I_sum = 20 / Ki
                # Only preload if current integral is smaller than this
                if self._ki > 0:
                    preload_target = 20.0 / self._ki
                    if self._integral_error < preload_target:
                        # Don't jump fully, but boost significantly towards it
                        self._integral_error = preload_target
                        _LOGGER.info("%s: Smart Start - Preloaded PID Integrator to %.1f (Boost)", self.name, self._integral_error)
        
        # ✅ WICHTIG: Kontrolllogik neu ausführen mit neuer Zieltemperatur
        # Trigger immediate update via timer cancel
        if self._update_timer:
            self._update_timer()
            self._update_timer = None
            
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
            _LOGGER.info("%s: Starting valve calibration", self.name)
            
            # Try via select entity (if available)
            if self.hass.states.get(self._calibration_entity):
                # Some TRVs have a calibration select option
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": self._calibration_entity,
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
                        "topic": self._mqtt_topic_calibration,
                        "payload": "run",
                    },
                    blocking=True,
                )
                _LOGGER.info("%s: Valve calibration triggered via MQTT", self.name)
                
        except Exception as err:
            _LOGGER.error("%s: Error during valve calibration: %s", self.name, err)

    async def async_trigger_valve_exercise(self) -> None:
        """Run the anti-calcification exercise (5 min open, 5 min closed)."""
        _LOGGER.info("%s: Starting anti-calcification valve exercise", self.name)
        
        if self._is_exercising:
            _LOGGER.warning("%s: Valve exercise already in progress", self.name)
            return
            
        self._is_exercising = True
        
        try:
            # Save current valve position and preset mode
            original_position = self._valve_position
            original_preset = self._attr_preset_mode
            
            _LOGGER.info("%s: Saved current state - Position: %d%%, Preset: %s", 
                        self.name, original_position, original_preset)
            
            # Step 1: Fully open (100%) for 5 minutes
            await self._async_set_valve_opening(100)
            _LOGGER.info("%s: Valve fully opened (100%%), scheduled close in 5 minutes", self.name)
            
            # Schedule step 2 after 5 minutes (non-blocking)
            from homeassistant.helpers.event import async_call_later
            async_call_later(
                self.hass,
                300,  # 5 minutes
                self._async_exercise_step_2,
                (original_position, original_preset),
            )
            
        except Exception as err:
            _LOGGER.error("%s: Error during valve exercise: %s", self.name, err)
            self._is_exercising = False

    async def _async_exercise_step_2(self, args) -> None:
        """Step 2: Fully close valve for 5 minutes."""
        original_position, original_preset = args
        try:
            # Step 2: Fully close (0%) for 5 minutes
            await self._async_set_valve_opening(0)
            _LOGGER.info("%s: Valve fully closed (0%%), scheduled restore in 5 minutes", self.name)
            
            # Schedule step 3 after 5 minutes (non-blocking)
            from homeassistant.helpers.event import async_call_later
            async_call_later(
                self.hass,
                300,  # 5 minutes
                self._async_exercise_step_3,
                (original_position, original_preset),
            )
            
        except Exception as err:
            _LOGGER.error("%s: Error during valve exercise step 2: %s", self.name, err)
            self._is_exercising = False

    async def _async_exercise_step_3(self, args) -> None:
        """Step 3: Restore original position and resume normal control."""
        original_position, original_preset = args
        try:
            # Step 3: Restore original position and trigger normal control
            await self._async_set_valve_opening(original_position)
            self._attr_preset_mode = original_preset
            _LOGGER.info("%s: Valve exercise complete - restored to %d%% (Preset: %s)", 
                       self.name, original_position, original_preset)
            
            # Reset exercising flag
            self._is_exercising = False
            
            # Trigger normal heating control to resume
            await self._async_schedule_next_update()
            
        except Exception as err:
            _LOGGER.error("%s: Error during valve exercise step 3: %s", self.name, err)
            self._is_exercising = False
    
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
