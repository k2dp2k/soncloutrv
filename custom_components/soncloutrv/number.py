"""Number platform for SonTRV (live tunable settings)."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import runtime
from .const import (
    CONF_HEATING_TYPE,
    CONF_HYSTERESIS,
    CONF_KA,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_MIN_VALVE_UPDATE_INTERVAL,
    CONF_PREDICTION_HORIZON,
    CONF_ROOM_POWER_SHARE,
    CONF_VALVE_MIN_OPENING,
    DEFAULT_HYSTERESIS,
    DEFAULT_ROOM_POWER_SHARE,
    DEFAULT_VALVE_MIN_OPENING,
    DOMAIN,
    HEATING_TYPE_FLOOR,
    VERSION,
)
from .controller import HeatingProfile, get_profile

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NumberSpec:
    key: str
    name: str
    min_value: float
    max_value: float
    step: float
    unit: str | None
    icon: str
    description: str


SPECS: list[NumberSpec] = [
    NumberSpec(
        CONF_HYSTERESIS, "Hysterese", 0.05, 2.0, 0.05, "°C", "mdi:thermometer-lines",
        "Schaltabstand im Binär-Modus. Im PID-Modus schließt das Ventil erst ab "
        "max(0,5 K; 2×Hysterese) Übertemperatur hart.",
    ),
    NumberSpec(
        CONF_MIN_VALVE_UPDATE_INTERVAL, "Trägheit (Min. Update-Intervall)", 1, 60, 1,
        UnitOfTime.MINUTES, "mdi:timer-sand",
        "Regelintervall. Standard: 15 min Fußboden, 5 min Heizkörper.",
    ),
    NumberSpec(
        CONF_KP, "PID: P-Gain (Kp)", 0.0, 150.0, 0.5, "%/°C", "mdi:thermometer-lines",
        "Proportionalanteil auf die vorhergesagte Abweichung (Heizbedarf in % pro K).",
    ),
    NumberSpec(
        CONF_KI, "PID: I-Gain (Ki - Lernen)", 0.0, 0.05, 0.00001, "%/°C/s", "mdi:chart-bell-curve-cumulative",
        "Integralanteil: lernt den dauerhaften Wärmebedarf. Nachstellzeit = Kp/Ki (Fußboden ca. 4 h).",
    ),
    NumberSpec(
        CONF_KD, "PID: D-Gain (Kd - Dämpfung)", 0.0, 100.0, 0.5, "%/(°C/h)", "mdi:speedometer-slow",
        "Zusätzliche Dämpfung auf die Temperatursteigung. Meist 0, die Vorhersage dämpft bereits.",
    ),
    NumberSpec(
        CONF_KA, "Feed-Forward: Außen-Gain (Ka)", 0.0, 10.0, 0.1, "%/°C", "mdi:weather-cloudy-arrow-right",
        "Manuelle Wettervorsteuerung. 0 = automatisch lernen.",
    ),
    NumberSpec(
        CONF_ROOM_POWER_SHARE, "Raum-Leistungsanteil", 0.1, 2.0, 0.05, None, "mdi:home-thermometer-outline",
        "Gewichtung dieses Heizkreises im gemeinsamen Raumregler (1.0 = normal).",
    ),
    NumberSpec(
        CONF_PREDICTION_HORIZON, "Vorausschau (Totzeit)", 0, 180, 5, UnitOfTime.MINUTES, "mdi:crystal-ball",
        "Wie weit der Regler die Temperatur vorausberechnet. Estrich ca. 45 min, Heizkörper ca. 12 min.",
    ),
    NumberSpec(
        CONF_VALVE_MIN_OPENING, "Ventil Öffnungsbeginn", 0, 50, 1, "%", "mdi:valve-open",
        "Öffnung, ab der tatsächlich Wasser fließt. Kleinere Stellwerte werden auf diesen Wert angehoben.",
    ),
]


def _default_for(key: str, profile: HeatingProfile) -> float:
    return {
        CONF_HYSTERESIS: DEFAULT_HYSTERESIS,
        CONF_MIN_VALVE_UPDATE_INTERVAL: profile.interval_s / 60,
        CONF_KP: profile.kp,
        CONF_KI: round(profile.ki, 6),
        CONF_KD: 0.0,
        CONF_KA: 0.0,
        CONF_ROOM_POWER_SHARE: DEFAULT_ROOM_POWER_SHARE,
        CONF_PREDICTION_HORIZON: profile.horizon_s / 60,
        CONF_VALVE_MIN_OPENING: DEFAULT_VALVE_MIN_OPENING,
    }[key]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number entities."""
    async_add_entities(SonClouTRVNumber(config_entry, spec) for spec in SPECS)


class SonClouTRVNumber(NumberEntity):
    """A live tunable setting of a SonTRV thermostat."""

    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, spec: NumberSpec) -> None:
        """Initialise."""
        self._entry = config_entry
        self._spec = spec
        name = config_entry.data[CONF_NAME]
        self._attr_translation_key = spec.key
        self._attr_name = f"{name} {spec.name}"
        # unique id scheme of v1 kept so existing entity ids stay
        self._attr_unique_id = f"{DOMAIN}_{config_entry.entry_id}_{spec.key}"
        self._attr_native_min_value = spec.min_value
        self._attr_native_max_value = spec.max_value
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_icon = spec.icon
        self._attr_extra_state_attributes = {"description": spec.description}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"SonTRV {name}",
            manufacturer="k2dp2k",
            model="Smart Thermostat Control",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> float | None:
        """Current value: stored option or the profile default."""
        conf = {**self._entry.data, **self._entry.options}
        profile = get_profile(conf.get(CONF_HEATING_TYPE, HEATING_TYPE_FLOOR))
        raw = conf.get(self._spec.key)
        if raw is None and self._spec.key == CONF_KP:
            raw = conf.get("proportional_gain")
        try:
            value = float(raw) if raw is not None else _default_for(self._spec.key, profile)
        except (TypeError, ValueError):
            value = _default_for(self._spec.key, profile)
        return max(self._spec.min_value, min(self._spec.max_value, value))

    async def async_added_to_hass(self) -> None:
        """Follow option changes (e.g. heating type switch resets gains)."""
        self.async_on_remove(self._entry.add_update_listener(self._async_entry_updated))

    async def _async_entry_updated(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Persist and apply the value live (no reload)."""
        value = max(self._spec.min_value, min(self._spec.max_value, float(value)))
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, self._spec.key: value}
        )
        climate = runtime.climate_for_entry(self.hass, self._entry.entry_id)
        if climate is not None:
            climate.async_update_setting(self._spec.key, value)
        else:
            _LOGGER.debug("%s: climate not loaded, value stored only", self.entity_id)
        self.async_write_ha_state()
