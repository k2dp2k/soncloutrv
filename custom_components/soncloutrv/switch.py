"""Switch platform for SonTRV (anti-seize / anti-calcification exercise)."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import runtime
from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

EXERCISE_WEEKDAY = 6  # Sunday
EXERCISE_HOUR = 3
MIN_DAYS_BETWEEN = 6


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch."""
    async_add_entities([AntiCalcificationSwitch(config_entry)])


class AntiCalcificationSwitch(SwitchEntity, RestoreEntity):
    """Weekly valve exercise (Sunday 03:xx, staggered per circuit)."""

    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        name = config_entry.data[CONF_NAME]
        self._attr_name = f"{name} Verkalkungsschutz"
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_anti_calcification"
        self._attr_icon = "mdi:water-off"
        self._attr_is_on = True
        self._last_exercise = None
        # Stagger the circuits (they share one supply) over 03:00-03:50.
        self._minute = (sum(ord(c) for c in config_entry.entry_id) % 6) * 10
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {name}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state != "off"
            raw = last.attributes.get("last_exercise")
            if raw:
                self._last_exercise = dt_util.parse_datetime(str(raw))
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_tick, hour=EXERCISE_HOUR, minute=self._minute, second=0
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    async def _async_tick(self, now) -> None:
        if not self._attr_is_on or dt_util.now().weekday() != EXERCISE_WEEKDAY:
            return
        # A manual exercise (button/service) also counts.
        manual = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("last_exercise")
        latest = max((d for d in (self._last_exercise, manual) if d is not None), default=None)
        if latest is not None and dt_util.now() - latest < timedelta(days=MIN_DAYS_BETWEEN):
            return
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is None:
            _LOGGER.warning("%s: climate not loaded, exercise skipped", self.entity_id)
            return
        self._last_exercise = dt_util.now()
        await climate.async_trigger_valve_exercise()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "description": (
                "Ventil jeden Sonntag gegen 3 Uhr durchbewegen (5 min offen, 5 min zu). "
                "Funktioniert auch im Sommer bei ausgeschalteter Heizung."
            ),
            "schedule": f"Sonntag 03:{self._minute:02d}",
        }
        if self._last_exercise:
            attrs["last_exercise"] = self._last_exercise.isoformat()
            days = (dt_util.now() - self._last_exercise).days
            attrs["days_since_last_exercise"] = days
            attrs["next_exercise_in_days"] = max(0, 7 - days)
        return attrs
