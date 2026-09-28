"""Climate platform for SonTRV (SONOFF TRVZB on single-room floor heating).

Version 2 architecture
----------------------
* The heavy lifting (trend, prediction, PI, learning) lives in
  ``controller.py`` and is shared by all circuits of a room and heating type.
* This entity is the actuator/IO layer: it reads the room sensor, keeps the
  TRV in a defined state (mode, external temperature, valve opening and the
  complementary closing degree), handles windows, failures and the valve
  exercise, and exposes everything as attributes.

Robustness rules applied throughout:
* never block the event loop / platform setup (no sleeps during setup),
* never let a failed service call break the control loop,
* write to the TRV only when something actually changes, but re-send
  periodically and whenever the TRV reports something different,
* if the room sensor is gone, fall back to the TRV's own sensor (offset
  corrected) and finally to the learned steady-state demand.
"""
from __future__ import annotations

import asyncio
import csv
from datetime import timedelta
import logging
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
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import runtime
from .const import (
    ATTR_AVG_VALVE_POSITION,
    ATTR_CONTROL_MODE,
    ATTR_EXTERNAL_TEMP,
    ATTR_LAST_VALVE_UPDATE,
    ATTR_PID_D,
    ATTR_PID_I,
    ATTR_PID_INTEGRAL,
    ATTR_PID_P,
    ATTR_TEMP_TREND,
    ATTR_TEMPERATURE_DIFFERENCE,
    ATTR_TIME_CONTROL,
    ATTR_TRV_BATTERY,
    ATTR_TRV_INTERNAL_TEMP,
    ATTR_VALVE_ADJUSTMENTS,
    ATTR_VALVE_POSITION,
    CONF_ADAPTIVE_FF,
    CONF_CONTROL_MODE,
    CONF_HEATING_TYPE,
    CONF_HYSTERESIS,
    CONF_KA,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_MAX_TEMP,
    CONF_MAX_VALVE_POSITION,
    CONF_MIN_TEMP,
    CONF_MIN_VALVE_UPDATE_INTERVAL,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_PREDICTION_HORIZON,
    CONF_PROPORTIONAL_GAIN,
    CONF_PWM_PERIOD,
    CONF_ROOM_ID,
    CONF_ROOM_LOG_FILE,
    CONF_ROOM_LOGGING_ENABLED,
    CONF_ROOM_POWER_SHARE,
    CONF_SENSOR_TIMEOUT,
    CONF_TARGET_TEMP,
    CONF_TEMP_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_VALVE_MIN_OPENING,
    CONF_VALVE_OPENING_STEP,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_DROP_THRESHOLD,
    CONF_WINDOW_MAX_FREEZE,
    CONF_WINDOW_SENSOR_SCOPE,
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_STABLE_BAND,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PID,
    CONTROL_MODE_PROPORTIONAL,
    CONTROL_MODE_PWM,
    DEFAULT_ADAPTIVE_FF,
    DEFAULT_CONTROL_MODE,
    DEFAULT_HYSTERESIS,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_ROOM_LOG_FILE,
    DEFAULT_ROOM_LOGGING_ENABLED,
    DEFAULT_ROOM_POWER_SHARE,
    DEFAULT_SENSOR_TIMEOUT,
    DEFAULT_TARGET_TEMP,
    DEFAULT_VALVE_MIN_OPENING,
    DEFAULT_WINDOW_DROP_THRESHOLD,
    DEFAULT_WINDOW_MAX_FREEZE,
    DEFAULT_WINDOW_STABLE_BAND,
    DOMAIN,
    EXT_TEMP_REFRESH_INTERVAL,
    EXT_TEMP_REFRESH_INTERVAL_BOSCH,
    TRV_DRIVER_BOSCH,
    TRV_DRIVER_SONOFF,
    HEATING_TYPE_FLOOR,
    HEATING_TYPE_RADIATOR,
    VALVE_OPENING_STEPS,
    VALVE_REFRESH_INTERVAL,
    VALVE_WRITE_DEADBAND,
    VERSION,
    WINDOW_SCOPE_ALL,
    WINDOW_SCOPE_LOCAL,
)
from .controller import (
    ControllerResult,
    ControllerSettings,
    RoomController,
    demand_to_opening,
    get_profile,
    pwm_on_seconds,
)

_LOGGER = logging.getLogger(__name__)

CONTROL_MODES = [
    CONTROL_MODE_PID,
    CONTROL_MODE_PWM,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PROPORTIONAL,
]
HEATING_TYPES = [HEATING_TYPE_FLOOR, HEATING_TYPE_RADIATOR]

# Window detection by temperature drop
WINDOW_DROP_WINDOW = 300  # seconds to look back
# After a window closed: limit the opening for this long ...
POST_WINDOW_SOFT_DURATION = 3600
# ... to the opening before the event plus this step (percentage points)
POST_WINDOW_MAX_STEP = 10
# Minimum distance between two controller runs of one room.
MIN_COMPUTE_SPACING = 60
# Exercise timing
EXERCISE_HOLD = 300


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _state_float(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, None, ""):
        return None
    return _to_float(state.state)


def _now_ts() -> float:
    return dt_util.utcnow().timestamp()


def _reported_ts(state: State) -> float:
    """Timestamp of the last report of a state (also without a value change)."""
    reported = getattr(state, "last_reported", None) or state.last_updated
    return reported.timestamp()


def _valve_step_to_percent(step: Any) -> int:
    """Convert the stored valve step ("*", "1".."5" or a legacy int) to %."""
    if isinstance(step, (int, float)) and not isinstance(step, bool):
        return int(max(0, min(100, step)))
    return VALVE_OPENING_STEPS.get(str(step), VALVE_OPENING_STEPS["2"])


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SonTRV climate platform."""
    climate_entity = SonClouTRVClimate(hass, config_entry)

    entry_data = hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    entry_data.setdefault("entities", []).append(climate_entity)
    entry_data["climate"] = climate_entity

    async_add_entities([climate_entity])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("calibrate_valve", {}, "async_calibrate_valve")
    platform.async_register_entity_service("reset_learning", {}, "async_reset_learning")
    platform.async_register_entity_service("exercise_valve", {}, "async_trigger_valve_exercise")


class SonClouTRVClimate(ClimateEntity, RestoreEntity):
    """SonTRV thermostat."""

    _attr_should_poll = False
    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = ["*", "1", "2", "3", "4", "5"]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the entity."""
        self.hass = hass
        self._entry = entry
        self._entry_id = entry.entry_id
        conf = {**entry.data, **entry.options}

        self._attr_name = conf[CONF_NAME]
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        # Marker used by the other platforms to find this entity.
        self._entity_id_base = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"SonTRV {conf[CONF_NAME]}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version=VERSION,
            configuration_url="https://github.com/k2dp2k/soncloutrv",
        )

        # --- wiring (structural, a change reloads the entry) ---------------
        self._valve_entity: str = conf[CONF_VALVE_ENTITY]
        self._temp_sensor: str = conf[CONF_TEMP_SENSOR]
        self._outside_temp_sensor: str | None = conf.get(CONF_OUTSIDE_TEMP_SENSOR) or conf.get(
            CONF_WEATHER_ENTITY
        )
        self._room_id: str | None = conf.get(CONF_ROOM_ID)
        self._room_key: str = self._room_id or self._temp_sensor
        raw_sensors = conf.get(CONF_WINDOW_SENSORS) or []
        self._window_sensors: list[str] = (
            list(raw_sensors) if isinstance(raw_sensors, (list, tuple)) else [raw_sensors]
        )
        self._window_sensor_scope: str = conf.get(CONF_WINDOW_SENSOR_SCOPE, WINDOW_SCOPE_LOCAL)

        base = self._valve_entity.split(".", 1)[1]
        self._device_id = base
        self._sensor_select_entity = f"select.{base}_temperature_sensor_select"
        self._temp_input_entity = f"number.{base}_external_temperature_input"
        self._valve_opening_entity = f"number.{base}_valve_opening_degree"
        self._valve_closing_entity = f"number.{base}_valve_closing_degree"
        self._calibration_entity = f"select.{base}_valve_calibration"
        # Bosch Radiator Thermostat II (BTH-RA / RBSH-TRV0-ZB-EU)
        self._pi_demand_entity = f"number.{base}_pi_heating_demand"
        self._remote_temp_entity = f"number.{base}_remote_temperature"
        self._adapt_button_entity = f"button.{base}_valve_adapt_process"
        self._driver: str | None = None
        self._local_temp_entity: str | None = None  # resolved in async_added_to_hass
        self._mqtt_topic_base = f"zigbee2mqtt/{base}/set"

        self._attr_min_temp = float(conf.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP))
        self._attr_max_temp = float(conf.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP))
        self._attr_target_temperature = float(conf.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP))
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_current_temperature: float | None = None

        # --- live settings (filled by _load_settings) ----------------------
        self._heating_type = HEATING_TYPE_FLOOR
        self._control_mode = DEFAULT_CONTROL_MODE
        self._kp = self._ki = self._kd = self._ka = 0.0
        self._hysteresis = DEFAULT_HYSTERESIS
        self._min_valve_update_interval = 900
        self._horizon_s = 2700.0
        self._max_valve_position = 40
        self._current_valve_step = "2"
        self._valve_min_opening = DEFAULT_VALVE_MIN_OPENING
        self._room_power_share = DEFAULT_ROOM_POWER_SHARE
        self._sensor_timeout_s = DEFAULT_SENSOR_TIMEOUT * 60
        self._adaptive_ff = DEFAULT_ADAPTIVE_FF
        self._pwm_period_s = 3600
        self._window_drop_threshold = DEFAULT_WINDOW_DROP_THRESHOLD
        self._window_stable_band = DEFAULT_WINDOW_STABLE_BAND
        self._window_max_freeze = DEFAULT_WINDOW_MAX_FREEZE
        self._room_logging_enabled = DEFAULT_ROOM_LOGGING_ENABLED
        self._room_log_path = hass.config.path(DEFAULT_ROOM_LOG_FILE)
        self._load_settings()

        # --- runtime state -------------------------------------------------
        self._controller: RoomController | None = None
        self._last_result: ControllerResult | None = None
        self._demand = 0.0
        self._valve_position = 0  # commanded opening
        self._last_written: int | None = None
        self._last_valve_update = None  # datetime of last write
        self._last_write_ts: float | None = None
        self._valve_mismatch_count = 0
        self._valve_write_errors = 0
        self._reported_opening: float | None = None
        self._valve_adjustments_count = 0
        self._valve_position_history: list[int] = []
        self._active = False
        self._is_exercising = False
        self._exercise_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._next_run_unsub: CALLBACK_TYPE | None = None
        self._next_update_time = None
        self._pwm_period_start: float | None = None
        self._pwm_on_s = 0.0
        self._pwm_unsub: CALLBACK_TYPE | None = None
        self._remove_listeners: list[CALLBACK_TYPE] = []
        self._started = False
        self._removed = False
        self._temp_source = "sensor"
        self._local_offset: float | None = None
        self._last_ext_sync_value: float | None = None
        self._last_ext_sync_ts: float | None = None
        self._outside_temperature: float | None = None
        self._trv_internal_temp: float | None = None
        self._trv_battery: float | None = None
        self._temp_history: list[float] = []
        self._temp_time_history: list[float] = []

        # Window state
        self._window_freeze_active = False
        self._window_freeze_start = None
        self._window_by_sensor = False
        self._window_min_temp: float | None = None
        self._pre_window_valve_opening: int | None = None
        self._post_window_soft_mode_until: float | None = None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @callback
    def _load_settings(self) -> None:
        """(Re-)read all live settings from data + options."""
        conf = {**self._entry.data, **self._entry.options}

        heating_type = conf.get(CONF_HEATING_TYPE, HEATING_TYPE_FLOOR)
        self._heating_type = heating_type if heating_type in HEATING_TYPES else HEATING_TYPE_FLOOR
        profile = get_profile(self._heating_type)

        mode = conf.get(CONF_CONTROL_MODE, DEFAULT_CONTROL_MODE)
        self._control_mode = mode if mode in CONTROL_MODES else DEFAULT_CONTROL_MODE

        legacy_p = conf.get(CONF_PROPORTIONAL_GAIN)
        self._kp = max(0.0, _to_float(conf.get(CONF_KP, legacy_p), profile.kp) or 0.0)
        self._ki = max(0.0, _to_float(conf.get(CONF_KI), profile.ki) or 0.0)
        self._kd = max(0.0, _to_float(conf.get(CONF_KD), 0.0) or 0.0)
        self._ka = max(0.0, _to_float(conf.get(CONF_KA), 0.0) or 0.0)
        self._hysteresis = max(0.05, _to_float(conf.get(CONF_HYSTERESIS), DEFAULT_HYSTERESIS))

        interval_min = _to_float(conf.get(CONF_MIN_VALVE_UPDATE_INTERVAL))
        interval_s = interval_min * 60 if interval_min else profile.interval_s
        self._min_valve_update_interval = int(max(60, min(3600, interval_s)))

        horizon_min = _to_float(conf.get(CONF_PREDICTION_HORIZON))
        self._horizon_s = horizon_min * 60 if horizon_min is not None else profile.horizon_s
        self._horizon_s = max(0.0, min(4 * 3600.0, self._horizon_s))

        step = conf.get(CONF_VALVE_OPENING_STEP, conf.get(CONF_MAX_VALVE_POSITION, "2"))
        self._max_valve_position = _valve_step_to_percent(step)
        self._current_valve_step = (
            str(step) if str(step) in VALVE_OPENING_STEPS else self._step_for_percent(self._max_valve_position)
        )
        self._attr_preset_mode = self._current_valve_step

        self._valve_min_opening = int(
            max(0, min(50, _to_float(conf.get(CONF_VALVE_MIN_OPENING), DEFAULT_VALVE_MIN_OPENING)))
        )
        self._room_power_share = max(
            0.0, min(2.0, _to_float(conf.get(CONF_ROOM_POWER_SHARE), DEFAULT_ROOM_POWER_SHARE))
        )
        self._sensor_timeout_s = max(
            600.0, (_to_float(conf.get(CONF_SENSOR_TIMEOUT), DEFAULT_SENSOR_TIMEOUT) or 0) * 60
        )
        self._adaptive_ff = bool(conf.get(CONF_ADAPTIVE_FF, DEFAULT_ADAPTIVE_FF))
        pwm_min = _to_float(conf.get(CONF_PWM_PERIOD))
        self._pwm_period_s = int(pwm_min * 60) if pwm_min else profile.pwm_period_s
        self._pwm_period_s = max(600, min(4 * 3600, self._pwm_period_s))

        self._window_drop_threshold = _to_float(
            conf.get(CONF_WINDOW_DROP_THRESHOLD), DEFAULT_WINDOW_DROP_THRESHOLD
        )
        self._window_stable_band = _to_float(
            conf.get(CONF_WINDOW_STABLE_BAND), DEFAULT_WINDOW_STABLE_BAND
        )
        self._window_max_freeze = int(
            _to_float(conf.get(CONF_WINDOW_MAX_FREEZE), DEFAULT_WINDOW_MAX_FREEZE)
        )
        self._room_logging_enabled = bool(
            conf.get(CONF_ROOM_LOGGING_ENABLED, DEFAULT_ROOM_LOGGING_ENABLED)
        )
        self._room_log_path = self.hass.config.path(
            conf.get(CONF_ROOM_LOG_FILE) or DEFAULT_ROOM_LOG_FILE
        )

    def _controller_settings(self) -> ControllerSettings:
        return ControllerSettings(
            heating_type=self._heating_type,
            kp=self._kp,
            ki=self._ki,
            kd=self._kd,
            ka=self._ka,
            horizon_s=self._horizon_s,
            hysteresis=self._hysteresis,
            adaptive_ff=self._adaptive_ff,
        )

    @staticmethod
    def _step_for_percent(percent: int) -> str:
        for step, value in VALVE_OPENING_STEPS.items():
            if value == percent:
                return step
        return "2"

    @callback
    def async_options_updated(self) -> None:
        """Apply non-structural option changes live."""
        self._load_settings()
        if self._controller is not None:
            self._controller = runtime.get_controller(
                self.hass, self._room_key, self._controller_settings()
            )
        self._request_control("options")

    @callback
    def async_update_setting(self, key: str, value: Any) -> None:
        """Set a single live setting (called by number/select entities)."""
        # The number/select entities persist the value in the options; the
        # options update listener re-reads everything. Apply immediately too.
        self._load_settings()
        overrides = {
            CONF_KP: "_kp",
            CONF_KI: "_ki",
            CONF_KD: "_kd",
            CONF_KA: "_ka",
            CONF_HYSTERESIS: "_hysteresis",
            CONF_ROOM_POWER_SHARE: "_room_power_share",
        }
        if key in overrides:
            setattr(self, overrides[key], float(value))
        if self._controller is not None:
            self._controller.apply_settings(self._controller_settings())
        self._update_extra_attributes()
        self.async_write_ha_state()

    @callback
    def _persist_options(self, **changes: Any) -> None:
        """Persist values into the config entry options (no reload)."""
        options = {**self._entry.options, **changes}
        if options != dict(self._entry.options):
            self.hass.config_entries.async_update_entry(self._entry, options=options)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        """Run when the entity is added."""
        await super().async_added_to_hass()

        self._controller = runtime.get_controller(
            self.hass, self._room_key, self._controller_settings()
        )
        runtime.register_climate(self.hass, self._room_key, self)
        self._resolve_local_temp_entity()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last_state.state)
            restored_target = _to_float(last_state.attributes.get(ATTR_TEMPERATURE))
            if restored_target is not None:
                self._attr_target_temperature = min(
                    self._attr_max_temp, max(self._attr_min_temp, restored_target)
                )
            offset = _to_float(last_state.attributes.get("sensor_fallback_offset"))
            if offset is not None and abs(offset) < 5:
                self._local_offset = offset

        # One set-point per room: all circuits of a room follow the room
        # thermostat. A circuit joining a room adopts the room's set-point.
        for other in runtime.room_climates(self.hass, self._room_key):
            if other is not self and other._attr_target_temperature is not None:
                if other._attr_target_temperature != self._attr_target_temperature:
                    _LOGGER.info(
                        "%s: adopting room set-point %.1f °C of %s",
                        self.name,
                        other._attr_target_temperature,
                        other.name,
                    )
                    self._attr_target_temperature = min(
                        self._attr_max_temp, max(self._attr_min_temp, other._attr_target_temperature)
                    )
                break

        # Prime the trend with the current values so the first run has data.
        self._ingest_room_temperature(self.hass.states.get(self._temp_sensor))
        if self._outside_temp_sensor:
            self._ingest_outside_temperature(self.hass.states.get(self._outside_temp_sensor))
        self._read_trv_attributes(self.hass.states.get(self._valve_entity))

        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass, [self._temp_sensor], self._async_sensor_changed
            )
        )
        if self._outside_temp_sensor:
            self._remove_listeners.append(
                async_track_state_change_event(
                    self.hass, [self._outside_temp_sensor], self._async_outside_sensor_changed
                )
            )
        trv_entities = [self._valve_entity, self._valve_opening_entity, self._pi_demand_entity]
        self._remove_listeners.append(
            async_track_state_change_event(self.hass, trv_entities, self._async_trv_changed)
        )
        if self._window_sensors:
            self._remove_listeners.append(
                async_track_state_change_event(
                    self.hass, self._window_sensors, self._async_window_sensor_changed
                )
            )

        self._update_extra_attributes()

        # Start the control loop once HA is up; stagger the circuits so the
        # valves of all rooms do not move at the same moment (they share one
        # supply and influence each other hydraulically).
        stagger = 20 + (sum(ord(c) for c in self._entry_id) % 90)

        @callback
        def _start(_hass: HomeAssistant) -> None:
            self._started = True
            self._schedule_next(stagger)

        self.async_on_remove(async_at_started(self.hass, _start))

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
        self._removed = True
        self._cancel_next()
        self._cancel_pwm()
        if self._exercise_task is not None:
            self._exercise_task.cancel()
            self._exercise_task = None
        for remove in self._remove_listeners:
            remove()
        self._remove_listeners.clear()
        runtime.unregister_climate(self.hass, self._room_key, self)
        runtime.schedule_save(self.hass)

    @callback
    def _resolve_local_temp_entity(self) -> None:
        """Find the TRV's own temperature sensor (fallback source)."""
        registry = er.async_get(self.hass)
        valve_entry = registry.async_get(self._valve_entity)
        if valve_entry and valve_entry.device_id:
            for entry in er.async_entries_for_device(registry, valve_entry.device_id):
                if entry.domain == "sensor" and entry.entity_id.endswith("local_temperature"):
                    self._local_temp_entity = entry.entity_id
                    return
        candidate = f"sensor.{self._device_id}_local_temperature"
        if self.hass.states.get(candidate) is not None:
            self._local_temp_entity = candidate

    @property
    def trv_driver(self) -> str:
        """TRV type, detected from the Zigbee2MQTT entities of the device."""
        if self._driver is None:
            registry = er.async_get(self.hass)
            if (
                self.hass.states.get(self._valve_opening_entity) is not None
                or registry.async_get(self._valve_opening_entity) is not None
            ):
                self._driver = TRV_DRIVER_SONOFF
            elif (
                self.hass.states.get(self._pi_demand_entity) is not None
                or registry.async_get(self._pi_demand_entity) is not None
            ):
                self._driver = TRV_DRIVER_BOSCH
            else:
                # Unknown yet (Z2M still starting) - behave like a TRVZB but
                # detect again next time.
                return TRV_DRIVER_SONOFF
        return self._driver

    @property
    def _valve_report_entity(self) -> str:
        return self._pi_demand_entity if self.trv_driver == TRV_DRIVER_BOSCH else self._valve_opening_entity

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    @callback
    def _cancel_next(self) -> None:
        if self._next_run_unsub is not None:
            self._next_run_unsub()
            self._next_run_unsub = None

    @callback
    def _schedule_next(self, delay: float | None = None) -> None:
        self._cancel_next()
        if delay is None:
            delay = self._min_valve_update_interval
        self._next_update_time = dt_util.now() + timedelta(seconds=delay)

        @callback
        def _run(_now) -> None:
            self._next_run_unsub = None
            self.hass.async_create_task(self._async_control("interval"))

        self._next_run_unsub = async_call_later(self.hass, delay, _run)

    @callback
    def _request_control(self, reason: str, *, force_write: bool = False) -> None:
        """Run the control loop soon (event driven)."""
        if not self._started or self._removed:
            return
        self.hass.async_create_task(self._async_control(reason, force_write=force_write))

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    @callback
    def _ingest_room_temperature(self, state: State | None) -> None:
        value = _state_float(state)
        if value is None or state is None:
            return
        if not -30.0 < value < 60.0:
            _LOGGER.debug("%s: ignoring implausible temperature %s", self.name, value)
            return
        ts = _reported_ts(state)
        self._attr_current_temperature = value
        self._temp_source = "sensor"
        if self._controller is not None:
            self._controller.add_temperature(ts, value)
        self._temp_history.append(value)
        self._temp_time_history.append(ts)
        if len(self._temp_history) > 30:
            self._temp_history.pop(0)
            self._temp_time_history.pop(0)
        if self._window_freeze_active:
            if self._window_min_temp is None or value < self._window_min_temp:
                self._window_min_temp = value
        # Learn the offset between room sensor and TRV sensor for the fallback.
        local = _state_float(self.hass.states.get(self._local_temp_entity)) if self._local_temp_entity else None
        if local is not None:
            offset = value - local
            if self._local_offset is None:
                self._local_offset = offset
            else:
                self._local_offset += 0.05 * (offset - self._local_offset)

    @callback
    def _ingest_outside_temperature(self, state: State | None) -> None:
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if state.domain == "weather":
            value = _to_float(state.attributes.get("temperature"))
            if value is None:
                value = _to_float(state.attributes.get("current_temperature"))
        else:
            value = _to_float(state.state)
        if value is None or not -50.0 < value < 60.0:
            return
        self._outside_temperature = value
        if self._controller is not None:
            self._controller.add_outside_temperature(_reported_ts(state), value)

    async def _async_outside_sensor_changed(self, event: Event) -> None:
        self._ingest_outside_temperature(event.data.get("new_state"))

    async def _async_sensor_changed(self, event: Event) -> None:
        """Room temperature changed: feed the trend, detect windows, sync TRV."""
        old_state: State | None = event.data.get("old_state")
        new_state: State | None = event.data.get("new_state")
        self._ingest_room_temperature(new_state)

        old_temp = _state_float(old_state)
        new_temp = _state_float(new_state)
        if (
            not self._window_sensors
            and old_temp is not None
            and new_temp is not None
            and self._attr_hvac_mode == HVACMode.HEAT
            and not self._window_freeze_active
        ):
            drop = old_temp - new_temp
            now = _now_ts()
            recent = [
                v for v, ts in zip(self._temp_history, self._temp_time_history)
                if ts >= now - WINDOW_DROP_WINDOW
            ]
            if drop >= self._window_drop_threshold or (
                recent and max(recent) - new_temp >= self._window_drop_threshold
            ):
                _LOGGER.info("%s: sudden temperature drop - assuming open window", self.name)
                await self._async_start_window_freeze(by_sensor=False)

        if new_temp is not None:
            await self._async_sync_external_temperature()
        self._update_extra_attributes()
        self.async_write_ha_state()

    async def _async_trv_changed(self, event: Event) -> None:
        """TRV or its valve number changed."""
        new_state: State | None = event.data.get("new_state")
        old_state: State | None = event.data.get("old_state")
        if new_state is None:
            return
        if new_state.entity_id in (self._valve_opening_entity, self._pi_demand_entity):
            if new_state.entity_id == self._valve_report_entity:
                self._reported_opening = _state_float(new_state)
            return
        self._read_trv_attributes(new_state)
        was_unavailable = old_state is None or old_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        if was_unavailable and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.info("%s: TRV %s available again - resyncing", self.name, self._valve_entity)
            self._last_ext_sync_ts = None
            self._request_control("trv_available", force_write=True)
        self._update_extra_attributes()
        self.async_write_ha_state()

    @callback
    def _read_trv_attributes(self, state: State | None) -> None:
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        attributes = state.attributes
        for key in ("_battery", "battery"):
            raw = attributes.get(key)
            if raw is None:
                continue
            value = _to_float(str(raw).replace("%", "").strip()) if isinstance(raw, str) else _to_float(raw)
            if value is not None:
                self._trv_battery = value
                break
        if self._local_temp_entity:
            local = _state_float(self.hass.states.get(self._local_temp_entity))
            if local is not None:
                self._trv_internal_temp = local
                return
        for key in ("local_temperature", "current_temperature"):
            value = _to_float(attributes.get(key))
            if value is not None:
                self._trv_internal_temp = value
                break

    # ------------------------------------------------------------------
    # Temperature source (with fallback)
    # ------------------------------------------------------------------
    def _current_room_temperature(self, now: float) -> tuple[float | None, str]:
        """Return the room temperature to control on and its source."""
        state = self.hass.states.get(self._temp_sensor)
        value = _state_float(state)
        if value is not None and state is not None and now - _reported_ts(state) <= self._sensor_timeout_s:
            return value, "sensor"
        if self._local_temp_entity:
            local_state = self.hass.states.get(self._local_temp_entity)
            local = _state_float(local_state)
            if local is not None and local_state is not None and now - _reported_ts(local_state) <= self._sensor_timeout_s:
                return local + (self._local_offset or 0.0), "trv_sensor"
        return None, "none"

    # ------------------------------------------------------------------
    # Control loop
    # ------------------------------------------------------------------
    def _trv_available(self) -> bool:
        state = self.hass.states.get(self._valve_entity)
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    async def _async_control(self, reason: str, *, force_write: bool = False) -> None:
        """One control cycle. Never raises."""
        async with self._lock:
            try:
                await self._async_control_locked(reason, force_write)
            except Exception:  # never let the loop die
                _LOGGER.exception("%s: control cycle failed", self.name)
            finally:
                if not self._removed:
                    self._schedule_next()
                    self._update_extra_attributes()
                    self.async_write_ha_state()

    async def _async_control_locked(self, reason: str, force_write: bool) -> None:
        now = _now_ts()
        if self._is_exercising:
            return

        # ----- OFF -----
        if self._attr_hvac_mode == HVACMode.OFF:
            self._demand = 0.0
            self._cancel_pwm()
            if self._controller is not None and self._room_all_off():
                self._controller.frozen = False
            await self._async_write_valve(0, force=force_write)
            await self._async_ensure_trv_mode(HVACMode.OFF)
            self._active = False
            return

        await self._async_ensure_trv_mode(HVACMode.HEAT)

        # ----- temperature -----
        temp, source = self._current_room_temperature(now)
        self._temp_source = source
        if source == "trv_sensor" and temp is not None and self._controller is not None:
            self._controller.add_temperature(now, temp)
            self._attr_current_temperature = round(temp, 2)
        elif source == "sensor" and temp is not None:
            self._attr_current_temperature = temp

        # ----- window -----
        if self._window_freeze_active:
            if self._is_window_freeze_over(now):
                await self._async_end_window_freeze()
            else:
                self._demand = 0.0
                await self._async_write_valve(0, force=force_write)
                self._active = False
                self._log_row(now)
                return

        # ----- controller -----
        ctrl = self._controller
        target = self._attr_target_temperature
        if ctrl is None or target is None:
            return
        compute_mode = self._control_mode if self._control_mode in (
            CONTROL_MODE_BINARY, CONTROL_MODE_PROPORTIONAL
        ) else CONTROL_MODE_PID
        if source == "none":
            # No usable temperature: do not learn from a stale trend, hold the
            # learned steady-state demand (integral + weather feed-forward).
            ff = ctrl.feed_forward(target)
            self._demand = max(0.0, min(60.0, ctrl.integral + ff))
            self._temp_source = "hold"
            ctrl.last_time = now
        elif (
            ctrl.last_result is None
            or ctrl.last_time is None
            or now - ctrl.last_time >= MIN_COMPUTE_SPACING
            or reason in ("target", "options", "mode")
        ):
            result = ctrl.compute(now, target, heating_enabled=True, mode=compute_mode)
            runtime.schedule_save(self.hass)
            self._last_result = result
            self._demand = result.demand
        else:
            self._last_result = ctrl.last_result
            self._demand = ctrl.last_result.demand

        # ----- output -----
        if self._control_mode == CONTROL_MODE_PWM:
            await self._async_run_pwm(now, force_write)
            self._log_row(now)
            return

        opening = demand_to_opening(
            self._demand,
            self._max_valve_position,
            share=self._room_power_share,
            min_opening=self._valve_min_opening,
        )
        if self._control_mode == CONTROL_MODE_BINARY:
            opening = self._max_valve_position if self._demand > 0 else 0
        opening = self._apply_post_window_limit(now, opening)
        await self._async_write_valve(opening, force=force_write)
        self._active = opening > 0
        await self._async_sync_external_temperature()
        await self._async_sync_target_temperature()
        self._log_row(now)

    @callback
    def _room_all_off(self) -> bool:
        return all(
            c._attr_hvac_mode == HVACMode.OFF for c in runtime.room_climates(self.hass, self._room_key)
        )

    def _apply_post_window_limit(self, now: float, opening: int) -> int:
        if self._post_window_soft_mode_until is None:
            return opening
        if now >= self._post_window_soft_mode_until:
            self._post_window_soft_mode_until = None
            self._pre_window_valve_opening = None
            return opening
        limit = (self._pre_window_valve_opening or 0) + POST_WINDOW_MAX_STEP
        return min(opening, limit, self._max_valve_position)

    # ----- PWM ---------------------------------------------------------
    @callback
    def _cancel_pwm(self) -> None:
        if self._pwm_unsub is not None:
            self._pwm_unsub()
            self._pwm_unsub = None

    async def _async_run_pwm(self, now: float, force_write: bool) -> None:
        """Time proportional control: open fully for a share of the period."""
        if self._pwm_period_start is None or now - self._pwm_period_start >= self._pwm_period_s:
            self._pwm_period_start = now
            share_demand = max(0.0, min(100.0, self._demand * self._room_power_share))
            self._pwm_on_s = pwm_on_seconds(share_demand, self._pwm_period_s)
            self._cancel_pwm()
            if 0 < self._pwm_on_s < self._pwm_period_s:
                @callback
                def _pwm_off(_now) -> None:
                    self._pwm_unsub = None
                    self.hass.async_create_task(self._async_pwm_switch_off())

                self._pwm_unsub = async_call_later(self.hass, self._pwm_on_s, _pwm_off)
        elapsed = now - self._pwm_period_start
        opening = self._max_valve_position if elapsed < self._pwm_on_s else 0
        opening = self._apply_post_window_limit(now, opening)
        await self._async_write_valve(opening, force=force_write, deadband=0)
        self._active = opening > 0
        await self._async_sync_external_temperature()
        await self._async_sync_target_temperature()

    async def _async_pwm_switch_off(self) -> None:
        async with self._lock:
            if self._control_mode != CONTROL_MODE_PWM or self._is_exercising:
                return
            if self._attr_hvac_mode == HVACMode.HEAT:
                await self._async_write_valve(0, deadband=0)
                self._active = False
            self._update_extra_attributes()
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Window handling
    # ------------------------------------------------------------------
    async def _async_window_sensor_changed(self, event: Event) -> None:
        is_open = self._own_window_open()
        if self._window_sensor_scope == WINDOW_SCOPE_ALL:
            targets = runtime.all_climates(self.hass)
        else:
            targets = runtime.room_climates(self.hass, self._room_key) or [self]
        for entity in targets:
            if entity is self:
                await self._async_handle_window(is_open)
            else:
                self.hass.async_create_task(entity._async_handle_window(is_open))

    def _own_window_open(self) -> bool:
        for entity_id in self._window_sensors:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == "on":
                return True
        return False

    def _any_window_open(self) -> bool:
        """Own sensors, room mates' sensors, or any sensor with global scope."""
        if self._own_window_open():
            return True
        for other in runtime.all_climates(self.hass):
            if other is self:
                continue
            same_room = other._room_key == self._room_key
            if (same_room or other._window_sensor_scope == WINDOW_SCOPE_ALL) and other._own_window_open():
                return True
        return False

    async def _async_handle_window(self, is_open: bool) -> None:
        if is_open:
            await self._async_start_window_freeze(by_sensor=True)
        elif self._window_freeze_active and self._window_by_sensor:
            if not self._any_window_open():
                await self._async_end_window_freeze()
                self._request_control("window_closed")

    async def _async_start_window_freeze(self, *, by_sensor: bool) -> None:
        if not self._window_freeze_active:
            self._pre_window_valve_opening = self._valve_position
            self._window_freeze_active = True
            self._window_by_sensor = by_sensor
            self._window_freeze_start = dt_util.now()
            self._window_min_temp = self._attr_current_temperature
            self._post_window_soft_mode_until = None
            if self._controller is not None:
                self._controller.frozen = True
            _LOGGER.info("%s: window open -> valve closed, learning frozen", self.name)
        elif by_sensor:
            self._window_by_sensor = True
        if self._attr_hvac_mode == HVACMode.HEAT and not self._is_exercising:
            await self._async_write_valve(0, deadband=0)
            self._active = False
        self._update_extra_attributes()
        self.async_write_ha_state()

    async def _async_end_window_freeze(self) -> None:
        if not self._window_freeze_active:
            return
        self._window_freeze_active = False
        self._window_by_sensor = False
        self._window_freeze_start = None
        self._window_min_temp = None
        # The screed is still warm - the air cooled quickly. Keep the learned
        # integral, but limit the opening for a while so the controller does
        # not react to the cold air with full power.
        self._post_window_soft_mode_until = _now_ts() + POST_WINDOW_SOFT_DURATION
        if self._controller is not None and not any(
            c._window_freeze_active for c in runtime.room_climates(self.hass, self._room_key) if c is not self
        ):
            self._controller.frozen = False
            # The trend saw the window dip - forget it so the prediction does
            # not over-react to the recovery slope.
            self._controller.trend.clear()
            state = self.hass.states.get(self._temp_sensor)
            self._ingest_room_temperature(state)
        _LOGGER.info("%s: window closed -> resuming control (soft phase)", self.name)

    def _is_window_freeze_over(self, now: float) -> bool:
        if not self._window_freeze_active:
            return True
        if self._window_by_sensor:
            return not self._any_window_open()
        start = self._window_freeze_start
        if start is not None and (dt_util.now() - start).total_seconds() > self._window_max_freeze:
            _LOGGER.info("%s: window freeze exceeded max duration - resuming", self.name)
            return True
        # temperature based: recovered and stable again
        if len(self._temp_history) >= 3 and self._window_min_temp is not None:
            recent = self._temp_history[-3:]
            if (
                max(recent) - min(recent) <= self._window_stable_band
                and recent[-1] >= self._window_min_temp + self._window_stable_band
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # TRV output
    # ------------------------------------------------------------------
    async def _async_call(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        """Call a service, return success, never raise."""
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
            return True
        except Exception as err:
            _LOGGER.warning("%s: %s.%s failed: %s", self.name, domain, service, err)
            return False

    async def _async_set_number(self, entity_id: str, topic_suffix: str, value: float) -> bool:
        if self.hass.states.get(entity_id) is not None:
            return await self._async_call("number", "set_value", {"entity_id": entity_id, "value": value})
        if self.hass.services.has_service("mqtt", "publish"):
            return await self._async_call(
                "mqtt",
                "publish",
                {"topic": f"{self._mqtt_topic_base}/{topic_suffix}", "payload": str(value)},
            )
        return False

    def _valve_reported_mismatch(self) -> bool:
        if self._last_written is None:
            return False
        reported = _state_float(self.hass.states.get(self._valve_report_entity))
        if reported is None:
            return False
        return abs(reported - self._last_written) >= 1

    async def _async_write_valve(self, opening: int, *, force: bool = False, deadband: int | None = None) -> None:
        """Write opening + complementary closing degree if needed."""
        opening = int(max(0, min(100, opening)))
        self._valve_position = opening
        if deadband is None:
            deadband = VALVE_WRITE_DEADBAND
        now = _now_ts()
        last = self._last_written

        mismatch = self._valve_reported_mismatch()
        if mismatch:
            self._valve_mismatch_count += 1
        else:
            self._valve_mismatch_count = 0

        should_write = force or last is None
        if not should_write:
            if (opening == 0) != (last == 0):
                should_write = True
            elif abs(opening - last) >= max(1, deadband):
                should_write = True
            elif self._last_write_ts is None or now - self._last_write_ts >= VALVE_REFRESH_INTERVAL:
                should_write = True
            elif self._valve_mismatch_count >= 2:
                _LOGGER.info(
                    "%s: TRV reports %s%% but %s%% was commanded - re-sending",
                    self.name,
                    self._reported_opening,
                    last,
                )
                should_write = True
        if not should_write:
            # keep the commanded value stable for the attributes
            self._valve_position = last if last is not None else opening
            return
        if not self._trv_available():
            _LOGGER.debug("%s: TRV unavailable, postponing valve write", self.name)
            return

        closing = 100 - opening
        if self.trv_driver == TRV_DRIVER_BOSCH:
            # Bosch BTH-RA: the valve position is written directly as PI
            # heating demand; the device keeps it (tested on RBSH-TRV0-ZB-EU).
            ok = await self._async_set_number(self._pi_demand_entity, "pi_heating_demand", opening)
        # Close first when reducing, open first when increasing: the valve
        # never passes through a wider position than intended.
        elif last is not None and opening < last:
            ok = await self._async_set_number(self._valve_closing_entity, "valve_closing_degree", closing)
            ok = await self._async_set_number(self._valve_opening_entity, "valve_opening_degree", opening) and ok
        else:
            ok = await self._async_set_number(self._valve_opening_entity, "valve_opening_degree", opening)
            ok = await self._async_set_number(self._valve_closing_entity, "valve_closing_degree", closing) and ok
        if not ok:
            self._valve_write_errors += 1
            return
        if last != opening:
            self._valve_adjustments_count += 1
            self._valve_position_history.append(opening)
            if len(self._valve_position_history) > 10:
                self._valve_position_history.pop(0)
        self._last_written = opening
        self._last_write_ts = now
        self._last_valve_update = dt_util.now()
        self._valve_mismatch_count = 0
        _LOGGER.debug("%s: valve opening %s%% (closing %s%%)", self.name, opening, closing)

    async def _async_ensure_trv_mode(self, mode: HVACMode) -> None:
        state = self.hass.states.get(self._valve_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if state.state == mode:
            return
        supported = state.attributes.get("hvac_modes") or []
        if supported and mode not in supported:
            return
        _LOGGER.info("%s: setting TRV %s to %s", self.name, self._valve_entity, mode)
        await self._async_call(
            "climate", "set_hvac_mode", {"entity_id": self._valve_entity, "hvac_mode": mode}
        )

    async def _async_sync_external_temperature(self) -> None:
        """Send the room temperature to the TRV (external sensor input)."""
        temp = self._attr_current_temperature
        if temp is None or self._temp_source not in ("sensor", "trv_sensor"):
            return
        if not self._trv_available():
            return
        value = round(float(temp), 1)
        now = _now_ts()
        bosch = self.trv_driver == TRV_DRIVER_BOSCH
        refresh = EXT_TEMP_REFRESH_INTERVAL_BOSCH if bosch else EXT_TEMP_REFRESH_INTERVAL
        due = (
            self._last_ext_sync_value is None
            or abs(value - self._last_ext_sync_value) >= 0.1
            or self._last_ext_sync_ts is None
            or now - self._last_ext_sync_ts >= refresh
        )
        if not due:
            return
        if bosch:
            # remote_temperature: 0-35 °C, must be refreshed every < 30 min
            clamped = max(0.0, min(35.0, value))
            if await self._async_set_number(self._remote_temp_entity, "remote_temperature", clamped):
                self._last_ext_sync_value = value
                self._last_ext_sync_ts = now
            return
        select_state = self.hass.states.get(self._sensor_select_entity)
        if select_state is not None and select_state.state != "external":
            await self._async_call(
                "select", "select_option", {"entity_id": self._sensor_select_entity, "option": "external"}
            )
        elif select_state is None and self.hass.services.has_service("mqtt", "publish") and self._last_ext_sync_ts is None:
            await self._async_call(
                "mqtt",
                "publish",
                {"topic": f"{self._mqtt_topic_base}/temperature_sensor_select", "payload": "external"},
            )
        if await self._async_set_number(self._temp_input_entity, "external_temperature_input", value):
            self._last_ext_sync_value = value
            self._last_ext_sync_ts = now

    async def _async_sync_target_temperature(self) -> None:
        """Keep the TRV set-point in line (TRV step is 0.5 K)."""
        target = self._attr_target_temperature
        state = self.hass.states.get(self._valve_entity)
        if target is None or state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        rounded = round(target * 2) / 2
        current = _to_float(state.attributes.get(ATTR_TEMPERATURE))
        if current is not None and abs(current - rounded) < 0.01:
            return
        await self._async_call(
            "climate", "set_temperature", {"entity_id": self._valve_entity, "temperature": rounded}
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    _LOG_HEADER = [
        "timestamp", "room_key", "climate_entity", "heating_type", "control_mode",
        "room_temp", "temp_source", "target_temp", "error", "predicted_error",
        "slope_k_per_h", "room_demand_percent", "valve_opening_percent",
        "max_valve_position", "outside_temp", "hvac_mode", "kp", "ki", "kd", "ka",
        "pid_p", "pid_i", "pid_d", "pid_ff", "ff_learned", "learning",
        "no_heat_supply", "window_freeze_active", "post_window_soft_active",
    ]

    @callback
    def _log_row(self, now: float) -> None:
        if not self._room_logging_enabled:
            return
        r = self._last_result
        ctrl = self._controller
        row = [
            dt_util.utc_from_timestamp(now).isoformat(),
            self._room_key,
            self.entity_id,
            self._heating_type,
            self._control_mode,
            self._attr_current_temperature,
            self._temp_source,
            self._attr_target_temperature,
            None if r is None else round(r.error, 3),
            None if r is None else round(r.predicted_error, 3),
            None if r is None else round(r.slope, 3),
            round(self._demand, 2),
            self._valve_position,
            self._max_valve_position,
            self._outside_temperature,
            self._attr_hvac_mode,
            self._kp, self._ki, self._kd, self._ka,
            None if r is None else round(r.p, 2),
            None if r is None else round(r.i, 2),
            None if r is None else round(r.d, 2),
            None if r is None else round(r.ff, 2),
            None if ctrl is None or ctrl.ff_coeff is None else round(ctrl.ff_coeff, 4),
            int(bool(r and r.learning)),
            int(bool(ctrl and ctrl.no_heat_supply)),
            int(self._window_freeze_active),
            int(self._post_window_soft_mode_until is not None),
        ]
        self.hass.async_add_executor_job(self._append_log_row, self._room_log_path, row)

    @classmethod
    def _append_log_row(cls, path: str, row: list[Any]) -> None:
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            write_header = True
            if os.path.isfile(path):
                with open(path, newline="", encoding="utf-8") as handle:
                    first = handle.readline().strip()
                if first == ",".join(cls._LOG_HEADER):
                    write_header = False
                else:
                    # Old format (v1.x): keep it, start a new file.
                    os.replace(path, path + ".v1.bak")
            with open(path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if write_header:
                    writer.writerow(cls._LOG_HEADER)
                writer.writerow(row)
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.error("Failed to append SonTRV room log row: %s", err)

    # ------------------------------------------------------------------
    # State / attributes
    # ------------------------------------------------------------------
    @property
    def hvac_action(self) -> HVACAction:
        """Return the current action."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._active and self._valve_position > 0:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @callback
    def _update_extra_attributes(self) -> None:
        r = self._last_result
        ctrl = self._controller
        attrs: dict[str, Any] = {
            ATTR_VALVE_POSITION: self._valve_position,
            "valve_reported_opening": self._reported_opening,
            ATTR_CONTROL_MODE: self._control_mode,
            "heating_type": self._heating_type,
            ATTR_TIME_CONTROL: False,
            ATTR_LAST_VALVE_UPDATE: self._last_valve_update.isoformat() if self._last_valve_update else None,
            ATTR_VALVE_ADJUSTMENTS: self._valve_adjustments_count,
            "valve_write_errors": self._valve_write_errors,
            "hysteresis": self._hysteresis,
            "min_valve_update_interval": self._min_valve_update_interval,
            "prediction_horizon_min": round(self._horizon_s / 60),
            "room_key": self._room_key,
            "trv_type": self.trv_driver,
            "room_demand": round(self._demand, 1),
            ATTR_PID_P: round(r.p, 1) if r else 0.0,
            ATTR_PID_I: round(r.i, 1) if r else round(ctrl.integral, 1) if ctrl else 0.0,
            ATTR_PID_D: round(r.d, 1) if r else 0.0,
            ATTR_PID_INTEGRAL: round(ctrl.integral, 2) if ctrl else 0.0,
            "pid_ff": round(r.ff, 1) if r else 0.0,
            "ff_learned": None if ctrl is None or ctrl.ff_coeff is None else round(ctrl.ff_coeff, 3),
            "predicted_error": round(r.predicted_error, 2) if r else None,
            "temperature_slope": round(r.slope, 2) if r else None,
            "control_reason": r.reason if r else None,
            "learning": bool(r and r.learning),
            "no_heat_supply": bool(ctrl and ctrl.no_heat_supply),
            "temperature_source": self._temp_source,
            "sensor_fallback_offset": None if self._local_offset is None else round(self._local_offset, 2),
            "outside_temperature": self._outside_temperature,
            "next_update": self._next_update_time.isoformat() if self._next_update_time else None,
            "is_exercising": self._is_exercising,
            "window_open": self._window_freeze_active,
            "window_freeze_since": self._window_freeze_start.isoformat() if self._window_freeze_start else None,
            "window_drop_threshold": self._window_drop_threshold,
            "window_stable_band": self._window_stable_band,
            "window_max_freeze": self._window_max_freeze,
            "post_window_soft_active": self._post_window_soft_mode_until is not None,
        }
        if self._attr_current_temperature is not None and self._attr_target_temperature is not None:
            attrs[ATTR_TEMPERATURE_DIFFERENCE] = round(
                self._attr_target_temperature - self._attr_current_temperature, 1
            )
            attrs[ATTR_EXTERNAL_TEMP] = self._attr_current_temperature
        if self._trv_internal_temp is not None:
            attrs[ATTR_TRV_INTERNAL_TEMP] = self._trv_internal_temp
        if self._trv_battery is not None:
            attrs[ATTR_TRV_BATTERY] = self._trv_battery
        if self._valve_position_history:
            attrs[ATTR_AVG_VALVE_POSITION] = round(
                sum(self._valve_position_history) / len(self._valve_position_history), 1
            )
        if r is not None:
            attrs[ATTR_TEMP_TREND] = round(r.slope, 2)
        self._attr_extra_state_attributes = attrs

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temperature = _to_float(kwargs.get(ATTR_TEMPERATURE))
        if temperature is None:
            return
        target = min(self._attr_max_temp, max(self._attr_min_temp, temperature))
        self._attr_target_temperature = target
        self.async_write_ha_state()
        # The set-point belongs to the room: every circuit in the room follows.
        for other in runtime.room_climates(self.hass, self._room_key):
            if other is not self:
                other.async_apply_room_target(target)
        await self._async_control("target", force_write=False)

    @callback
    def async_apply_room_target(self, target: float) -> None:
        """Follow a set-point change made on another circuit of the room."""
        target = min(self._attr_max_temp, max(self._attr_min_temp, target))
        if target == self._attr_target_temperature:
            return
        self._attr_target_temperature = target
        self._update_extra_attributes()
        self.async_write_ha_state()
        self._request_control("target")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.warning("%s: unsupported hvac_mode %s", self.name, hvac_mode)
            return
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
        await self._async_control("mode", force_write=True)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the maximum valve opening (step)."""
        if preset_mode not in self._attr_preset_modes:
            _LOGGER.warning("%s: unsupported preset %s", self.name, preset_mode)
            return
        # Persisting triggers the options listener which reloads the settings.
        self._persist_options(**{CONF_VALVE_OPENING_STEP: preset_mode})
        self._current_valve_step = preset_mode
        self._attr_preset_mode = preset_mode
        self._max_valve_position = VALVE_OPENING_STEPS.get(preset_mode, 40)
        await self._async_control("options")

    async def async_set_control_mode(self, mode: str) -> None:
        """Change the control mode live (used by the select entity)."""
        if mode not in CONTROL_MODES:
            return
        self._persist_options(**{CONF_CONTROL_MODE: mode})
        self._control_mode = mode
        self._pwm_period_start = None
        self._cancel_pwm()
        await self._async_control("mode", force_write=True)

    async def async_set_heating_type(self, heating_type: str) -> None:
        """Change the heating type; resets gains to the type's defaults."""
        if heating_type not in HEATING_TYPES:
            return
        profile = get_profile(heating_type)
        changes = {
            CONF_HEATING_TYPE: heating_type,
            CONF_KP: profile.kp,
            CONF_KI: round(profile.ki, 6),
            CONF_KD: 0.0,
        }
        options = {**self._entry.options, **changes}
        options.pop(CONF_MIN_VALVE_UPDATE_INTERVAL, None)
        options.pop(CONF_PREDICTION_HORIZON, None)
        options.pop(CONF_PWM_PERIOD, None)
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self._load_settings()
        self._controller = runtime.get_controller(self.hass, self._room_key, self._controller_settings())
        await self._async_control("options")

    async def async_reset_learning(self) -> None:
        """Forget the learned demand of this room."""
        if self._controller is not None:
            self._controller.reset_learning()
            runtime.schedule_save(self.hass)
        _LOGGER.info("%s: learned state reset", self.name)
        await self._async_control("options")

    async def async_calibrate_valve(self) -> None:
        """Trigger the TRV valve calibration."""
        if self.trv_driver == TRV_DRIVER_BOSCH:
            if self.hass.states.get(self._adapt_button_entity) is not None:
                await self._async_call("button", "press", {"entity_id": self._adapt_button_entity})
            elif self.hass.services.has_service("mqtt", "publish"):
                await self._async_call(
                    "mqtt", "publish", {"topic": f"{self._mqtt_topic_base}/valve_adapt_process", "payload": "adapt"}
                )
        elif self.hass.states.get(self._calibration_entity) is not None:
            await self._async_call(
                "select", "select_option", {"entity_id": self._calibration_entity, "option": "calibrate"}
            )
        elif self.hass.services.has_service("mqtt", "publish"):
            await self._async_call(
                "mqtt", "publish", {"topic": f"{self._mqtt_topic_base}/calibration", "payload": "run"}
            )
        # The TRV loses the positions during calibration - re-send afterwards.
        self._last_written = None

    async def async_trigger_valve_exercise(self) -> None:
        """Anti-seize exercise: 5 min open, 5 min closed, then back."""
        if self._exercise_task is not None and not self._exercise_task.done():
            _LOGGER.info("%s: valve exercise already running", self.name)
            return
        self._exercise_task = self.hass.async_create_background_task(
            self._async_exercise(), f"{DOMAIN}_exercise_{self._entry_id}"
        )

    async def _async_exercise(self) -> None:
        self._is_exercising = True
        self._update_extra_attributes()
        self.async_write_ha_state()
        state = self.hass.states.get(self._valve_entity)
        original_mode = state.state if state is not None else None
        cancelled = False
        try:
            _LOGGER.info("%s: valve exercise started", self.name)
            # The TRV must be in heat mode, otherwise it keeps the valve shut.
            await self._async_ensure_trv_mode(HVACMode.HEAT)
            await self._async_write_valve(100, force=True)
            await asyncio.sleep(EXERCISE_HOLD)
            await self._async_write_valve(0, force=True)
            await asyncio.sleep(EXERCISE_HOLD)
            self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry_id, {})[
                "last_exercise"
            ] = dt_util.now()
            _LOGGER.info("%s: valve exercise finished", self.name)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception:
            _LOGGER.exception("%s: valve exercise failed", self.name)
        finally:
            self._is_exercising = False
            self._last_written = None  # force a fresh write of the real position
            if cancelled or self._removed:
                pass
            elif self._attr_hvac_mode == HVACMode.OFF and original_mode == HVACMode.OFF:
                await self._async_write_valve(0, force=True)
                await self._async_ensure_trv_mode(HVACMode.OFF)
            else:
                self._request_control("exercise_done", force_write=True)
            self._update_extra_attributes()
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Diagnostics helper
    # ------------------------------------------------------------------
    def diagnostics(self) -> dict[str, Any]:
        """Return internal state for the diagnostics download."""
        ctrl = self._controller
        return {
            "room_key": self._room_key,
            "trv_type": self.trv_driver,
            "heating_type": self._heating_type,
            "control_mode": self._control_mode,
            "gains": {"kp": self._kp, "ki": self._ki, "kd": self._kd, "ka": self._ka},
            "horizon_s": self._horizon_s,
            "interval_s": self._min_valve_update_interval,
            "max_valve_position": self._max_valve_position,
            "valve_min_opening": self._valve_min_opening,
            "last_written": self._last_written,
            "reported_opening": self._reported_opening,
            "valve_write_errors": self._valve_write_errors,
            "temperature_source": self._temp_source,
            "local_temp_entity": self._local_temp_entity,
            "local_offset": self._local_offset,
            "window_freeze_active": self._window_freeze_active,
            "controller": None if ctrl is None else {
                **ctrl.as_dict(),
                "no_heat_supply": ctrl.no_heat_supply,
                "frozen": ctrl.frozen,
                "outside_filtered": ctrl.outside_temperature,
                "last_result": None if ctrl.last_result is None else vars(ctrl.last_result),
            },
        }
