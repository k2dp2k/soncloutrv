"""Bathroom simulation: ClouSet floor loop + towel radiator (Bosch on the return).

Run: python3 tests/sim_bath.py

Both circuits see the same room sensor. The floor loop is slow (screed), the
towel radiator is fast (small water content, heats the air directly). The
question is how to set the two targets so that the floor carries the base
load and the radiator only assists, without the two controllers fighting.
"""
from __future__ import annotations

import math
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sim_clouset import DT, Room, Sensor, outside_temp, sun_gain  # noqa: E402
import sim_clouset  # noqa: E402

controller = sim_clouset.controller


class Radiator:
    """Towel radiator: 450 W at full flow, ~8 min time constant."""

    def __init__(self, q_full: float = 450.0, tau_s: float = 480.0):
        self.q_full = q_full
        self.tau = tau_s
        self.q = 0.0

    def step(self, opening: float) -> float:
        # Bosch valve on the return: roughly linear flow over the stroke,
        # radiator output saturates above ~60 % flow.
        x = max(0.0, min(1.0, opening / 100.0))
        target = self.q_full * min(1.0, x / 0.6)
        self.q += DT / self.tau * (target - self.q)
        return self.q


class Circuit:
    """PI controlled circuit (role "primary")."""

    def __init__(self, heating_type: str, target: float, max_opening: int):
        self.c = controller.RoomController(f"bad|{heating_type}")
        self.c.apply_settings(controller.ControllerSettings(heating_type=heating_type))
        self.target = target
        self.max_opening = max_opening
        self.opening = 0
        self.next_run = 0.0
        self.writes = 0

    def feed(self, t: float, value: float) -> None:
        self.c.add_temperature(t, value)

    def control(self, t: float, t_out: float) -> None:
        self.c.add_outside_temperature(t, t_out)
        if t < self.next_run:
            return
        self.next_run = t + self.c.settings.profile.interval_s
        res = self.c.compute(t, self.target, mode="pid")
        desired = controller.demand_to_opening(res.demand, self.max_opening)
        if abs(desired - self.opening) < 3 and not (desired == 0) != (self.opening == 0):
            desired = self.opening
        if desired != self.opening:
            self.writes += 1
            self.opening = desired


class AssistCircuit(Circuit):
    """Role "assist" as implemented in climate.py: two-point on the predicted
    error, on below target - 0.5 K, off above target - 0.1 K, no learning."""

    ON_BELOW = 0.5
    OFF_BELOW = 0.1

    def control(self, t: float, t_out: float) -> None:
        if t < self.next_run:
            return
        self.next_run = t + self.c.settings.profile.interval_s
        centre = (self.ON_BELOW + self.OFF_BELOW) / 2
        res = self.c.compute(
            t, self.target - centre, mode="binary", hysteresis=(self.ON_BELOW - self.OFF_BELOW) / 2
        )
        desired = self.max_opening if res.demand > 0 else 0
        if desired != self.opening:
            self.writes += 1
            self.opening = desired


def run(radiator_target: float | None, *, days: float = 6.0, seed: int = 3, cold_shift: float = 0.0):
    """radiator_target None = assist role, else PI with that target."""
    random.seed(seed)
    room = Room(t0=20.5, q_full=1800.0)  # small bathroom loop
    room.h_ro = 40.0
    rad = Radiator()
    sensor = Sensor()
    floor = Circuit("floor", 21.5, 40)
    if radiator_target is None:
        towel: Circuit = AssistCircuit("radiator", 21.5, 100)
    else:
        towel = Circuit("radiator", radiator_target, 100)
    t = 0.0
    samples = []
    while t < days * 86400:
        t_out = outside_temp(t) - cold_shift
        val, _ = sensor.read(t, room.tr)
        if val is not None:
            floor.feed(t, val)
            towel.feed(t, val)
        floor.control(t, t_out)
        towel.control(t, t_out)
        q_rad = rad.step(towel.opening)
        # shower at 7:00: window/vent + moisture, modelled as a 1.2 K air drop
        hour = (t % 86400) / 3600
        if 7.0 <= hour < 7.05:
            room.tr -= 1.2 * DT / 180.0
        room.step(floor.opening, t_out, sun_gain(t) * 0.3 + q_rad)
        if t >= 86400:
            samples.append((t, room.tr, floor.opening, towel.opening, q_rad))
        t += DT
    errs = [tr - 21.5 for _, tr, _, _, _ in samples]
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    floor_share = sum(o for _, _, o, _, _ in samples) / len(samples) / 40.0
    rad_share = sum(q for *_, q in samples) / len(samples) / 450.0
    return {
        "radiator": "assist" if radiator_target is None else f"PI @ {radiator_target}",
        "rms_K": round(rms, 3),
        "min_K": round(min(errs), 2),
        "max_K": round(max(errs), 2),
        "floor_duty": round(floor_share, 2),
        "radiator_duty": round(rad_share, 2),
        "floor_I": round(floor.c.integral, 1),
        "rad_I": round(towel.c.integral, 1),
        "writes_floor": floor.writes,
        "writes_rad": towel.writes,
    }


if __name__ == "__main__":
    for shift in (0.0, 8.0):
        print(f"\n=== outside {3 - shift:+.0f} °C mean (day/night swing 4 K) ===")
        for target in (21.5, 20.5, None):
            print(run(target, cold_shift=shift))
