"""Simulation of a ClouSet screed floor-heating room: old vs. new controller.

Run: python3 tests/sim_clouset.py

The model is deliberately simple but captures what matters for control:
screed mass (hours), room mass, supply dead time, quick-opening valve with a
pre-set maximum flow, sensor quantisation (0.1 K, report on change) and a
shared supply whose available flow drops when many loops are open.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "controller", ROOT / "custom_components" / "soncloutrv" / "controller.py"
)
controller = importlib.util.module_from_spec(spec)
sys.modules["controller"] = controller
spec.loader.exec_module(controller)

DT = 30.0  # s simulation step


class Room:
    """Two-mass model: screed floor + room (air, furniture, wall surface)."""

    def __init__(self, t0: float = 20.5, *, supply: float = 38.0, q_full: float = 2600.0, valve_exp: float = 2.0):
        self.tf = t0 + 2.0  # floor
        self.tr = t0  # room
        self.cf = 2.6e6  # J/K  (65 mm screed, 20 m²)
        self.cr = 1.6e6  # J/K
        self.h_fr = 200.0  # W/K floor -> room
        self.h_ro = 55.0  # W/K room -> outside
        self.supply = supply
        self.q_full = q_full
        self.delay = [0.0] * int(8 * 60 / DT)  # 8 min water transport
        self.water_factor = 1.0
        self.valve_exp = valve_exp

    def valve_flow(self, opening: float, max_opening: float = 40.0) -> float:
        """Quick-opening characteristic, flow limited by the pre-setting."""
        x = max(0.0, min(1.0, opening / max_opening))
        return 1.0 - (1.0 - x) ** self.valve_exp

    def step(self, opening: float, t_out: float, sun: float) -> None:
        # neighbouring loops change the available differential pressure
        self.water_factor += random.gauss(0, 0.004) + (1.0 - self.water_factor) * 0.002
        self.water_factor = max(0.75, min(1.25, self.water_factor))
        flow = self.valve_flow(opening) * self.water_factor
        self.delay.append(flow)
        flow = self.delay.pop(0)
        q_w = self.q_full * flow * max(0.0, self.supply - self.tf) / (self.supply - 24.0)
        q_fr = self.h_fr * (self.tf - self.tr)
        q_ro = self.h_ro * (self.tr - t_out)
        self.tf += DT * (q_w - q_fr) / self.cf
        self.tr += DT * (q_fr - q_ro + sun) / self.cr


class Sensor:
    def __init__(self):
        self.value = None
        self.last_report = -1e9

    def read(self, t: float, true_temp: float):
        q = round(true_temp + random.gauss(0, 0.02), 1)
        if self.value is None or abs(q - self.value) >= 0.1 or t - self.last_report > 1800:
            changed = self.value != q
            self.value = q
            self.last_report = t
            return q, changed
        return None, False


# --------------------------------------------------------------------------
# Old controller (1.3.3 logic, condensed but faithful)
# --------------------------------------------------------------------------
class OldController:
    def __init__(self):
        self.kp, self.ki, self.kd, self.hyst = 10.0, 0.005, 0.0, 0.15
        self.max_valve = 40
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_calc = None
        self.avg_error = 0.0
        self.min_interval = 600
        self.last_write = None
        self.opening = 0
        self.writes = 0

    def calc(self, t, cur, tgt):
        error = tgt - cur
        dt = 0.0 if self.last_calc is None else t - self.last_calc
        self.last_calc = t
        if 0 < dt < 7200:
            if self.avg_error == 0:
                self.avg_error = abs(error)
            else:
                a = min(0.1, dt / 7200)
                self.avg_error = (1 - a) * self.avg_error + a * abs(error)
        ae = abs(error)
        gs = 2.0 if ae > 1.8 else 1.7 if ae > 1.2 else 1.4 if ae > 0.7 else 1.2 if ae > 0.3 else 1.0
        kp = self.kp * gs * (0.8 if error < 0 else 1.0)
        p = kp * error
        ki = self.ki
        if self.avg_error > self.hyst:
            ki *= min(4.0, 1 + max(0, (self.avg_error - self.hyst) / 0.3))
        if 0 < dt < 3600 and ki > 0:
            if ae < self.hyst:
                self.integral *= 0.9
            elif ae <= 1.0:
                if error > 0.5:
                    self.integral += error * dt
                else:
                    self.integral *= 0.9
            else:
                self.integral *= 0.95
            if error < -0.5:
                self.integral *= 0.9
            self.integral = max(-200.0, min(100.0 / ki, self.integral))
        i = ki * self.integral
        if error * self.prev_error < 0:
            self.integral = 0.0
        self.prev_error = error
        out = max(0.0, min(100.0, p + i))
        final = int(out / 100 * self.max_valve)
        if error < -self.hyst:
            final = 0
        elif error > self.hyst and final == 0:
            final = 1
        return final

    def control(self, t, cur, tgt):
        desired = self.calc(t, cur, tgt)
        if self.last_write is None or (t - self.last_write >= self.min_interval and desired != self.opening):
            if desired != self.opening:
                self.writes += 1
            self.opening = desired
            self.last_write = t


class NewController:
    def __init__(self, mode="pid", **settings):
        self.c = controller.RoomController("room")
        if settings:
            st = controller.ControllerSettings(**settings)
            self.c.apply_settings(st)
        self.mode = mode
        self.opening = 0
        self.writes = 0
        self.next_run = 0.0
        self.pwm_start = None
        self.pwm_on = 0.0
        self.demand = 0.0

    def feed(self, t, value):
        self.c.add_temperature(t, value)

    def control(self, t, tgt, t_out):
        self.c.add_outside_temperature(t, t_out)
        if t < self.next_run:
            if self.mode == "pwm" and self.pwm_start is not None:
                desired = 40 if t - self.pwm_start < self.pwm_on else 0
                self._write(desired)
            return
        self.next_run = t + self.c.settings.profile.interval_s
        res = self.c.compute(t, tgt, mode="pid")
        self.demand = res.demand
        if self.mode == "pwm":
            period = self.c.settings.profile.pwm_period_s
            if self.pwm_start is None or t - self.pwm_start >= period:
                self.pwm_start = t
                self.pwm_on = controller.pwm_on_seconds(res.demand, period)
            desired = 40 if t - self.pwm_start < self.pwm_on else 0
        else:
            desired = controller.demand_to_opening(res.demand, 40)
            if abs(desired - self.opening) < 3 and not (desired == 0) != (self.opening == 0):
                desired = self.opening
        self._write(desired)

    def _write(self, desired):
        if desired != self.opening:
            self.writes += 1
            self.opening = desired


def outside_temp(t):
    day = t / 86400
    return 3.0 + 4.0 * math.sin(2 * math.pi * (day - 0.375)) - 3.0 * (day > 3.5)


def sun_gain(t):
    day = t / 86400
    hour = (t % 86400) / 3600
    if int(day) in (1, 4) and 11 <= hour <= 15:
        return 450.0 * math.sin(math.pi * (hour - 11) / 4)
    return 0.0


def setpoint(t, setback):
    hour = (t % 86400) / 3600
    if setback and (hour >= 22 or hour < 6):
        return 19.5
    return 21.5


def run(ctrl_kind: str, *, setback: bool, days: float = 6.0, seed: int = 1, valve_exp: float = 2.0, **settings):
    random.seed(seed)
    room = Room(valve_exp=valve_exp)
    sensor = Sensor()
    if ctrl_kind == "old":
        ctrl = OldController()
    else:
        ctrl = NewController("pwm" if ctrl_kind == "pwm" else "pid", **settings)
    samples = []
    t = 0.0
    last_val = None
    warmup = 86400.0  # ignore first day in the metrics
    while t < days * 86400:
        tgt = setpoint(t, setback)
        val, changed = sensor.read(t, room.tr)
        if val is not None:
            last_val = val
            if ctrl_kind == "old":
                if changed:
                    ctrl.control(t, val, tgt)
            else:
                ctrl.feed(t, val)
        if ctrl_kind == "old":
            if last_val is not None and (ctrl.last_write is None or t - ctrl.last_write >= 600):
                ctrl.control(t, last_val, tgt)
        else:
            ctrl.control(t, tgt, outside_temp(t))
        room.step(ctrl.opening, outside_temp(t), sun_gain(t))
        if t >= warmup:
            samples.append((t, room.tr, tgt, ctrl.opening))
        t += DT
    return samples, ctrl


def _sunny(t):
    day = int(t / 86400)
    hour = (t % 86400) / 3600
    return day in (1, 4) and 11 <= hour <= 21


def metrics(samples, ctrl):
    """Comfort metrics outside the sunny afternoons (sun gain is not controllable)."""
    comfort = [tr - tgt for t, tr, tgt, _ in samples if tgt == 21.5 and not _sunny(t)]
    rms = math.sqrt(sum(e * e for e in comfort) / max(1, len(comfort)))
    crossings = 0
    prev = None
    for e in comfort:
        state = True if e > 0.1 else False if e < -0.1 else prev
        if prev is not None and state is not None and state != prev:
            crossings += 1
        prev = state
    return {
        "max_over_K": round(max(comfort), 2),
        "max_under_K": round(min(comfort), 2),
        "rms_K": round(rms, 3),
        "crossings": crossings,
        "valve_writes": ctrl.writes,
    }


if __name__ == "__main__":
    for exp in (1.0, 2.0, 3.0):
        for setback in (False, True):
            print(f"\n=== valve curve exp={exp}, {'night setback 22-6 h' if setback else 'constant 21.5 °C'} ===")
            for kind in ("old", "new", "pwm"):
                samples, ctrl = run(kind, setback=setback, valve_exp=exp)
                print(f"{kind:4s}", metrics(samples, ctrl))
