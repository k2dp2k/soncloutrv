"""Shared runtime state for SonTRV (room controllers, persistence)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .controller import ControllerSettings, RoomController

if TYPE_CHECKING:
    from .climate import SonClouTRVClimate

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.controllers"
STORAGE_VERSION = 1
SAVE_DELAY = 120  # seconds


def domain_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return (and initialise) the integration wide data dict."""
    data = hass.data.setdefault(DOMAIN, {})
    data.setdefault("rooms", {})  # room_key -> list[climate]
    data.setdefault("controllers", {})  # controller key -> RoomController
    data.setdefault("room_pid_sensors", set())
    data.setdefault("room_temp_sensors", set())
    return data


async def async_load_store(hass: HomeAssistant) -> None:
    """Load persisted controller state once per HA run."""
    data = domain_data(hass)
    if "store" in data:
        return
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data["store"] = store
    try:
        loaded = await store.async_load()
    except Exception as err:  # corrupt file must never block the setup
        _LOGGER.warning("Could not load SonTRV controller state: %s", err)
        loaded = None
    data["stored_controllers"] = (loaded or {}).get("controllers", {}) if isinstance(loaded, dict) else {}


@callback
def _data_to_save(hass: HomeAssistant) -> dict[str, Any]:
    data = domain_data(hass)
    stored: dict[str, Any] = dict(data.get("stored_controllers", {}))
    for key, ctrl in data["controllers"].items():
        stored[key] = ctrl.as_dict()
    data["stored_controllers"] = stored
    return {"controllers": stored}


@callback
def schedule_save(hass: HomeAssistant) -> None:
    """Persist the learned controller state (debounced)."""
    data = domain_data(hass)
    store: Store | None = data.get("store")
    if store is None:
        return
    store.async_delay_save(lambda: _data_to_save(hass), SAVE_DELAY)


async def async_save_now(hass: HomeAssistant) -> None:
    """Persist immediately (on unload)."""
    data = domain_data(hass)
    store: Store | None = data.get("store")
    if store is None:
        return
    try:
        await store.async_save(_data_to_save(hass))
    except Exception as err:  # pragma: no cover - defensive
        _LOGGER.warning("Could not save SonTRV controller state: %s", err)


def controller_key(room_key: str, heating_type: str) -> str:
    """Key of the shared controller: one per room and heating type."""
    return f"{room_key}|{heating_type}"


@callback
def get_controller(
    hass: HomeAssistant, room_key: str, settings: ControllerSettings
) -> RoomController:
    """Return the shared controller for a room, creating/restoring it."""
    data = domain_data(hass)
    key = controller_key(room_key, settings.heating_type)
    ctrl: RoomController | None = data["controllers"].get(key)
    if ctrl is None:
        ctrl = RoomController(key, settings=settings)
        ctrl.restore(data.get("stored_controllers", {}).get(key))
        data["controllers"][key] = ctrl
    else:
        ctrl.apply_settings(settings)
    return ctrl


@callback
def register_climate(hass: HomeAssistant, room_key: str, entity: SonClouTRVClimate) -> None:
    """Register a climate entity in its room."""
    rooms = domain_data(hass)["rooms"]
    members = rooms.setdefault(room_key, [])
    if entity not in members:
        members.append(entity)


@callback
def unregister_climate(hass: HomeAssistant, room_key: str, entity: SonClouTRVClimate) -> None:
    """Remove a climate entity from its room."""
    rooms = domain_data(hass)["rooms"]
    members = rooms.get(room_key)
    if members and entity in members:
        members.remove(entity)
        if not members:
            rooms.pop(room_key, None)


def all_climates(hass: HomeAssistant) -> list[SonClouTRVClimate]:
    """Return all live SonTRV climate entities."""
    result: list[SonClouTRVClimate] = []
    for members in domain_data(hass)["rooms"].values():
        for entity in members:
            if entity not in result:
                result.append(entity)
    return result


def room_climates(hass: HomeAssistant, room_key: str) -> list[SonClouTRVClimate]:
    """Return the live SonTRV climate entities of a room."""
    return list(domain_data(hass)["rooms"].get(room_key, []))


def climate_for_entry(hass: HomeAssistant, entry_id: str) -> SonClouTRVClimate | None:
    """Return the climate entity that belongs to a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if isinstance(entry_data, dict):
        entity = entry_data.get("climate")
        if entity is not None:
            return entity
    return None
