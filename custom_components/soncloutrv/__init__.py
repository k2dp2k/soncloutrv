"""The SonTRV (soncloutrv) integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import runtime
from .const import (
    CONF_CONTROL_MODE,
    CONF_HEATING_TYPE,
    CONF_KA,
    CONF_KD,
    CONF_KI,
    CONF_KP,
    CONF_MIN_VALVE_UPDATE_INTERVAL,
    CONFIG_VERSION,
    DOMAIN,
    HEATING_TYPE_FLOOR,
    PLATFORMS,
    STATS_EPOCH,
    STRUCTURAL_KEYS,
)
from .controller import get_profile, is_legacy_default_gains

_LOGGER = logging.getLogger(__name__)


def _structural_snapshot(entry: ConfigEntry) -> dict[str, Any]:
    merged = {**entry.data, **entry.options}
    return {key: merged.get(key) for key in STRUCTURAL_KEYS}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SonTRV from a config entry."""
    runtime.domain_data(hass)
    await runtime.async_load_store(hass)

    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "entities": [],
        "structural": _structural_snapshot(entry),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changed: reload only for structural changes, else apply live."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(entry_data, dict):
        return
    snapshot = _structural_snapshot(entry)
    if snapshot != entry_data.get("structural"):
        _LOGGER.debug("SonTRV %s: structural option change - reloading", entry.title)
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    climate = entry_data.get("climate")
    if climate is not None:
        climate.async_options_updated()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await runtime.async_save_now(hass)
        domain = hass.data.get(DOMAIN, {})
        domain.pop(entry.entry_id, None)
        # Room level debug sensors are created once per room; allow them to be
        # re-created when the entry is set up again.
        conf = {**entry.data, **entry.options}
        room_key = conf.get("room_id") or conf.get("temp_sensor")
        for registry_key in ("room_pid_sensors", "room_temp_sensors"):
            owners = domain.get(f"{registry_key}_owner", {})
            if owners.get(room_key) == entry.entry_id:
                owners.pop(room_key, None)
                domain.get(registry_key, set()).discard(room_key)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    Guarantees for existing thermostats:
    * entity ids / unique ids stay the same,
    * manually tuned gains are kept (converted where the unit changed),
    * untouched legacy default gains are replaced by the new profile.
    """
    if entry.version > CONFIG_VERSION:
        _LOGGER.error("SonTRV entry %s has a newer version (%s) - downgrade not supported", entry.title, entry.version)
        return False

    if entry.version < CONFIG_VERSION:
        options: dict[str, Any] = {**entry.options}
        data: dict[str, Any] = {**entry.data}

        heating_type = options.get(CONF_HEATING_TYPE) or data.get(CONF_HEATING_TYPE) or HEATING_TYPE_FLOOR
        options[CONF_HEATING_TYPE] = heating_type
        profile = get_profile(heating_type)

        merged = {**data, **options}
        kp, ki, kd = merged.get(CONF_KP), merged.get(CONF_KI), merged.get(CONF_KD, 0.0)
        if kp is None or ki is None or is_legacy_default_gains(kp, ki, kd if kd is not None else 0.0):
            options[CONF_KP] = profile.kp
            options[CONF_KI] = round(profile.ki, 6)
            options[CONF_KD] = 0.0
            if merged.get(CONF_KA) in (None, 0, 0.0):
                options[CONF_KA] = 0.0
            _LOGGER.info("SonTRV %s: default gains replaced by the %s profile", entry.title, heating_type)
        else:
            # Custom tuning: the D-term unit changed from %·s/K to %/(K/h).
            try:
                kd_old = float(kd or 0.0)
            except (TypeError, ValueError):
                kd_old = 0.0
            options[CONF_KD] = round(kd_old / 3600.0, 4)
            _LOGGER.info("SonTRV %s: kept custom gains Kp=%s Ki=%s", entry.title, kp, ki)

        # The control mode used to live in entry.data (written by the select).
        if CONF_CONTROL_MODE in data and CONF_CONTROL_MODE not in options:
            options[CONF_CONTROL_MODE] = data[CONF_CONTROL_MODE]

        # The old climate never read the update interval option (it always
        # used 10 min). Drop the stored value so the profile default applies,
        # unless it was explicitly tuned away from the old default.
        interval = options.get(CONF_MIN_VALVE_UPDATE_INTERVAL)
        if interval in (10, 10.0):
            options.pop(CONF_MIN_VALVE_UPDATE_INTERVAL, None)

        options.pop("pid_defaults_v3_applied", None)
        options["stats_epoch"] = STATS_EPOCH

        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=CONFIG_VERSION
        )
        _LOGGER.info("SonTRV %s migrated to config version %s", entry.title, CONFIG_VERSION)

    return True
