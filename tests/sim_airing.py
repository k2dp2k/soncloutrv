"""Long airing through a window the room does not know (November 2026 data).

Run: python3 tests/sim_airing.py [path/to/controller.py ...]

Observed on 24.-26.11.2026 (outside 0 °C): the bedroom window was open for
two hours, the doors inside the flat were open. Living room and bathroom
have no sensor on that window. Their air dropped by 1.5-2 K within ten
minutes and stayed there. The rate limiter (0.8 K/h) hid the draft for the
first hour only, then the floor loop heated against the open window with
up to 66 % demand. After the window was closed the air recovered by itself
within an hour, and the heat stored in the screed pushed the room 0.9 K
(living room) to 1.6 K (bathroom) above the target for the rest of the day.

Scenarios (ClouSet screed model of sim_clouset.py, outside 0 °C +- 3 K):

* ``airing_2h``  - every morning 08:30-10:30 cold air (-2 K within 10 min).
* ``airing_30``  - every morning 30 min, every evening 30 min.
* ``cold_snap``  - no airing; the outside temperature falls by 14 K within
                   a day. A real heat deficit: must not get slower.
* ``supply_off`` - no airing; the boiler is off for 12 h, then back. The room
                   really cools down and has to be reheated.
"""
from __future__ import annotations

import math
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sim_clouset import DT, Room, Sensor  # noqa: E402
from sim_disturbances import DEFAULT_CONTROLLER, Circuit, load_controller  # noqa: E402

TARGET = 22.2
# The flat lies between heated neighbours: at 0 °C outside the rooms need
# only 10-15 % demand (sim_clouset.py models a detached room with 55 W/K).
H_ROOM_OUTSIDE = 15.0  # W/K
# Cold air flowing through the flat: the air at the sensor drops by
# DRAFT_AIR_DROP within ~10 min and comes back within ~30 min after the
# window is closed (measured), walls and furniture lose DRAFT_W_PER_K.
DRAFT_AIR_DROP = 2.0  # K
DRAFT_W_PER_K = 7.0
DRAFT_TAU_IN = 420.0  # s
DRAFT_TAU_OUT = 1500.0  # s


def outside(t: float, scenario: str) -> float:
    base = 0.0 + 3.0 * math.sin(2 * math.pi * (t / 86400 - 0.375))
    if scenario == "cold_snap":
        base += 8.0 - 14.0 * min(1.0, max(0.0, (t / 86400 - 3.0)))
    return base


def airing(scenario: str, hour: float) -> bool:
    if scenario == "airing_2h":
        return 8.5 <= hour < 10.5
    if scenario == "airing_30":
        return 8.5 <= hour < 9.0 or 20.0 <= hour < 20.5
    return False


def run(ctrl_mod, scenario: str, *, days: float = 7.0, seed: int = 3) -> dict:
    random.seed(seed)
    room = Room(t0=TARGET, supply=36.0)
    room.h_ro = H_ROOM_OUTSIDE
    room.tf = TARGET + 1.5
    air_drop = 0.0
    sensor = Sensor()
    circuit = Circuit(ctrl_mod)
    circuit.c.integral = 8.0
    t = 0.0
    errs: list[float] = []
    quiet: list[float] = []  # outside the airing itself
    demand_airing: list[float] = []
    q_full = room.q_full
    while t < days * 86400:
        day, hour = divmod(t / 3600.0, 24.0)
        t_out = outside(t, scenario)
        gain = 0.0
        open_now = airing(scenario, hour)
        if open_now:
            gain -= DRAFT_W_PER_K * (room.tr - t_out)
            air_drop += (DRAFT_AIR_DROP - air_drop) * DT / DRAFT_TAU_IN
        else:
            air_drop -= air_drop * DT / DRAFT_TAU_OUT
        if scenario == "supply_off":
            room.q_full = 0.0 if (day == 3 and 2.0 <= hour < 14.0) else q_full
        val, _ = sensor.read(t, room.tr - air_drop)
        if val is not None:
            circuit.c.add_temperature(t, val)
        # same call as Circuit.control, but with this file's target
        circuit.c.add_outside_temperature(t, t_out)
        if t >= circuit.next_run:
            circuit.next_run = t + circuit.c.settings.profile.interval_s
            res = circuit.c.compute(t, TARGET)
            desired = ctrl_mod.demand_to_opening(res.demand, 40)
            if abs(desired - circuit.opening) < 3 and not (desired == 0) != (circuit.opening == 0):
                desired = circuit.opening
            if desired != circuit.opening:
                circuit.writes += 1
                circuit.opening = desired
            if open_now and t >= 86400:
                demand_airing.append(res.demand)
        room.step(circuit.opening, t_out, gain)
        if t >= 86400:
            errs.append(room.tr - air_drop - TARGET)
            if air_drop < 0.3:
                quiet.append(room.tr - air_drop - TARGET)
        t += DT
    rms = math.sqrt(sum(e * e for e in quiet) / len(quiet))
    over = sum(1 for e in quiet if e > 0.3) * DT / 3600.0 / (days - 1)
    under = sum(1 for e in quiet if e < -0.3) * DT / 3600.0 / (days - 1)
    return {
        "rms_K": round(rms, 3),
        "max_over_K": round(max(quiet), 2),
        "max_under_K": round(min(quiet), 2),
        "h_over_per_day": round(over, 1),
        "h_under_per_day": round(under, 1),
        "demand_in_airing": round(sum(demand_airing) / len(demand_airing), 1) if demand_airing else None,
        "valve_writes": circuit.writes,
    }


if __name__ == "__main__":
    paths = [pathlib.Path(p) for p in sys.argv[1:]] or [DEFAULT_CONTROLLER]
    mods = [(p, load_controller(p)) for p in paths]
    for scenario in ("airing_2h", "airing_30", "cold_snap", "supply_off"):
        print(f"\n=== {scenario} ===")
        for path, mod in mods:
            print(f"{str(path)[-40:]:40s}", run(mod, scenario))
