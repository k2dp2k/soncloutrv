"""Integration tests: setup, migration of existing (v1.3.x) entries, TRV IO."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.components.climate import HVACMode
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.soncloutrv import runtime
from custom_components.soncloutrv.const import CONFIG_VERSION, DOMAIN, STATS_EPOCH
from custom_components.soncloutrv.controller import PROFILES

BASE = "heizung_wohnzimmer_fussboden"
TRV = f"climate.{BASE}"
OPEN = f"number.{BASE}_valve_opening_degree"
CLOSE = f"number.{BASE}_valve_closing_degree"
EXT = f"number.{BASE}_external_temperature_input"
SELECT = f"select.{BASE}_temperature_sensor_select"
LOCAL = f"sensor.{BASE}_local_temperature"
ROOM = "sensor.indoor_outdoor_meter_1932_temperatur"
OUTSIDE = "sensor.indoor_outdoor_meter_6362_temperatur"
WINDOW = "binary_sensor.fenster_essbereich_contact"
ENTRY_ID = "01KXKZB8MSD8CZREQPHRFAKJXP"

# data + options as they exist today for "trv_wohn" (v1.3.3)
V1_DATA = {
    "name": "trv_wohn",
    "valve_entity": TRV,
    "temp_sensor": ROOM,
    "room_id": "Wohnzimmer",
    "min_temp": 6.0,
    "max_temp": 25.0,
    "target_temp": 21.5,
    "valve_opening_step": "2",
}
V1_OPTIONS = {
    "outside_temp_sensor": OUTSIDE,
    "temp_sensor": ROOM,
    "room_logging_enabled": False,
    "room_log_file": "sontrv_room_log.csv",
    "window_drop_threshold": 0.8,
    "window_stable_band": 0.3,
    "window_max_freeze": 10800,
    "window_sensors": [WINDOW],
    "window_sensor_scope": "local",
    "min_temp": 6,
    "max_temp": 25,
    "room_id": "Wohnzimmer",
    "target_temp": 21.5,
    "valve_opening_step": "2",
    "kp": 10.0,
    "ki": 0.005,
    "kd": 0.0,
    "ka": 0.0,
    "pid_defaults_v3_applied": True,
}


class FakeTRV:
    """Records service calls and mirrors them into the TRV states."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_numbers = False

    def setup_states(self, room: float = 20.5) -> None:
        h = self.hass
        h.states.async_set(
            TRV,
            "off",
            {"hvac_modes": ["off", "auto", "heat"], "temperature": 7, "current_temperature": room},
        )
        h.states.async_set(OPEN, "0")
        h.states.async_set(CLOSE, "100")
        h.states.async_set(EXT, str(room))
        h.states.async_set(SELECT, "external")
        h.states.async_set(LOCAL, "22.0", {"device_class": "temperature"})
        h.states.async_set(ROOM, str(room), {"device_class": "temperature", "unit_of_measurement": "°C"})
        h.states.async_set(OUTSIDE, "3.0", {"device_class": "temperature"})
        h.states.async_set(WINDOW, "off", {"device_class": "window"})

    def install(self) -> None:
        """Override services AFTER the integration registered its own."""
        h = self.hass
        original = {
            ("climate", "set_hvac_mode"): h.services._services["climate"]["set_hvac_mode"],
            ("climate", "set_temperature"): h.services._services["climate"]["set_temperature"],
            ("number", "set_value"): h.services._services["number"]["set_value"],
            ("select", "select_option"): h.services._services["select"]["select_option"],
        }
        self._original = original

        async def handler(call: ServiceCall) -> None:
            entity_id = call.data.get("entity_id")
            ids = entity_id if isinstance(entity_id, list) else [entity_id]
            key = (call.domain, call.service)
            if any(str(i).startswith(f"{call.domain}.trv_") for i in ids):
                # our own entities -> original implementation
                await original[key].job.target(call)
                return
            self.calls.append((call.domain, call.service, dict(call.data)))
            for eid in ids:
                state = h.states.get(eid)
                attrs = dict(state.attributes) if state else {}
                if key == ("number", "set_value"):
                    if self.fail_numbers:
                        raise RuntimeError("zigbee timeout")
                    h.states.async_set(eid, str(int(float(call.data["value"]))) if eid in (OPEN, CLOSE) else str(call.data["value"]), attrs)
                elif key == ("climate", "set_hvac_mode"):
                    h.states.async_set(eid, call.data["hvac_mode"], attrs)
                elif key == ("climate", "set_temperature"):
                    attrs["temperature"] = call.data["temperature"]
                    h.states.async_set(eid, state.state, attrs)
                elif key == ("select", "select_option"):
                    h.states.async_set(eid, call.data["option"], attrs)

        for domain, service in original:
            h.services.async_register(domain, service, handler)

    def last(self, domain: str, service: str, entity_id: str) -> dict[str, Any] | None:
        for d, s, data in reversed(self.calls):
            if d == domain and s == service and data.get("entity_id") == entity_id:
                return data
        return None


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations, freezer):
    # Fixed weekday morning: tests advance the clock by hours and must not run
    # into the weekly valve exercise (Sunday 11:00), which pauses the control.
    freezer.move_to("2026-10-14 06:00:00+00:00")
    yield


async def _setup(
    hass: HomeAssistant, *, version: int = 1, data=None, options=None, window: str = "off"
) -> tuple[MockConfigEntry, FakeTRV]:
    trv = FakeTRV(hass)
    trv.setup_states()
    hass.states.async_set(WINDOW, window, {"device_class": "window"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="trv_wohn",
        data=data or V1_DATA,
        options=options if options is not None else V1_OPTIONS,
        version=version,
        entry_id=ENTRY_ID,
        unique_id=TRV,
    )
    entry.add_to_hass(hass)
    # Entities that already exist in the user's registry keep their ids.
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "select", DOMAIN, f"{DOMAIN}_{ENTRY_ID}_control_mode",
        suggested_object_id="trv_wohn_steuermodus", config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    trv.install()
    return entry, trv


async def _run_cycle(hass: HomeAssistant, minutes: float = 3) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await hass.async_block_till_done()


async def _wait(hass: HomeAssistant, freezer, seconds: float) -> None:
    """Advance the clock (states and timers) by ``seconds``."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _set_window(hass: HomeAssistant, freezer, state: str, entity_id: str = WINDOW) -> None:
    hass.states.async_set(entity_id, state, {"device_class": "window"})
    await hass.async_block_till_done()
    if state == "on":
        await _wait(hass, freezer, 130)  # longer than the default open delay


async def test_migration_from_v1_keeps_entities(hass: HomeAssistant, mqtt_mock) -> None:
    entry, _ = await _setup(hass)
    assert entry.version == CONFIG_VERSION
    floor = PROFILES["floor"]
    assert entry.options["kp"] == floor.kp
    assert entry.options["ki"] == pytest.approx(floor.ki, rel=1e-3)
    assert entry.options["heating_type"] == "floor"
    assert entry.options["stats_epoch"] == STATS_EPOCH
    assert "pid_defaults_v3_applied" not in entry.options
    # user settings survive
    assert entry.options["window_sensors"] == [WINDOW]
    assert entry.options["outside_temp_sensor"] == OUTSIDE

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("climate", DOMAIN, f"{DOMAIN}_{ENTRY_ID}") == "climate.trv_wohn"
    for eid in (
        "number.trv_wohn_pid_p_gain_kp",
        "number.trv_wohn_hysterese",
        "select.trv_wohn_steuermodus",
        "switch.trv_wohn_verkalkungsschutz",
        "button.trv_wohn_ventil_durchbewegen",
        "sensor.trv_wohn_ventilposition",
    ):
        assert hass.states.get(eid) is not None, eid
    assert hass.states.get("number.trv_wohn_pid_p_gain_kp").state == str(floor.kp)
    heating_type = registry.async_get_entity_id("select", DOMAIN, f"{DOMAIN}_{ENTRY_ID}_heating_type")
    assert hass.states.get(heating_type).state == "floor"


async def test_migration_keeps_custom_gains(hass: HomeAssistant, mqtt_mock) -> None:
    options = {**V1_OPTIONS, "kp": 15.0, "ki": 0.002, "kd": 360.0, "min_valve_update_interval": 20}
    entry, _ = await _setup(hass, options=options)
    assert entry.options["kp"] == 15.0
    assert entry.options["ki"] == 0.002
    assert entry.options["kd"] == pytest.approx(0.1)
    assert entry.options["min_valve_update_interval"] == 20
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._min_valve_update_interval == 1200


async def test_control_writes_valve_and_heat_mode(hass: HomeAssistant, mqtt_mock) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    mode = trv.last("climate", "set_hvac_mode", TRV)
    assert mode is not None and mode["hvac_mode"] == "heat"
    opening = trv.last("number", "set_value", OPEN)
    closing = trv.last("number", "set_value", CLOSE)
    assert opening is not None and closing is not None
    assert 0 < opening["value"] <= 40
    assert opening["value"] + closing["value"] == 100
    # TRV set-point in 0.5 K steps
    assert trv.last("climate", "set_temperature", TRV)["temperature"] == 21.5
    state = hass.states.get("climate.trv_wohn")
    assert state.state == "heat"
    assert state.attributes["valve_position"] == opening["value"]
    assert state.attributes["hvac_action"] == "heating"

    # A second cycle with unchanged conditions must not rewrite the valve.
    writes = len([c for c in trv.calls if c[2].get("entity_id") == OPEN])
    await _run_cycle(hass, 20)
    assert len([c for c in trv.calls if c[2].get("entity_id") == OPEN]) == writes


async def test_hvac_off_closes_valve_then_trv_off(hass: HomeAssistant, mqtt_mock) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    await climate.async_set_hvac_mode(HVACMode.OFF)
    await hass.async_block_till_done()
    assert trv.last("number", "set_value", OPEN)["value"] == 0
    assert trv.last("number", "set_value", CLOSE)["value"] == 100
    assert hass.states.get(TRV).state == "off"
    # back on: TRV must be switched to heat again (bug in v1.x)
    await climate.async_set_hvac_mode(HVACMode.HEAT)
    await hass.async_block_till_done()
    assert hass.states.get(TRV).state == "heat"


async def test_number_change_is_live_without_reload(hass: HomeAssistant, mqtt_mock) -> None:
    entry, _ = await _setup(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.trv_wohn_pid_p_gain_kp", "value": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert runtime.climate_for_entry(hass, ENTRY_ID) is climate  # no reload
    assert climate._kp == 30
    assert entry.options["kp"] == 30


async def test_control_mode_select_is_applied(hass: HomeAssistant, mqtt_mock) -> None:
    entry, trv = await _setup(hass)
    await _run_cycle(hass)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.trv_wohn_steuermodus", "option": "binary"}, blocking=True
    )
    await hass.async_block_till_done()
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._control_mode == "binary"
    assert entry.options["control_mode"] == "binary"
    # binary opens fully (to the step) because the room is 1 K too cold
    assert trv.last("number", "set_value", OPEN)["value"] == 40


async def test_window_sensor_closes_and_resumes(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    before = trv.last("number", "set_value", OPEN)["value"]
    assert before > 0
    await _set_window(hass, freezer, "on")
    assert trv.last("number", "set_value", OPEN)["value"] == 0
    assert hass.states.get("climate.trv_wohn").attributes["window_open"] is True
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    integral_before = climate._controller.integral
    await _set_window(hass, freezer, "off")
    assert hass.states.get("climate.trv_wohn").attributes["window_open"] is False
    # back to the opening from before the window
    assert trv.last("number", "set_value", OPEN)["value"] == before
    # learned state is kept over the window event
    assert climate._controller.integral == pytest.approx(integral_before, abs=0.5)


async def test_short_door_opening_is_ignored(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Front door: a few seconds open must not move the valve."""
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    writes = len([c for c in trv.calls if c[2].get("entity_id") == OPEN])
    for _ in range(5):
        hass.states.async_set(WINDOW, "on", {"device_class": "window"})
        await _wait(hass, freezer, 5)
        hass.states.async_set(WINDOW, "off", {"device_class": "window"})
        await _wait(hass, freezer, 60)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._window_freeze_active is False
    assert len([c for c in trv.calls if c[2].get("entity_id") == OPEN]) == writes


async def test_bouncing_contact_is_ignored(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Door ajar: the contact toggles every few seconds (seen on the office door)."""
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    for i in range(60):  # 60 toggles in ~4 min
        hass.states.async_set(WINDOW, "on" if i % 2 == 0 else "off", {"device_class": "window"})
        await _wait(hass, freezer, 4)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._window_freeze_active is False
    assert trv.last("number", "set_value", OPEN)["value"] > 0


async def test_window_recovery_holds_valve_until_air_recovered(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """After airing, the floor circuit neither opens wide nor learns."""
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    before = trv.last("number", "set_value", OPEN)["value"]
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    integral = climate._controller.integral
    await _set_window(hass, freezer, "on")
    hass.states.async_set(ROOM, "18.5", {"device_class": "temperature"})  # cold air
    await _wait(hass, freezer, 600)
    await _set_window(hass, freezer, "off")
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["post_window_soft_active"] is True
    assert trv.last("number", "set_value", OPEN)["value"] == before
    # 2 K below target, but the valve stays where it was during the recovery
    await _wait(hass, freezer, 16 * 60)
    assert trv.last("number", "set_value", OPEN)["value"] == before
    assert climate._controller.integral == pytest.approx(integral, abs=0.01)
    # the air comes back from the warm screed -> normal control again
    hass.states.async_set(ROOM, "20.4", {"device_class": "temperature"})
    await _wait(hass, freezer, 16 * 60)
    assert hass.states.get("climate.trv_wohn").attributes["post_window_soft_active"] is False


async def test_room_mates_end_window_freeze_together(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Open living room: wohn + kuche share sensors and controller."""
    _, trv = await _setup(hass)
    base2 = "heizung_kuche_fussboden"
    hass.states.async_set(f"climate.{base2}", "off", {"hvac_modes": ["off", "auto", "heat"], "temperature": 7})
    hass.states.async_set(f"number.{base2}_valve_opening_degree", "0")
    hass.states.async_set(f"number.{base2}_valve_closing_degree", "100")
    entry2 = MockConfigEntry(
        domain=DOMAIN, title="trv_kuche", version=CONFIG_VERSION, entry_id="01KXKZ7SKVSYSTS33R44NB22P1",
        unique_id=f"climate.{base2}", data={**V1_DATA, "name": "trv_kuche", "valve_entity": f"climate.{base2}"},
        options={**V1_OPTIONS, "kp": 25.0, "ki": 0.001736},
    )
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    await _run_cycle(hass)
    c1 = runtime.climate_for_entry(hass, ENTRY_ID)
    c2 = runtime.climate_for_entry(hass, entry2.entry_id)
    await _set_window(hass, freezer, "on")
    assert c1._window_freeze_active and c2._window_freeze_active
    hass.states.async_set(ROOM, "18.5", {"device_class": "temperature"})
    await _wait(hass, freezer, 300)
    await _set_window(hass, freezer, "off")
    assert not c1._window_freeze_active and not c2._window_freeze_active
    assert c1._controller is c2._controller
    assert c1._controller.frozen is False
    # neither circuit reacted to the cold air with a wide opening
    assert c1._valve_position <= 40 and c2._valve_position <= 40
    assert c1._last_result is None or c1._last_result.demand < 80


async def test_new_z2m_sensor_select_options(hass: HomeAssistant, mqtt_mock) -> None:
    """Zigbee2MQTT 2.x: remote_temperature instead of external, state unknown."""
    trv = FakeTRV(hass)
    trv.setup_states()
    options = ["local_temperature", "remote_temperature", "remote_source_offline"]
    hass.states.async_set(SELECT, "unknown", {"options": options})
    entry, _ = await _setup(hass)
    hass.states.async_set(SELECT, "unknown", {"options": options})
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._external_sensor_option(hass.states.get(SELECT)) == "remote_temperature"
    assert climate._external_sensor_option(None) is None
    hass.states.async_set(SELECT, "unknown", {"options": ["internal", "external", "external_2"]})
    assert climate._external_sensor_option(hass.states.get(SELECT)) == "external"
    hass.states.async_set(SELECT, "unknown", {"options": ["local_temperature"]})
    assert climate._external_sensor_option(hass.states.get(SELECT)) is None


async def test_sensor_select_is_set_once_per_hour(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    options = ["local_temperature", "remote_temperature", "remote_source_offline"]
    _, trv = await _setup(hass)
    hass.states.async_set(SELECT, "unknown", {"options": options})
    trv.calls.clear()
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    climate._last_select_try_ts = None
    climate._last_ext_sync_ts = None
    await _wait(hass, freezer, 16 * 60)
    tries = [c for c in trv.calls if c[2].get("entity_id") == SELECT]
    assert tries and tries[-1][2]["option"] == "remote_temperature"
    # the device keeps rejecting it -> no new try within the hour
    hass.states.async_set(SELECT, "unknown", {"options": options})
    for _ in range(3):
        hass.states.async_set(ROOM, str(20.0 + _ * 0.2), {"device_class": "temperature"})
        await _wait(hass, freezer, 15 * 60)
    assert len([c for c in trv.calls if c[2].get("entity_id") == SELECT]) == len(tries)


async def test_trv_own_window_detection_is_switched_off(hass: HomeAssistant, mqtt_mock) -> None:
    hass.states.async_set(f"switch.{BASE}_open_window", "on")
    switched: list[str] = []

    async def turn_off(call: ServiceCall) -> None:
        switched.append(call.data["entity_id"])
        hass.states.async_set(call.data["entity_id"], "off")

    _, trv = await _setup(hass)
    hass.services.async_register("switch", "turn_off", turn_off)
    await _run_cycle(hass)
    assert switched == [f"switch.{BASE}_open_window"]


async def test_window_open_before_start_is_respected(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """A window that is already open at (re)start never sends an event."""
    _, trv = await _setup(hass, window="on")
    await _wait(hass, freezer, 130)
    await _run_cycle(hass)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["window_open"] is True
    assert state.attributes["valve_position"] == 0
    # the freeze may have written 0 before the fake TRV was installed; in no
    # case is a positive opening written
    assert all(c[2]["value"] == 0 for c in trv.calls if c[2].get("entity_id") == OPEN)
    await _set_window(hass, freezer, "off")
    assert hass.states.get("climate.trv_wohn").attributes["window_open"] is False
    await _run_cycle(hass, 16)
    assert trv.last("number", "set_value", OPEN)["value"] > 0


async def test_missed_window_event_is_caught_by_control_cycle(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    # simulate a missed event: set the state without the listener seeing it
    for remove in climate._remove_listeners:
        remove()
    climate._remove_listeners.clear()
    hass.states.async_set(WINDOW, "on", {"device_class": "window"})
    await hass.async_block_till_done()
    assert climate._window_freeze_active is False
    freezer.tick(timedelta(minutes=20))
    await _run_cycle(hass, 0)
    assert climate._window_freeze_active is True
    assert trv.last("number", "set_value", OPEN)["value"] == 0


async def test_silent_sensor_stays_trusted_when_plausible(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Sensors reporting on change only are silent in a stable room."""
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._local_offset == pytest.approx(-1.5)
    freezer.tick(timedelta(hours=5))  # > sensor_timeout (4 h), room sensor silent
    hass.states.async_set(LOCAL, "22.1", {"device_class": "temperature"}, force_update=True)
    await _wait(hass, freezer, 16 * 60)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["temperature_source"] == "sensor"
    assert state.attributes["sensor_stale"] is True
    assert state.attributes["current_temperature"] == 20.5
    # the TRV sensor says the room moved by 2 K -> the silent sensor is stale
    hass.states.async_set(LOCAL, "24.0", {"device_class": "temperature"}, force_update=True)
    await _wait(hass, freezer, 16 * 60)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["temperature_source"] == "trv_sensor"
    assert state.attributes["current_temperature"] == pytest.approx(22.5, abs=0.05)
    # a fresh report restores the sensor as the source
    hass.states.async_set(ROOM, "22.4", {"device_class": "temperature"}, force_update=True)
    await _wait(hass, freezer, 16 * 60)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["temperature_source"] == "sensor"
    assert state.attributes["sensor_stale"] is False


async def _setup_bath(hass: HomeAssistant, trv: FakeTRV, *, role: str | None = None) -> tuple[MockConfigEntry, MockConfigEntry, str]:
    """Floor loop (SONOFF) + towel radiator (Bosch) sharing room 'Bad'."""
    base = "handtuch_heizung_bad"
    hass.states.async_set(
        f"climate.{base}", "off", {"hvac_modes": ["off", "heat", "auto"], "temperature": 5, "current_temperature": 20.5}
    )
    hass.states.async_set(f"number.{base}_pi_heating_demand", "0", {"min": 0, "max": 100})
    hass.states.async_set(f"number.{base}_remote_temperature", "0", {"min": 0, "max": 35})
    hass.states.async_set(f"sensor.{base}_local_temperature", "20.6", {"device_class": "temperature"})
    floor = MockConfigEntry(
        domain=DOMAIN, title="trv_bad", version=CONFIG_VERSION, entry_id="01KXKYXHTQQ1XB0FA9SVA70TY7", unique_id=TRV,
        data={**V1_DATA, "name": "trv_bad", "room_id": "Bad"},
        options={**V1_OPTIONS, "room_id": "Bad", "window_sensors": [], "kp": 25.0, "ki": 0.001736},
    )
    options = {**V1_OPTIONS, "room_id": "Bad", "heating_type": "radiator", "valve_opening_step": "5", "window_sensors": [],
               "kp": 25.0, "ki": 0.010417}
    if role is not None:
        options["heater_role"] = role
    towel = MockConfigEntry(
        domain=DOMAIN, title="trv_handtuch", version=CONFIG_VERSION, entry_id="01KXKZ53FC4NMFSC1YXJMXC9EN",
        unique_id=f"climate.{base}", data={**V1_DATA, "name": "trv_handtuch", "valve_entity": f"climate.{base}", "room_id": "Bad"},
        options=options,
    )
    for entry in (floor, towel):
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    trv.install()
    return floor, towel, base


async def test_radiator_next_to_floor_loop_assists_only(hass: HomeAssistant, mqtt_mock) -> None:
    trv = FakeTRV(hass)
    trv.setup_states(room=20.5)
    floor, towel, base = await _setup_bath(hass, trv)
    await _run_cycle(hass)
    f = runtime.climate_for_entry(hass, floor.entry_id)
    t = runtime.climate_for_entry(hass, towel.entry_id)
    assert f.effective_role == "primary" and t.effective_role == "assist"
    assert f._controller is not t._controller  # separate learning per heating type
    # 1 K below target: floor modulates, the radiator switches fully on
    assert 0 < trv.last("number", "set_value", OPEN)["value"] <= 40
    assert trv.last("number", "set_value", f"number.{base}_pi_heating_demand")["value"] == 100
    # the Bosch's own regulation must agree: fully open -> maximum set-point
    assert hass.states.get(f"climate.{base}").attributes["temperature"] == 30.0
    assert hass.states.get("climate.trv_handtuch").attributes["control_reason"] == "assist"
    # back within 0.1 K of the target: the radiator goes off, the floor keeps its demand
    hass.states.async_set(ROOM, "21.45", {"device_class": "temperature"})
    await hass.async_block_till_done()
    await _run_cycle(hass, 6)
    assert trv.last("number", "set_value", f"number.{base}_pi_heating_demand")["value"] == 0
    # shut -> minimum set-point, otherwise the Bosch heats on its own after ~15 min
    assert hass.states.get(f"climate.{base}").attributes["temperature"] == 5.0
    assert trv.last("number", "set_value", OPEN)["value"] > 0
    assert hass.states.get("climate.trv_handtuch").attributes["heater_role"] == "assist"
    # the assist heater never learns an integral of its own
    assert t._controller.integral == 0.0


async def test_bath_window_unfreezes_both_controllers(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Floor and towel radiator share the room but not the controller."""
    trv = FakeTRV(hass)
    trv.setup_states(room=20.5)
    hass.states.async_set("binary_sensor.fenster_bad", "off", {"device_class": "window"})
    floor, towel, base = await _setup_bath(hass, trv)
    for entry in (floor, towel):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "window_sensors": ["binary_sensor.fenster_bad"]}
        )
    await hass.async_block_till_done()
    await _run_cycle(hass)
    f = runtime.climate_for_entry(hass, floor.entry_id)
    t = runtime.climate_for_entry(hass, towel.entry_id)
    await _set_window(hass, freezer, "on", "binary_sensor.fenster_bad")
    assert f._window_freeze_active and t._window_freeze_active
    await _set_window(hass, freezer, "off", "binary_sensor.fenster_bad")
    assert f._controller.frozen is False
    assert t._controller.frozen is False


async def test_heater_role_can_be_forced_primary(hass: HomeAssistant, mqtt_mock) -> None:
    trv = FakeTRV(hass)
    trv.setup_states(room=20.5)
    _, towel, base = await _setup_bath(hass, trv, role="primary")
    await _run_cycle(hass)
    t = runtime.climate_for_entry(hass, towel.entry_id)
    assert t.effective_role == "primary"
    demand = trv.last("number", "set_value", f"number.{base}_pi_heating_demand")["value"]
    assert 0 < demand < 100  # PI, not two-point
    # in between the Bosch regulates to the room target itself
    assert hass.states.get(f"climate.{base}").attributes["temperature"] == 21.5


async def test_unstable_trv_sensor_is_not_used_as_fallback(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """A head on the return pipe follows the water, not the room."""
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._trv_sensor_trusted is True
    # the valve opens and closes: the TRV sensor swings by 10 K
    for i in range(40):
        hass.states.async_set(LOCAL, "32.0" if i % 2 else "22.0", {"device_class": "temperature"})
        hass.states.async_set(ROOM, str(20.5 + (i % 3) * 0.1), {"device_class": "temperature"}, force_update=True)
        await hass.async_block_till_done()
    assert climate._trv_sensor_trusted is False
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["trv_sensor_trusted"] is False
    # room sensor dies -> no fallback to the pipe temperature, hold instead
    hass.states.async_set(ROOM, "unavailable")
    freezer.tick(timedelta(minutes=16))
    hass.states.async_set(LOCAL, "32.0", {"device_class": "temperature"}, force_update=True)
    await _run_cycle(hass, 0.1)
    assert hass.states.get("climate.trv_wohn").attributes["temperature_source"] == "hold"


async def test_target_from_options_is_applied_live(hass: HomeAssistant, mqtt_mock) -> None:
    entry, _ = await _setup(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate.target_temperature == 21.5
    hass.config_entries.async_update_entry(entry, options={**entry.options, "target_temp": 20.0})
    await hass.async_block_till_done()
    assert runtime.climate_for_entry(hass, ENTRY_ID) is climate  # no reload
    assert climate.target_temperature == 20.0
    # a target changed in the options together with a structural change
    # (reload) wins over the restored state
    await climate.async_set_temperature(temperature=21.0)
    hass.states.async_set("sensor.other", "20.0", {"device_class": "temperature"})
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "target_temp": 19.0, "temp_sensor": "sensor.other"}
    )
    await hass.async_block_till_done()
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate.target_temperature == 19.0
    # a plain reload keeps the value set by the user
    await climate.async_set_temperature(temperature=22.5)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert runtime.climate_for_entry(hass, ENTRY_ID).target_temperature == 22.5
    # unrelated option changes do not touch a target set by the user meanwhile
    await climate.async_set_temperature(temperature=22.0)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "kp": 30.0})
    await hass.async_block_till_done()
    assert climate.target_temperature == 22.0


def test_room_log_rotation(tmp_path, monkeypatch) -> None:
    from custom_components.soncloutrv import climate as climate_module

    path = str(tmp_path / "log.csv")
    header = ",".join(climate_module.SonClouTRVClimate._LOG_HEADER)
    monkeypatch.setattr(climate_module, "ROOM_LOG_MAX_BYTES", len(header) + 40)
    row = ["2026-01-01T00:00:00+00:00", "r", "climate.x"] + [0] * (len(climate_module.SonClouTRVClimate._LOG_HEADER) - 3)
    for _ in range(4):
        climate_module.SonClouTRVClimate._append_log_row(path, row)
    assert (tmp_path / "log.csv.1").is_file()
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert lines[0] == header and 1 < len(lines) < 4


async def test_sensor_failure_falls_back_to_trv_sensor(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._local_offset == pytest.approx(-1.5)
    hass.states.async_set(ROOM, "unavailable")
    freezer.tick(timedelta(minutes=16))
    hass.states.async_set(LOCAL, "22.1", {"device_class": "temperature"}, force_update=True)
    await _run_cycle(hass, 0.1)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["temperature_source"] == "trv_sensor"
    assert state.attributes["current_temperature"] == pytest.approx(20.6, abs=0.05)


async def test_failed_valve_write_is_retried(hass: HomeAssistant, mqtt_mock) -> None:
    _, trv = await _setup(hass)
    trv.fail_numbers = True
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert climate._valve_write_errors >= 1
    assert climate._last_written is None
    trv.fail_numbers = False
    await _run_cycle(hass, 20)
    assert climate._last_written is not None and climate._last_written > 0


async def test_stats_from_old_epoch_are_reset(hass: HomeAssistant, mqtt_mock) -> None:
    mock_restore_cache(
        hass,
        [
            State("sensor.trv_wohn_geschatzte_heizenergie", "1506.974", {}),
            State("sensor.trv_wohn_ventil_gesamtlaufzeit", "30138.6", {}),
        ],
    )
    await _setup(hass)
    assert float(hass.states.get("sensor.trv_wohn_geschatzte_heizenergie").state) < 1
    assert float(hass.states.get("sensor.trv_wohn_ventil_gesamtlaufzeit").state) < 1
    energy = hass.states.get("sensor.trv_wohn_geschatzte_heizenergie")
    assert energy.attributes["source"] == OPEN


async def test_learning_persists_over_reload(hass: HomeAssistant, mqtt_mock) -> None:
    entry, _ = await _setup(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    climate._controller.integral = 33.0
    climate._controller.ff_coeff = 1.2
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    new_climate = runtime.climate_for_entry(hass, ENTRY_ID)
    assert new_climate is not climate
    assert new_climate._controller.integral == 33.0
    assert new_climate._controller.ff_coeff == 1.2
    # room sensors are re-created after the reload
    assert hass.states.get("sensor.trv_wohn_raum_heizbedarf") is not None


async def test_insight_sensors_and_model_persistence(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    entry, trv = await _setup(hass)
    for i in range(110):  # > 1 day of control cycles
        hass.states.async_set(ROOM, str(round(20.5 + 0.1 * (i % 3), 1)), {"device_class": "temperature"})
        await _wait(hass, freezer, 15 * 60)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["model_updates"] > 96
    assert state.attributes["model_ready"] is True
    assert set(state.attributes["model_forecast"]) == {"hold", "off", "full"}
    assert state.attributes["comfort_samples"] > 0
    assert state.attributes["model_skill_samples"] > 0
    # forecast curves and the confidence dict are not written to the recorder
    assert {"model_forecast", "model_confidence"} <= climate._unrecorded_attributes
    for object_id in (
        "regelgute_24h",
        "gelernte_wetterabhangigkeit",
        "raummodell_zeitkonstante",
        "raummodell_heizleistung",
        "raummodell_fremdwarme",
        "raummodell_prognose_3h",
        "raummodell_vorhersage_vorteil",
    ):
        sensor = hass.states.get(f"sensor.trv_wohn_{object_id}")
        assert sensor is not None, object_id
        assert sensor.attributes.get("state_class") == "measurement", object_id
    assert hass.states.get("sensor.trv_wohn_raummodell_zeitkonstante").state not in ("unknown", "unavailable")
    updates = climate._controller.model.updates
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert runtime.climate_for_entry(hass, ENTRY_ID)._controller.model.updates == updates


async def test_structural_option_change_reloads(hass: HomeAssistant, mqtt_mock) -> None:
    entry, _ = await _setup(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    hass.states.async_set("sensor.other", "20.0", {"device_class": "temperature"})
    hass.config_entries.async_update_entry(entry, options={**entry.options, "temp_sensor": "sensor.other"})
    await hass.async_block_till_done()
    assert runtime.climate_for_entry(hass, ENTRY_ID) is not climate


async def test_exercise_opens_and_closes(hass: HomeAssistant, mqtt_mock) -> None:
    _, trv = await _setup(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    await climate.async_set_hvac_mode(HVACMode.OFF)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.trv_wohn_ventil_durchbewegen"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(TRV).state == "heat"  # needed to move the valve
    assert trv.last("number", "set_value", OPEN)["value"] == 100
    await _run_cycle(hass, 5.1)
    assert trv.last("number", "set_value", OPEN)["value"] == 0
    await _run_cycle(hass, 5.1)
    assert climate._is_exercising is False
    # heating was off before -> back to off
    assert hass.states.get(TRV).state == "off"


async def test_no_temperature_holds_learned_demand(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    climate._controller.integral = 25.0
    integral = climate._controller.integral
    hass.states.async_set(ROOM, "unavailable")
    hass.states.async_set(LOCAL, "unavailable")
    freezer.tick(timedelta(minutes=16))
    await _run_cycle(hass, 0.1)
    state = hass.states.get("climate.trv_wohn")
    assert state.attributes["temperature_source"] == "hold"
    assert state.attributes["room_demand"] == pytest.approx(25.0, abs=0.5)
    assert climate._controller.integral == integral  # no learning on stale data
    assert trv.last("number", "set_value", OPEN)["value"] == 10


async def test_global_window_scope_keeps_all_frozen(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    options = {**V1_OPTIONS, "window_sensor_scope": "all"}
    _, trv = await _setup(hass, options=options)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    await _set_window(hass, freezer, "on")
    assert climate._window_freeze_active
    await _set_window(hass, freezer, "off")
    assert not climate._window_freeze_active


async def test_two_circuits_share_room_controller(hass: HomeAssistant, mqtt_mock) -> None:
    """trv_wohn and trv_kuche share room 'Wohnzimmer' and the room sensor."""
    entry, trv = await _setup(hass)
    base2 = "heizung_kuche_fussboden"
    hass.states.async_set(f"climate.{base2}", "off", {"hvac_modes": ["off", "auto", "heat"], "temperature": 7})
    hass.states.async_set(f"number.{base2}_valve_opening_degree", "0")
    hass.states.async_set(f"number.{base2}_valve_closing_degree", "100")
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        title="trv_kuche",
        data={**V1_DATA, "name": "trv_kuche", "valve_entity": f"climate.{base2}", "control_mode": "pid"},
        options={**V1_OPTIONS, "kp": 12.0, "ki": 0.001},  # custom tuning
        version=1,
        entry_id="01KXKZ7SKVSYSTS33R44NB22P1",
        unique_id=f"climate.{base2}",
    )
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    c1 = runtime.climate_for_entry(hass, ENTRY_ID)
    c2 = runtime.climate_for_entry(hass, entry2.entry_id)
    assert c1._controller is c2._controller
    assert entry2.options["kp"] == 12.0 and entry2.options["control_mode"] == "pid"
    assert set(runtime.room_climates(hass, "Wohnzimmer")) == {c1, c2}
    # tuning one circuit only is flagged (the controller is shared)
    from unittest.mock import patch
    from custom_components.soncloutrv import climate as climate_module

    with patch.object(climate_module._LOGGER, "warning") as warning:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.trv_wohn_pid_p_gain_kp", "value": 30}, blocking=True
        )
        await hass.async_block_till_done()
    assert any("share the room controller" in str(call.args[0]) for call in warning.call_args_list)
    # unloading one circuit keeps the other working
    assert await hass.config_entries.async_unload(entry2.entry_id)
    await hass.async_block_till_done()
    assert runtime.room_climates(hass, "Wohnzimmer") == [c1]


async def test_bosch_bth_ra_driver(hass: HomeAssistant, mqtt_mock, freezer) -> None:
    """Bosch Radiator Thermostat II: pi_heating_demand + remote_temperature."""
    base = "handtuch_heizung_bad"
    trv = FakeTRV(hass)
    trv.setup_states()
    hass.states.async_set(
        f"climate.{base}", "off", {"hvac_modes": ["off", "heat", "auto"], "temperature": 5, "current_temperature": 23.8}
    )
    hass.states.async_set(f"number.{base}_pi_heating_demand", "0", {"min": 0, "max": 100})
    hass.states.async_set(f"number.{base}_remote_temperature", "0", {"min": 0, "max": 35})
    hass.states.async_set(f"sensor.{base}_local_temperature", "23.8", {"device_class": "temperature"})
    hass.states.async_set(f"button.{base}_valve_adapt_process", "unknown")
    hass.states.async_set(f"select.{base}_operating_mode", "pause", {"options": ["schedule", "manual", "pause"]})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="trv_handtuch",
        data={**V1_DATA, "name": "trv_handtuch", "valve_entity": f"climate.{base}"},
        options={**V1_OPTIONS, "heating_type": "radiator", "valve_opening_step": "5", "window_sensors": []},
        version=CONFIG_VERSION,
        entry_id="01KXKZ53FC4NMFSC1YXJMXC9EN",
        unique_id=f"climate.{base}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    trv.install()
    pressed: list[str] = []

    async def press(call: ServiceCall) -> None:
        pressed.append(call.data["entity_id"])

    hass.services.async_register("button", "press", press)

    climate = runtime.climate_for_entry(hass, entry.entry_id)
    assert climate.trv_driver == "bosch_bth_ra"
    await _run_cycle(hass)
    assert hass.states.get(f"climate.{base}").state == "heat"
    # the Bosch is taken out of "pause" so it accepts the heating demand
    assert trv.last("select", "select_option", f"select.{base}_operating_mode")["option"] == "manual"
    demand = trv.last("number", "set_value", f"number.{base}_pi_heating_demand")
    assert demand is not None and 0 < demand["value"] <= 100
    # no SONOFF entities are written for this device
    assert not [c for c in trv.calls if "valve_closing_degree" in str(c[2].get("entity_id")) and base in str(c[2].get("entity_id"))]
    remote = trv.last("number", "set_value", f"number.{base}_remote_temperature")
    assert remote is not None and remote["value"] == 20.5
    assert hass.states.get("climate.trv_handtuch").attributes["trv_type"] == "bosch_bth_ra"

    # remote temperature is re-sent before the 30 min fallback of the TRV
    count = len([c for c in trv.calls if c[2].get("entity_id") == f"number.{base}_remote_temperature"])
    for _ in range(5):  # 25 min, one control cycle every 5 min (radiator)
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert len([c for c in trv.calls if c[2].get("entity_id") == f"number.{base}_remote_temperature"]) > count

    await climate.async_calibrate_valve()
    assert pressed == [f"button.{base}_valve_adapt_process"]

    await climate.async_set_hvac_mode(HVACMode.OFF)
    await hass.async_block_till_done()
    assert trv.last("number", "set_value", f"number.{base}_pi_heating_demand")["value"] == 0
    assert hass.states.get(f"climate.{base}").state == "off"
    assert hass.states.get(f"climate.{base}").attributes["temperature"] == 5.0
