"""The SonClouTRV integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_platform

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_KP,
    CONF_KI,
    CONF_KD,
    CONF_KA,
    DEFAULT_KP,
    DEFAULT_KI,
    DEFAULT_KD,
    DEFAULT_KA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SonClouTRV from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Per-config-entry storage (existing behaviour)
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "entities": [],  # Will store entity references
    }

    # Global room registry: groups SonTRV climates by external temperature sensor
    # so that we can later coordinate PID control per room.
    hass.data[DOMAIN].setdefault("rooms", {})

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as err:
        _LOGGER.error("Failed to set up SonClouTRV platforms: %s", err)
        return False

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to the latest schema.

    Ab Version 3 werden **alle** bestehenden Thermostate erneut auf die jeweils
    aktuellen PID-Standardwerte (DEFAULT_KP/KI/KD/KA) zurückgesetzt. Dadurch
    starten auch bereits konfigurierte Räume nach einem Update mit denselben
    Startwerten wie neue Installationen und können sich dann über den
    adaptiven I-Anteil wieder einregeln.
    """
    _LOGGER.debug(
        "Migrating config entry %s from version %s",
        config_entry.entry_id,
        config_entry.version,
    )

    if config_entry.version < 3:
        new_options = {**config_entry.options}
        new_options[CONF_KP] = DEFAULT_KP
        new_options[CONF_KI] = DEFAULT_KI
        new_options[CONF_KD] = DEFAULT_KD
        new_options[CONF_KA] = DEFAULT_KA

        # Setze die Entry-Version auf 3, damit diese Rücksetzung nur einmalig
        # beim Update passiert. Danach übernimmt die Laufzeit-Logik (adaptives Ki)
        # das Feintuning pro Raum.
        config_entry.version = 3
        hass.config_entries.async_update_entry(
            config_entry,
            options=new_options,
        )

        _LOGGER.info(
            "Reset SonClouTRV PID options to defaults Kp=%.1f, Ki=%.3f, Kd=%.1f, Ka=%.1f for entry %s (version %s)",
            DEFAULT_KP,
            DEFAULT_KI,
            DEFAULT_KD,
            DEFAULT_KA,
            config_entry.entry_id,
            config_entry.version,
        )

    _LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
