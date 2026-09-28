"""Button platform for SonTRV."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import runtime
from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_entities([ValveExerciseButton(config_entry), ResetLearningButton(config_entry)])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"SonTRV {entry.data[CONF_NAME]}",
        manufacturer="k2dp2k",
        model="Smart Thermostat Control",
        sw_version=VERSION,
    )


class ValveExerciseButton(ButtonEntity):
    """Manually exercise the valve."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_name = f"{config_entry.data[CONF_NAME]} Ventil Durchbewegen"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_valve_exercise"
        self._attr_icon = "mdi:valve"
        self._attr_device_info = _device_info(config_entry)
        self._attr_extra_state_attributes = {
            "description": "Ventil sofort durchbewegen: 5 min 100 %, 5 min 0 %, dann Regelung. Dauer ca. 10 min."
        }

    async def async_press(self) -> None:
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is None:
            _LOGGER.warning("%s: climate not loaded", self.entity_id)
            return
        await climate.async_trigger_valve_exercise()


class ResetLearningButton(ButtonEntity):
    """Forget the learned heat demand of the room."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_name = f"{config_entry.data[CONF_NAME]} Lernwerte zurücksetzen"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_reset_learning"
        self._attr_icon = "mdi:restore"
        self._attr_entity_registry_enabled_default = True
        self._attr_device_info = _device_info(config_entry)
        self._attr_extra_state_attributes = {
            "description": "Setzt I-Anteil und gelernte Wettervorsteuerung des Raums zurück (z. B. nach Umbau)."
        }

    async def async_press(self) -> None:
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is not None:
            await climate.async_reset_learning()
