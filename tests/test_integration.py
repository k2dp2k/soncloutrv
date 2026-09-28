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
def _enable(enable_custom_integrations):
    yield


async def _setup(hass: HomeAssistant, *, version: int = 1, data=None, options=None) -> tuple[MockConfigEntry, FakeTRV]:
    trv = FakeTRV(hass)
    trv.setup_states()
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


async def test_window_sensor_closes_and_resumes(hass: HomeAssistant, mqtt_mock) -> None:
    _, trv = await _setup(hass)
    await _run_cycle(hass)
    assert trv.last("number", "set_value", OPEN)["value"] > 0
    hass.states.async_set(WINDOW, "on", {"device_class": "window"})
    await hass.async_block_till_done()
    assert trv.last("number", "set_value", OPEN)["value"] == 0
    assert hass.states.get("climate.trv_wohn").attributes["window_open"] is True
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    integral_before = climate._controller.integral
    hass.states.async_set(WINDOW, "off", {"device_class": "window"})
    await hass.async_block_till_done()
    assert hass.states.get("climate.trv_wohn").attributes["window_open"] is False
    assert trv.last("number", "set_value", OPEN)["value"] > 0
    # learned state is kept over the window event
    assert climate._controller.integral == pytest.approx(integral_before, abs=0.5)


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


async def test_global_window_scope_keeps_all_frozen(hass: HomeAssistant, mqtt_mock) -> None:
    options = {**V1_OPTIONS, "window_sensor_scope": "all"}
    _, trv = await _setup(hass, options=options)
    await _run_cycle(hass)
    climate = runtime.climate_for_entry(hass, ENTRY_ID)
    hass.states.async_set(WINDOW, "on", {"device_class": "window"})
    await hass.async_block_till_done()
    assert climate._window_freeze_active
    hass.states.async_set(WINDOW, "off", {"device_class": "window"})
    await hass.async_block_till_done()
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


async def test_room_setpoint_is_shared(hass: HomeAssistant, mqtt_mock) -> None:
    """Wohnen + Küche are one room: one set-point for both circuits."""
    await _setup(hass)
    base2 = "heizung_kuche_fussboden"
    hass.states.async_set(f"climate.{base2}", "off", {"hvac_modes": ["off", "heat"], "temperature": 7})
    hass.states.async_set(f"number.{base2}_valve_opening_degree", "0")
    hass.states.async_set(f"number.{base2}_valve_closing_degree", "100")
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        title="trv_kuche",
        data={**V1_DATA, "name": "trv_kuche", "valve_entity": f"climate.{base2}", "target_temp": 19.0},
        options={**V1_OPTIONS, "target_temp": 19.0},
        version=CONFIG_VERSION,
        entry_id="01KXKZ7SKVSYSTS33R44NB22P1",
        unique_id=f"climate.{base2}",
    )
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    await hass.async_block_till_done()
    wohn = runtime.climate_for_entry(hass, ENTRY_ID)
    kuche = runtime.climate_for_entry(hass, entry2.entry_id)
    # joining circuit adopts the room set-point
    assert kuche.target_temperature == wohn.target_temperature == 21.5
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.trv_kuche", "temperature": 22.0}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.trv_wohn").attributes["temperature"] == 22.0
    assert hass.states.get("climate.trv_kuche").attributes["temperature"] == 22.0
