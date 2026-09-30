"""Config flow for SonClouTRV integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_VALVE_ENTITY,
    CONF_TEMP_SENSOR,
    CONF_ROOM_ID,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET_TEMP,
    CONF_VALVE_OPENING_STEP,
    CONF_CONTROL_MODE,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PROPORTIONAL,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_ROOMS,
    DEFAULT_VALVE_OPENING_STEP,
    DEFAULT_CONTROL_MODE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
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
    CONF_WINDOW_SENSORS,
    CONF_WINDOW_SENSOR_SCOPE,
    WINDOW_SCOPE_LOCAL,
    WINDOW_SCOPE_ALL,
    CONFIG_VERSION,
    CONF_HEATING_TYPE,
    CONF_SENSOR_TIMEOUT,
    CONF_ADAPTIVE_FF,
    CONF_HEATER_ROLE,
    CONF_PWM_PERIOD,
    DEFAULT_HEATER_ROLE,
    HEATER_ROLE_ASSIST,
    HEATER_ROLE_AUTO,
    HEATER_ROLE_PRIMARY,
    CONTROL_MODE_PID,
    CONTROL_MODE_PWM,
    DEFAULT_SENSOR_TIMEOUT,
    DEFAULT_ADAPTIVE_FF,
    HEATING_TYPE_FLOOR,
    HEATING_TYPE_RADIATOR,
    STATS_EPOCH,
)
from .controller import get_profile

HEATING_TYPE_OPTIONS = [
    {"value": HEATING_TYPE_FLOOR, "label": "Flächenheizung / Fußboden (Estrich, träge)"},
    {"value": HEATING_TYPE_RADIATOR, "label": "Heizkörper (schnell)"},
]
HEATER_ROLE_OPTIONS = [
    {"value": HEATER_ROLE_AUTO, "label": "Automatisch (Heizkörper neben Fußboden = Zusatzheizung)"},
    {"value": HEATER_ROLE_PRIMARY, "label": "Hauptheizung (regelt den Raum)"},
    {"value": HEATER_ROLE_ASSIST, "label": "Zusatzheizung (springt nur bei Abweichung ein)"},
]
CONTROL_MODE_OPTIONS = [
    {"value": CONTROL_MODE_PID, "label": "PID (vorausschauend, stetig) - empfohlen"},
    {"value": CONTROL_MODE_PWM, "label": "Takt (PWM, auf/zu im Zeitraster)"},
    {"value": CONTROL_MODE_BINARY, "label": "Binär (Zweipunkt mit Hysterese)"},
    {"value": CONTROL_MODE_PROPORTIONAL, "label": "Proportional (Legacy)"},
]


def _outside_selector() -> selector.EntitySelector:
    """Outside temperature: a temperature sensor or a weather entity."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter=[
                selector.EntityFilterSelectorConfig(domain="sensor", device_class="temperature"),
                selector.EntityFilterSelectorConfig(domain="weather"),
            ]
        )
    )


def _room_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=DEFAULT_ROOMS,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )

_LOGGER = logging.getLogger(__name__)


def _filter_sonoff_trvzb_entities(hass: HomeAssistant) -> list[str]:
    """Filter climate entities to only show SONOFF TRVZB devices."""
    filtered_entities = []
    
    for entity_id in hass.states.async_entity_ids("climate"):
        state = hass.states.get(entity_id)
        if not state:
            continue
        
        # Check if entity is from Zigbee2MQTT and is SONOFF TRVZB
        # Zigbee2MQTT entities typically have specific attributes
        attributes = state.attributes
        
        # Check for Zigbee2MQTT integration
        if "via_device" in attributes or entity_id.startswith("climate.0x"):
            # Check device model in friendly_name or other attributes
            friendly_name = attributes.get("friendly_name", "")
            model = attributes.get("model", "")
            
            # SONOFF TRVZB identification
            if "TRVZB" in model or "trvzb" in friendly_name.lower() or "TRVZB" in friendly_name:
                filtered_entities.append(entity_id)
                continue
            
            # Alternative: Check for SONOFF manufacturer
            if "sonoff" in friendly_name.lower() or "SONOFF" in str(attributes.get("manufacturer", "")):
                # Additional check if it's a TRV (has position attribute)
                if "position" in attributes or "valve" in friendly_name.lower():
                    filtered_entities.append(entity_id)
    
    return filtered_entities


class SonClouTRVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SonClouTRV."""

    VERSION = CONFIG_VERSION

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the entities exist
            valve_entity = user_input.get(CONF_VALVE_ENTITY)
            temp_sensor = user_input.get(CONF_TEMP_SENSOR)
            
            valve_state = self.hass.states.get(valve_entity)
            if not valve_state:
                errors[CONF_VALVE_ENTITY] = "entity_not_found"
            elif valve_state.domain != "climate":
                errors[CONF_VALVE_ENTITY] = "not_climate_entity"
            
            if not self.hass.states.get(temp_sensor):
                errors[CONF_TEMP_SENSOR] = "entity_not_found"
            
            if not errors:
                # Create unique_id from valve entity
                await self.async_set_unique_id(valve_entity)
                self._abort_if_unique_id_configured()
                
                heating_type = user_input.pop(CONF_HEATING_TYPE, HEATING_TYPE_FLOOR)
                profile = get_profile(heating_type)
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                    options={
                        CONF_HEATING_TYPE: heating_type,
                        "kp": profile.kp,
                        "ki": round(profile.ki, 6),
                        "kd": 0.0,
                        "ka": 0.0,
                        "stats_epoch": STATS_EPOCH,
                    },
                )

        # Get filtered SONOFF TRVZB entities
        # (TRVZB filter helper kept for reference; the selector filters by MQTT)
        
        # Build the configuration schema
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Required(CONF_VALVE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="climate",
                        integration="mqtt",
                    )
                ),
                vol.Optional(CONF_ROOM_ID, default=DEFAULT_ROOMS[0]): _room_selector(),
                vol.Required(CONF_HEATING_TYPE, default=HEATING_TYPE_FLOOR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=HEATING_TYPE_OPTIONS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_OUTSIDE_TEMP_SENSOR): _outside_selector(),
                vol.Optional(CONF_WINDOW_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                        device_class=["window", "door"],
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_SENSOR_SCOPE,
                    default=WINDOW_SCOPE_LOCAL,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": WINDOW_SCOPE_LOCAL, "label": "Nur dieses Thermostat"},
                            {"value": WINDOW_SCOPE_ALL, "label": "Alle SonTRV-Thermostate"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=5, max=35)
                ),
                vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=5, max=35)
                ),
                vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=5, max=35)
                ),
                vol.Optional(CONF_VALVE_OPENING_STEP, default=DEFAULT_VALVE_OPENING_STEP): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "*", "label": "* Aus (0%)"},
                            {"value": "1", "label": "Stufe 1 (20%)"},
                            {"value": "2", "label": "Stufe 2 (40%)"},
                            {"value": "3", "label": "Stufe 3 (60%)"},
                            {"value": "4", "label": "Stufe 4 (80%)"},
                            {"value": "5", "label": "Stufe 5 (100%)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return SonClouTRVOptionsFlow()


class SonClouTRVOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for SonClouTRV."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        entry = self.config_entry
        current = {**entry.data, **entry.options}

        if user_input is not None:
            options = {**entry.options, **user_input}
            # Optional entity fields that were cleared must be removed.
            for key in (CONF_OUTSIDE_TEMP_SENSOR, CONF_WINDOW_SENSORS):
                if key not in user_input:
                    options.pop(key, None)
            if CONF_OUTSIDE_TEMP_SENSOR in user_input:
                options.pop(CONF_WEATHER_ENTITY, None)
            # Switching the heating type resets the gains to the new profile.
            new_type = user_input.get(CONF_HEATING_TYPE)
            if new_type and new_type != current.get(CONF_HEATING_TYPE, HEATING_TYPE_FLOOR):
                profile = get_profile(new_type)
                options.update({"kp": profile.kp, "ki": round(profile.ki, 6), "kd": 0.0})
                for key in ("min_valve_update_interval", "prediction_horizon", CONF_PWM_PERIOD):
                    options.pop(key, None)
            return self.async_create_entry(title="", data=options)

        def sv(key: str, default: Any = None) -> dict[str, Any]:
            value = current.get(key, default)
            return {"suggested_value": value} if value is not None else {}

        outside_default = current.get(CONF_OUTSIDE_TEMP_SENSOR) or current.get(CONF_WEATHER_ENTITY)
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_HEATING_TYPE, default=current.get(CONF_HEATING_TYPE, HEATING_TYPE_FLOOR)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=HEATING_TYPE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_CONTROL_MODE, default=current.get(CONF_CONTROL_MODE, DEFAULT_CONTROL_MODE)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=CONTROL_MODE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_TEMP_SENSOR, default=current.get(CONF_TEMP_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(
                    CONF_OUTSIDE_TEMP_SENSOR,
                    description={"suggested_value": outside_default} if outside_default else {},
                ): _outside_selector(),
                vol.Required(
                    CONF_ROOM_ID, default=current.get(CONF_ROOM_ID) or DEFAULT_ROOMS[0]
                ): _room_selector(),
                vol.Optional(CONF_WINDOW_SENSORS, description=sv(CONF_WINDOW_SENSORS)): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor", device_class=["window", "door"], multiple=True
                    )
                ),
                vol.Required(
                    CONF_WINDOW_SENSOR_SCOPE,
                    default=current.get(CONF_WINDOW_SENSOR_SCOPE, WINDOW_SCOPE_LOCAL),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": WINDOW_SCOPE_LOCAL, "label": "Nur dieser Raum"},
                            {"value": WINDOW_SCOPE_ALL, "label": "Alle SonTRV-Thermostate"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_WINDOW_DROP_THRESHOLD,
                    default=current.get(CONF_WINDOW_DROP_THRESHOLD, DEFAULT_WINDOW_DROP_THRESHOLD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=5.0)),
                vol.Required(
                    CONF_WINDOW_STABLE_BAND,
                    default=current.get(CONF_WINDOW_STABLE_BAND, DEFAULT_WINDOW_STABLE_BAND),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
                vol.Required(
                    CONF_WINDOW_MAX_FREEZE,
                    default=current.get(CONF_WINDOW_MAX_FREEZE, DEFAULT_WINDOW_MAX_FREEZE),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=43200)),
                vol.Required(
                    CONF_MIN_TEMP, default=current.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Required(
                    CONF_MAX_TEMP, default=current.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Required(
                    CONF_TARGET_TEMP, default=current.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP)
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Required(
                    CONF_VALVE_OPENING_STEP,
                    default=str(current.get(CONF_VALVE_OPENING_STEP, DEFAULT_VALVE_OPENING_STEP)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "*", "label": "* Aus (0%)"},
                            {"value": "1", "label": "Stufe 1 (20%)"},
                            {"value": "2", "label": "Stufe 2 (40%)"},
                            {"value": "3", "label": "Stufe 3 (60%)"},
                            {"value": "4", "label": "Stufe 4 (80%)"},
                            {"value": "5", "label": "Stufe 5 (100%)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_SENSOR_TIMEOUT, default=current.get(CONF_SENSOR_TIMEOUT, DEFAULT_SENSOR_TIMEOUT)
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=1440)),
                vol.Required(
                    CONF_ADAPTIVE_FF, default=current.get(CONF_ADAPTIVE_FF, DEFAULT_ADAPTIVE_FF)
                ): cv.boolean,
                vol.Required(
                    CONF_HEATER_ROLE, default=current.get(CONF_HEATER_ROLE, DEFAULT_HEATER_ROLE)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=HEATER_ROLE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_ROOM_LOGGING_ENABLED,
                    default=current.get(CONF_ROOM_LOGGING_ENABLED, DEFAULT_ROOM_LOGGING_ENABLED),
                ): cv.boolean,
                vol.Required(
                    CONF_ROOM_LOG_FILE, default=current.get(CONF_ROOM_LOG_FILE, DEFAULT_ROOM_LOG_FILE)
                ): cv.string,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
