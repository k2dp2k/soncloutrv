"""Learned room model and control quality statistics."""
from __future__ import annotations

import math
import random

from custom_components.soncloutrv.controller import RoomController
from custom_components.soncloutrv.insights import ComfortTracker, ThermalModel


def _drive(model: ThermalModel, *, a: float, b: float, c: float, days: int, heat: bool, seed: int = 1):
    """Simulate dT/dt = a (Tout - T) + b u_f + c and feed the model."""
    random.seed(seed)
    temp, uf, t = 21.0, 0.0, 0.0
    dt_h = 0.25
    k = 1.0 - math.exp(-dt_h / model.floor_lag_h)
    for step in range(int(days * 96)):
        outside = 5.0 + 5.0 * math.sin(2 * math.pi * step / 96)
        u = (0.6 if (step // 24) % 2 else 0.1) if heat else 0.0
        slope = a * (outside - temp) + b * uf + c
        model.track_input(t, u * 100)
        model.update(t, temp, slope + random.gauss(0, 0.02), outside)
        uf += k * (u - uf)
        temp += dt_h * slope
        t += dt_h * 3600
    return temp, outside


def test_model_identifies_a_known_room():
    model = ThermalModel(floor_lag_h=2.0)
    _drive(model, a=0.05, b=2.0, c=0.15, days=10, heat=True)
    assert 15 < model.time_constant_h < 25  # true 20 h
    assert 1.6 < model.heating_rate < 2.4  # true 2.0 K/h
    assert 0.05 < model.foreign_heat < 0.25  # true 0.15 K/h
    conf = model.confidence()
    assert conf["a"] > 0.5 and conf["b"] > 0.5
    assert model.updates >= 900


def test_shut_valve_keeps_heating_rate_uncertain():
    """October: the valve is closed, b cannot be learned - the model admits it."""
    model = ThermalModel(floor_lag_h=2.0)
    _drive(model, a=0.04, b=2.0, c=0.3, days=10, heat=False)
    assert model.confidence()["b"] < 0.2
    assert model.steady_demand(22.0, 5.0) is not None
    # bounded covariance: no blow-up without excitation
    assert all(math.isfinite(x) and abs(x) < 10 for row in model.p for x in row)


def test_forecast_scenarios_are_ordered():
    model = ThermalModel(floor_lag_h=2.0)
    _drive(model, a=0.05, b=2.0, c=0.1, days=5, heat=True)
    hold = model.forecast(21.0, 5.0, 30.0)
    off = model.forecast(21.0, 5.0, 0.0)
    full = model.forecast(21.0, 5.0, 100.0)
    assert hold[0] == [0, 21.0] and len(hold) == 13  # every 30 min for 6 h
    assert off[-1][1] < hold[-1][1] < full[-1][1]
    assert off[-1][1] < 21.0  # cools down without heating at 5 °C outside


def test_model_persistence_roundtrip_and_garbage():
    model = ThermalModel()
    _drive(model, a=0.05, b=2.0, c=0.1, days=2, heat=True)
    data = model.as_dict()
    other = ThermalModel()
    other.restore(data)
    assert other.theta == data["theta"] and other.updates == model.updates
    other.restore({"v": 1, "theta": ["x"], "p": []})
    assert other.updates == model.updates  # garbage is ignored
    other.restore({"v": 99})  # unknown version is ignored


def test_comfort_tracker_rolling_24h():
    tracker = ComfortTracker()
    for i in range(200):
        tracker.add(i * 900.0, 0.1 if i % 4 else 0.6)
    stats = tracker.stats()
    assert stats["samples"] == 96
    assert stats["in_band"] == 75.0
    assert 0.2 < stats["rms"] < 0.4
    other = ComfortTracker()
    other.restore(tracker.as_dict())
    assert other.stats() == stats


def test_controller_persists_model_and_comfort():
    ctrl = RoomController("r")
    ctrl.add_outside_temperature(0, 5.0)
    now = 0.0
    for i in range(130):
        ctrl.add_temperature(now, 21.5 + 0.1 * math.sin(i / 10))
        res = ctrl.compute(now, 21.5)
        ctrl.model.track_input(now, res.demand)
        now += 900
    assert ctrl.model.updates > 96
    info = ctrl.insights(21.5, 20.0)
    assert info["model_ready"] is True
    assert info["comfort_in_band_24h"] == 100.0
    assert set(info["model_forecast"]) == {"hold", "off", "full"}
    other = RoomController("r")
    other.restore(ctrl.as_dict())
    assert other.model.updates == ctrl.model.updates
    assert other.comfort.stats() == ctrl.comfort.stats()
    other.reset_learning()
    assert other.model.updates == 0 and other.comfort.stats()["samples"] == 0
