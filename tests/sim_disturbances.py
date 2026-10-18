"""Disturbance scenarios observed in the real flat (October 2026 data).

Run: python3 tests/sim_disturbances.py [path/to/controller.py ...]

Every given controller file is simulated on the same scenarios, so an old
and a new version can be compared side by side. Without arguments the
controller of this repository is used.

Scenarios (all on the ClouSet screed model of sim_clouset.py):

* ``drafts``     - hallway: three cold-air drafts per day (front door, balcony
                   door in the open living room) that drop the air by ~2 K in
                   10 min. No window sensor sees them. The floor barely cools,
                   the air recovers by itself within ~30-60 min.
* ``neighbours`` - hallway as observed: drafts (see above) plus heat from
                   the neighbours that keeps the air ~1 K above target with
                   the valve shut for 3 days, then the gain disappears.
                   Measures the stale integral left when the gain stops and
                   how deep the room undershoots / overshoots afterwards.
* ``mild``       - plain October weather (outside 9 °C +- 4 K), no
                   disturbances. Must not get worse.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sim_clouset  # noqa: E402
from sim_clouset import DT, Room, Sensor  # noqa: E402

ROOT = HERE.parent
DEFAULT_CONTROLLER = ROOT / "custom_components" / "soncloutrv" / "controller.py"
TARGET = 22.5


def load_controller(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"ctrl_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outside(t: float, mean: float = 9.0) -> float:
    return mean + 4.0 * math.sin(2 * math.pi * (t / 86400 - 0.375))


class Circuit:
    """Same output stage as climate.py (15 min interval, 3 % deadband)."""

    def __init__(self, ctrl_mod):
        self.mod = ctrl_mod
        self.c = ctrl_mod.RoomController("room")
        self.opening = 0
        self.writes = 0
        self.next_run = 0.0

    def control(self, t: float, t_out: float) -> None:
        self.c.add_outside_temperature(t, t_out)
        if t < self.next_run:
            return
        self.next_run = t + self.c.settings.profile.interval_s
        res = self.c.compute(t, TARGET)
        desired = self.mod.demand_to_opening(res.demand, 40)
        if abs(desired - self.opening) < 3 and not (desired == 0) != (self.opening == 0):
            desired = self.opening
        if desired != self.opening:
            self.writes += 1
            self.opening = desired


def run(ctrl_mod, scenario: str, *, days: float = 8.0, seed: int = 5) -> dict:
    random.seed(seed)
    room = Room(t0=TARGET, supply=34.0)
    sensor = Sensor()
    circuit = Circuit(ctrl_mod)
    # learned state as found in the real flat after a week of mild weather
    circuit.c.integral = 5.0
    t = 0.0
    errs: list[float] = []
    after_gain: list[float] = []
    integral_at_switch = None
    draft_hours = (8.5, 13.0, 18.6)
    while t < days * 86400:
        day, hour = divmod(t / 3600.0, 24.0)
        t_out = outside(t)
        gain = 0.0
        if scenario == "neighbours":
            # heat through walls/ceiling fades over ~6 h, it does not switch off
            gain = 800.0 * min(1.0, max(0.0, (3.25 * 24 - t / 3600.0) / 6.0))
            if day >= 3 and integral_at_switch is None:
                integral_at_switch = circuit.c.integral
        if scenario in ("drafts", "neighbours"):
            for h in draft_hours:
                if h <= hour < h + 10 / 60:
                    gain -= 4500.0  # cold air rushing in
        val, _ = sensor.read(t, room.tr)
        if val is not None:
            circuit.c.add_temperature(t, val)
        circuit.control(t, t_out)
        room.step(circuit.opening, t_out, gain)
        if t >= 86400:
            errs.append(room.tr - TARGET)
            if scenario == "neighbours" and day >= 3:
                after_gain.append(room.tr - TARGET)
        t += DT
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    result = {
        "rms_K": round(rms, 3),
        "max_over_K": round(max(errs), 2),
        "max_under_K": round(min(errs), 2),
        "valve_writes": circuit.writes,
    }
    if scenario == "neighbours":
        result["I_when_gain_stops"] = round(integral_at_switch or 0.0, 1)
        result["under_after_gain_K"] = round(min(after_gain), 2)
    return result


if __name__ == "__main__":
    paths = [pathlib.Path(p) for p in sys.argv[1:]] or [DEFAULT_CONTROLLER]
    mods = [(p, load_controller(p)) for p in paths]
    for scenario in ("drafts", "neighbours", "mild"):
        print(f"\n=== {scenario} ===")
        for path, mod in mods:
            print(f"{path.name:28s}", run(mod, scenario))
