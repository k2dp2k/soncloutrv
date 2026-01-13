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
CONF_ROOM_ID = "room_id"
CONF_KP = "kp"
CONF_KI = "ki"
CONF_KD = "kd"
CONF_KA = "ka"  # Ambient/Outside Gain (Feed-Forward)
# Room logging / analysis
CONF_ROOM_LOGGING_ENABLED = "room_logging_enabled"
CONF_ROOM_LOG_FILE = "room_log_file"
# Legacy support
CONF_PROPORTIONAL_GAIN = "proportional_gain"
CONF_OUTSIDE_TEMP_SENSOR = "outside_temp_sensor"
CONF_WEATHER_ENTITY = "weather_entity"
# Window / sudden temperature drop detection
CONF_WINDOW_DROP_THRESHOLD = "window_drop_threshold"
CONF_WINDOW_STABLE_BAND = "window_stable_band"
CONF_WINDOW_MAX_FREEZE = "window_max_freeze"

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
DEFAULT_MAX_TEMP = 25.0
DEFAULT_TARGET_TEMP = 21.5
# Default room names for simple assignment during setup
DEFAULT_ROOMS = [
    "Wohnzimmer",
    "Schlafzimmer",
    "Bad",
    "Küche",
    "Flur",
    "Büro",
]
DEFAULT_HYSTERESIS = 0.15  # °C - etwas feinere Regelung um den Sollwert
DEFAULT_COLD_TOLERANCE = 0.3
DEFAULT_HOT_TOLERANCE = 0.3
DEFAULT_MIN_CYCLE_DURATION = 300  # 5 minutes in seconds
DEFAULT_MAX_VALVE_POSITION = 40  # Prozent (Stufe 2)
DEFAULT_VALVE_OPENING_STEP = "2"  # Stufe 2 = 40%
DEFAULT_CONTROL_MODE = CONTROL_MODE_PID  # PID für Fußbodenheizung
# Vereinfachte Standardregelung: zunächst reiner P-Regler
# (angepasste Default-Werte, alte Konfigurationen werden in climate.py migriert)
DEFAULT_KP = 5.0
DEFAULT_KI = 0.004  # Deutlich stärkerer Integral-Gain für schnelleren Abbau von Dauerabweichungen
DEFAULT_KD = 0.0    # Derivative-Gain – default aus
DEFAULT_KA = 0.0    # Feed-Forward Gain (Standard aus, da optional)
# Room logging defaults (for external analysis / ML tuning)
DEFAULT_ROOM_LOGGING_ENABLED = False
DEFAULT_ROOM_LOG_FILE = "sontrv_room_log.csv"
# Window detection defaults
DEFAULT_WINDOW_DROP_THRESHOLD = 0.8  # °C Sprung nach unten zwischen zwei Messungen
DEFAULT_WINDOW_STABLE_BAND = 0.3     # °C Bandbreite für "stabil wieder"
DEFAULT_WINDOW_MAX_FREEZE = 1800     # Sekunden (30 Minuten) maximale Einfrierzeit

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
