"""Constants for the SonClouTRV integration."""

DOMAIN = "soncloutrv"
PLATFORMS = ["climate", "sensor", "number", "switch", "button", "select"]

# Configuration keys
CONF_VALVE_ENTITY = "valve_entity"
CONF_TEMP_SENSOR = "temp_sensor"
CONF_HEATER_ENTITY = "heater_entity"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"
CONF_TARGET_TEMP = "target_temp"
CONF_HYSTERESIS = "hysteresis"
CONF_COLD_TOLERANCE = "cold_tolerance"
CONF_HOT_TOLERANCE = "hot_tolerance"
CONF_MIN_CYCLE_DURATION = "min_cycle_duration"
CONF_MAX_VALVE_POSITION = "max_valve_position"
CONF_VALVE_OPENING_STEP = "valve_opening_step"
CONF_CONTROL_MODE = "control_mode"
CONF_TIME_CONTROL_ENABLED = "time_control_enabled"
CONF_TIME_START = "time_start"
CONF_TIME_END = "time_end"
CONF_KP = "kp"
CONF_KI = "ki"
CONF_KD = "kd"
# Legacy support
CONF_PROPORTIONAL_GAIN = "proportional_gain"

# Control modes
CONTROL_MODE_BINARY = "binary"
CONTROL_MODE_PID = "pid"  # Renamed/Upgraded from proportional
# Legacy support
CONTROL_MODE_PROPORTIONAL = "proportional"

# Valve opening steps (* = closed, then 5 levels in 20% increments)
VALVE_OPENING_STEPS = {
    "*": 0,   # Closed / Off
    "1": 20,
    "2": 40,
    "3": 60,
    "4": 80,
    "5": 100,
}

# Preset modes
PRESET_OFF = "*"      # 0% - Closed
PRESET_STEP_1 = "1"   # 20%
PRESET_STEP_2 = "2"   # 40%
PRESET_STEP_3 = "3"   # 60%
PRESET_STEP_4 = "4"   # 80%
PRESET_STEP_5 = "5"   # 100%

# Defaults
DEFAULT_NAME = "SonClouTRV"
DEFAULT_MIN_TEMP = 6.0
DEFAULT_MAX_TEMP = 28.0
DEFAULT_TARGET_TEMP = 21.5
DEFAULT_HYSTERESIS = 0.5  # °C
DEFAULT_COLD_TOLERANCE = 0.3
DEFAULT_HOT_TOLERANCE = 0.3
DEFAULT_MIN_CYCLE_DURATION = 300  # 5 minutes in seconds
DEFAULT_MAX_VALVE_POSITION = 80  # Prozent (Stufe 4)
DEFAULT_VALVE_OPENING_STEP = "4"  # Stufe 4 = 80%
DEFAULT_CONTROL_MODE = CONTROL_MODE_PID  # PID für Fußbodenheizung
DEFAULT_KP = 20.0
DEFAULT_KI = 0.01  # Integral-Gain (Lernfaktor)
DEFAULT_KD = 500.0  # Derivative-Gain (Overshoot-Bremse, hoch da dt in Sekunden)

# Attributes
ATTR_VALVE_POSITION = "valve_position"
ATTR_CONTROL_MODE = "control_mode"
ATTR_TIME_CONTROL = "time_control_enabled"
ATTR_LAST_VALVE_UPDATE = "last_valve_update"
ATTR_TEMPERATURE_DIFFERENCE = "temperature_difference"
ATTR_TRV_INTERNAL_TEMP = "trv_internal_temperature"
ATTR_EXTERNAL_TEMP = "external_temperature"
ATTR_TRV_BATTERY = "trv_battery"
ATTR_VALVE_ADJUSTMENTS = "valve_adjustments_count"
ATTR_AVG_VALVE_POSITION = "average_valve_position"
ATTR_TEMP_TREND = "temperature_trend"
ATTR_PID_P = "pid_p"
ATTR_PID_I = "pid_i"
ATTR_PID_D = "pid_d"
ATTR_PID_INTEGRAL = "pid_integral_error"
