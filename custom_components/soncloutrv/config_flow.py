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
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PROPORTIONAL,
    VALVE_OPENING_STEPS,
    DEFAULT_NAME,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_ROOMS,
    DEFAULT_HYSTERESIS,
    DEFAULT_COLD_TOLERANCE,
    DEFAULT_HOT_TOLERANCE,
    DEFAULT_MIN_CYCLE_DURATION,
    DEFAULT_MAX_VALVE_POSITION,
    DEFAULT_VALVE_OPENING_STEP,
    DEFAULT_CONTROL_MODE,
    CONF_OUTSIDE_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_ROOM_LOGGING_ENABLED,
    CONF_ROOM_LOG_FILE,
    DEFAULT_ROOM_LOGGING_ENABLED,
    DEFAULT_ROOM_LOG_FILE,
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

    VERSION = 1

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
                
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        # Get filtered SONOFF TRVZB entities
        available_valves = _filter_sonoff_trvzb_entities(self.hass)
        
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
                vol.Optional(CONF_ROOM_ID, default=DEFAULT_ROOMS[0]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DEFAULT_ROOMS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_OUTSIDE_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"], device_class="temperature")
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
        return SonClouTRVOptionsFlow(config_entry)


class SonClouTRVOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for SonClouTRV."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # self.config_entry is already set by base class or handled differently in newer HA versions
        # Just calling super if needed, but OptionsFlow usually doesn't need super().__init__ args
        # However, to be safe and fix the error, we remove the assignment since it's a property without setter
        pass

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Clean up old weather_entity key if present and outside_temp_sensor is used
            if CONF_OUTSIDE_TEMP_SENSOR in user_input:
                user_input.pop(CONF_WEATHER_ENTITY, None)
                
            # Merge with existing config entry data to preserve required fields
            # Also preserve optional fields if not in user_input
            merged_data = {**self.config_entry.data, **user_input}
            return self.async_create_entry(title="", data=merged_data)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OUTSIDE_TEMP_SENSOR,
                    description={"suggested_value": self.config_entry.data.get(CONF_OUTSIDE_TEMP_SENSOR, self.config_entry.data.get(CONF_WEATHER_ENTITY))},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "weather"], device_class="temperature")
                ),
                vol.Optional(
                    CONF_ROOM_LOGGING_ENABLED,
                    default=self.config_entry.data.get(CONF_ROOM_LOGGING_ENABLED, DEFAULT_ROOM_LOGGING_ENABLED),
                ): cv.boolean,
                vol.Optional(
                    CONF_ROOM_LOG_FILE,
                    default=self.config_entry.data.get(CONF_ROOM_LOG_FILE, DEFAULT_ROOM_LOG_FILE),
                ): cv.string,
                vol.Optional(
                    CONF_MIN_TEMP,
                    default=self.config_entry.data.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP),
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Optional(
                    CONF_MAX_TEMP,
                    default=self.config_entry.data.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP),
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Optional(
                    CONF_ROOM_ID,
                    default=self.config_entry.data.get(CONF_ROOM_ID, DEFAULT_ROOMS[0]),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DEFAULT_ROOMS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_TARGET_TEMP,
                    default=self.config_entry.data.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP),
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=35)),
                vol.Optional(
                    CONF_VALVE_OPENING_STEP,
                    default=self.config_entry.data.get(CONF_VALVE_OPENING_STEP, DEFAULT_VALVE_OPENING_STEP),
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
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
