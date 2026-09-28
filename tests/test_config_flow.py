"""Config and options flow tests."""
from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.soncloutrv.const import CONFIG_VERSION, DOMAIN
from custom_components.soncloutrv.controller import PROFILES


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    yield


async def test_user_flow_creates_v4_entry(hass: HomeAssistant, mqtt_mock) -> None:
    hass.states.async_set("climate.trv_x", "off", {"hvac_modes": ["off", "heat"]})
    hass.states.async_set("sensor.room_x", "20.0", {"device_class": "temperature"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "trv_neu",
            "valve_entity": "climate.trv_x",
            "room_id": "Gästezimmer",  # custom room name
            "heating_type": "radiator",
            "temp_sensor": "sensor.room_x",
            "window_sensor_scope": "local",
            "min_temp": 6,
            "max_temp": 25,
            "target_temp": 21,
            "valve_opening_step": "2",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.version == CONFIG_VERSION
    assert entry.options["heating_type"] == "radiator"
    assert entry.options["kp"] == PROFILES["radiator"].kp
    assert entry.data["room_id"] == "Gästezimmer"


async def test_options_flow_switch_heating_type(hass: HomeAssistant, mqtt_mock) -> None:
    hass.states.async_set("climate.trv_x", "off", {"hvac_modes": ["off", "heat"]})
    hass.states.async_set("sensor.room_x", "20.0", {"device_class": "temperature"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONFIG_VERSION,
        data={
            "name": "trv_x",
            "valve_entity": "climate.trv_x",
            "temp_sensor": "sensor.room_x",
            "min_temp": 6,
            "max_temp": 25,
            "target_temp": 21.5,
            "valve_opening_step": "2",
        },
        options={"heating_type": "floor", "kp": 25.0, "ki": 0.001736},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "heating_type": "radiator",
            "control_mode": "pid",
            "temp_sensor": "sensor.room_x",
            "room_id": "Bad",
            "window_sensor_scope": "local",
            "window_drop_threshold": 0.8,
            "window_stable_band": 0.3,
            "window_max_freeze": 10800,
            "min_temp": 6,
            "max_temp": 25,
            "target_temp": 21.5,
            "valve_opening_step": "3",
            "sensor_timeout": 240,
            "adaptive_feed_forward": True,
            "room_logging_enabled": False,
            "room_log_file": "sontrv_room_log.csv",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["heating_type"] == "radiator"
    assert entry.options["kp"] == PROFILES["radiator"].kp
    assert entry.options["valve_opening_step"] == "3"
