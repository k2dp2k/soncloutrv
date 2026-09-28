"""Diagnostics for SonTRV."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import runtime
from .const import VERSION


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    climate = runtime.climate_for_entry(hass, entry.entry_id)
    return {
        "version": VERSION,
        "entry": {
            "version": entry.version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "climate": None if climate is None else climate.diagnostics(),
    }
