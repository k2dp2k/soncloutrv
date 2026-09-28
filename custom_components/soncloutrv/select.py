"""Select platform for SonTRV."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import runtime
from .const import (
    CONF_CONTROL_MODE,
    CONF_HEATING_TYPE,
    CONTROL_MODE_BINARY,
    CONTROL_MODE_PID,
    CONTROL_MODE_PROPORTIONAL,
    CONTROL_MODE_PWM,
    DEFAULT_CONTROL_MODE,
    DOMAIN,
    HEATING_TYPE_FLOOR,
    HEATING_TYPE_RADIATOR,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"SonTRV {entry.data[CONF_NAME]}",
        manufacturer="k2dp2k",
        model="Smart Thermostat Control",
        sw_version=VERSION,
        configuration_url="https://github.com/k2dp2k/soncloutrv",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select entities."""
    async_add_entities(
        [
            SonClouTRVControlModeSelect(config_entry),
            SonClouTRVHeatingTypeSelect(config_entry),
        ]
    )


class _OptionSelect(SelectEntity):
    """Select backed by a config entry option."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _option_key: str
    _default: str

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_device_info = _device_info(entry)

    @property
    def current_option(self) -> str:
        conf = {**self._entry.data, **self._entry.options}
        value = conf.get(self._option_key, self._default)
        return value if value in self.options else self._default

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._entry.add_update_listener(self._async_entry_updated))

    async def _async_entry_updated(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.async_write_ha_state()


class SonClouTRVControlModeSelect(_OptionSelect):
    """Control mode (applied live, no reload)."""

    _attr_icon = "mdi:tune-variant"
    _attr_translation_key = "control_mode"
    _option_key = CONF_CONTROL_MODE
    _default = DEFAULT_CONTROL_MODE

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_name = "Steuermodus"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_control_mode"
        self._attr_options = [
            CONTROL_MODE_BINARY,
            CONTROL_MODE_PROPORTIONAL,
            CONTROL_MODE_PID,
            CONTROL_MODE_PWM,
        ]

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            _LOGGER.error("Invalid control mode: %s", option)
            return
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is not None:
            await climate.async_set_control_mode(option)
        else:
            self.hass.config_entries.async_update_entry(
                self._entry, options={**self._entry.options, self._option_key: option}
            )
        self.async_write_ha_state()


class SonClouTRVHeatingTypeSelect(_OptionSelect):
    """Heating type (floor / radiator) - selects the controller profile."""

    _attr_icon = "mdi:heating-coil"
    _attr_translation_key = "heating_type"
    _option_key = CONF_HEATING_TYPE
    _default = HEATING_TYPE_FLOOR

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_name = "Heizungstyp"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_heating_type"
        self._attr_options = [HEATING_TYPE_FLOOR, HEATING_TYPE_RADIATOR]

    async def async_select_option(self, option: str) -> None:
        if option not in self.options or option == self.current_option:
            return
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is not None:
            await climate.async_set_heating_type(option)
        else:
            self.hass.config_entries.async_update_entry(
                self._entry, options={**self._entry.options, self._option_key: option}
            )
        self.async_write_ha_state()
