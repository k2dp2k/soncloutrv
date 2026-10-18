"""Does the learned room model (insights.ThermalModel) learn something useful?

Run: python3 tests/sim_model.py

The v2.4 controller heats the ClouSet screed room of sim_clouset.py for
three weeks (mild October first, then colder, night setback in week 3 for
some excitation). The thermal model learns in shadow mode exactly as it does
in Home Assistant. Every 15 min it forecasts the next 3 h; the forecasts are
compared with what the simulated room really did, and with a naive forecast
("the temperature stays as it is").

Output: learning curve per day (parameters, confidence, 3 h forecast error).
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sim_clouset import DT, Room, Sensor  # noqa: E402

ROOT = HERE.parent
PKG = ROOT / "custom_components" / "soncloutrv"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


controller = _load("controller")
insights = _load("insights")

TARGET = 22.0


def outside(t: float) -> float:
    day = t / 86400
    mean = 10.0 if day < 7 else 4.0 if day < 14 else 0.0
    return mean + 4.0 * math.sin(2 * math.pi * (day - 0.375))


def target(t: float) -> float:
    day, hour = t / 86400, (t % 86400) / 3600
    if day >= 14 and (hour >= 22 or hour < 6):
        return TARGET - 1.5
    return TARGET


def main(days: int = 21, seed: int = 11) -> None:
    random.seed(seed)
    room = Room(t0=TARGET, supply=34.0)
    sensor = Sensor()
    ctrl = controller.RoomController("room")
    model = insights.ThermalModel(floor_lag_h=2.0)
    opening = 0
    next_run = 0.0
    pending: list[tuple[float, float, float]] = []  # (due time, forecast, naive)
    per_day: dict[int, list[tuple[float, float]]] = {}
    t = 0.0
    while t < days * 86400:
        t_out = outside(t)
        ctrl.add_outside_temperature(t, t_out)
        val, _ = sensor.read(t, room.tr)
        if val is not None:
            ctrl.add_temperature(t, val)
        if t >= next_run:
            next_run = t + 900
            res = ctrl.compute(t, target(t))
            opening = controller.demand_to_opening(res.demand, 40)
            applied = opening / 40 * 100
            model.track_input(t, applied)
            smooth, slope = ctrl.trend.estimate(t)
            if smooth is not None and not res.disturbance:
                model.update(t, smooth, slope, t_out)
                forecast = model.forecast(smooth, t_out, applied)
                three_h = next(v for m, v in forecast if m == 180)
                pending.append((t + 3 * 3600, three_h, smooth))
        while pending and pending[0][0] <= t:
            _, fc, naive = pending.pop(0)
            per_day.setdefault(int(t // 86400), []).append((fc - room.tr, naive - room.tr))
        room.step(opening, t_out, 0.0)
        if t % 86400 == 0 and t > 0:
            day = int(t // 86400)
            errs = per_day.get(day - 1, [])
            rmse = lambda k: math.sqrt(sum(e[k] ** 2 for e in errs) / max(1, len(errs)))
            conf = model.confidence()
            print(
                f"day {day:2d}  tau={model.time_constant_h:6.1f} h  heat={model.heating_rate:5.2f} K/h  "
                f"foreign={model.foreign_heat:+.2f} K/h  conf a/b/c={conf['a']:.2f}/{conf['b']:.2f}/{conf['c']:.2f}  "
                f"3h forecast RMSE model={rmse(0):.2f} K  naive={rmse(1):.2f} K"
            )
        t += DT
    print(f"\nmodel demand for {TARGET} °C at 0 °C outside: {model.steady_demand(TARGET, 0.0)} %")


if __name__ == "__main__":
    main()
