"""Learned room model and control quality statistics for SonTRV.

Free of Home Assistant imports so it can be unit tested and simulated.

ThermalModel - a learned (grey box) model of one room
------------------------------------------------------
The controller in ``controller.py`` learns *how much* demand a room needs
(integral, weather feed-forward). It does not learn *how the room behaves*.
The thermal model does, by online system identification (recursive least
squares with forgetting, a classic machine learning method for dynamic
systems)::

    dT/dt = a * (T_out - T) + b * u_f + c          [K/h]

* ``a``   [1/h]  heat loss rate, ``1/a`` is the room's time constant,
* ``b``   [K/h]  how fast full heating demand warms the room,
* ``c``   [K/h]  heat that is not ours (neighbours, sun, people, devices),
* ``u_f``        heating demand (0..1) delayed by the floor: a first order
                 lag with the screed's time constant (2 h, radiator 15 min).

The model is fitted on the smoothed temperature slope of every control
cycle, but only in undisturbed phases (no window, no draft, no recovery).
It runs in shadow mode: it predicts and explains, it does not steer the
valve. Its outputs are

* forecasts of the room temperature for the next hours for three
  scenarios (keep the valve, close it, open it fully),
* the demand the model expects for the target at the current weather
  (a cross check of the learned integral + feed-forward),
* a confidence per parameter (from the RLS covariance): in mild weather the
  valve is mostly closed and ``b`` cannot be learned yet - the model says so
  instead of inventing a value.

ComfortTracker - how good is the control?
-----------------------------------------
Rolling 24 h statistics of the control error (share of time within
+-0.3 K, RMS, mean deviation).
"""
from __future__ import annotations

import math
from typing import Any

MODEL_VERSION = 1

# Parameter bounds (physically plausible for a flat).
A_MIN, A_MAX = 0.005, 0.5  # 1/h  -> time constant 2 ... 200 h
B_MIN, B_MAX = 0.0, 20.0  # K/h at full demand
C_MIN, C_MAX = -2.0, 2.0  # K/h

# Prior and initial uncertainty (variance) of [a, b, c].
THETA0 = (0.04, 1.0, 0.0)
P0 = (0.0025, 4.0, 0.25)
# Forgetting factor per update (15 min): memory of roughly 10 days.
FORGETTING = 0.999
# Updates with a larger smoothed slope are not model data (disturbance).
MAX_SLOPE = 2.0  # K/h
# Minimum spacing of parameter updates / input tracking.
MIN_UPDATE_SPACING = 600.0  # s
# Forecasts are only published after this many model updates (~1 day).
MIN_UPDATES_FOR_FORECAST = 96
# Forecast settings.
FORECAST_HOURS = 6
FORECAST_STEP_H = 0.25
FORECAST_POINT_EVERY = 2  # one output point every 30 min


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class ThermalModel:
    """Online identified first order room model (see module docstring)."""

    def __init__(self, floor_lag_h: float = 2.0) -> None:
        self.floor_lag_h = floor_lag_h
        self.theta = list(THETA0)
        self.p = [[P0[i] if i == j else 0.0 for j in range(3)] for i in range(3)]
        self.u_f = 0.0  # delayed demand 0..1
        self.u_last = 0.0  # last applied demand 0..1
        self._u_ts: float | None = None
        self._update_ts: float | None = None
        self.updates = 0
        self.rmse: float | None = None  # K/h, one step slope residual

    # --- persistence -----------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        return {
            "v": MODEL_VERSION,
            "theta": [round(x, 6) for x in self.theta],
            "p": [[round(x, 8) for x in row] for row in self.p],
            "u_f": round(self.u_f, 4),
            "updates": self.updates,
            "rmse": None if self.rmse is None else round(self.rmse, 4),
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict) or data.get("v") != MODEL_VERSION:
            return
        try:
            theta = [float(x) for x in data["theta"]]
            p = [[float(x) for x in row] for row in data["p"]]
            if len(theta) != 3 or len(p) != 3 or any(len(r) != 3 for r in p):
                return
            if not all(math.isfinite(x) for x in theta) or not all(math.isfinite(x) for r in p for x in r):
                return
            self.theta = theta
            self.p = p
            self.u_f = _clamp(float(data.get("u_f", 0.0)), 0.0, 1.0)
            self.updates = max(0, int(data.get("updates", 0)))
            rmse = data.get("rmse")
            self.rmse = None if rmse is None else max(0.0, float(rmse))
        except (KeyError, TypeError, ValueError):
            return
        self._project()

    def reset(self) -> None:
        self.__init__(self.floor_lag_h)

    # --- inputs ----------------------------------------------------------
    def track_input(self, now: float, demand_percent: float) -> None:
        """Advance the floor lag with the demand that was applied until now."""
        u = _clamp(demand_percent / 100.0, 0.0, 1.0)
        if self._u_ts is not None and now > self._u_ts:
            dt_h = min(6.0, (now - self._u_ts) / 3600.0)
            # exact discretisation of the first order lag
            k = 1.0 - math.exp(-dt_h / max(0.05, self.floor_lag_h))
            self.u_f += k * (self.u_last - self.u_f)
        self.u_last = u
        self._u_ts = now

    def regressors(self, temp: float, outside: float) -> list[float]:
        return [outside - temp, self.u_f, 1.0]

    def update(self, now: float, temp: float, slope: float, outside: float) -> bool:
        """One RLS step with the smoothed slope (K/h). Returns True if used."""
        if self._update_ts is not None and now - self._update_ts < MIN_UPDATE_SPACING:
            return False
        if not all(math.isfinite(v) for v in (temp, slope, outside)) or abs(slope) > MAX_SLOPE:
            return False
        self._update_ts = now
        x = self.regressors(temp, outside)
        y = slope
        theta, p = self.theta, self.p
        px = [sum(p[i][j] * x[j] for j in range(3)) for i in range(3)]
        denom = FORGETTING + sum(x[i] * px[i] for i in range(3))
        if denom <= 1e-12:
            return False
        error = y - sum(theta[i] * x[i] for i in range(3))
        gain = [px[i] / denom for i in range(3)]
        self.theta = [theta[i] + gain[i] * error for i in range(3)]
        self.p = [
            [(p[i][j] - gain[i] * px[j]) / FORGETTING for j in range(3)] for i in range(3)
        ]
        self.updates += 1
        sq = error * error
        self.rmse = math.sqrt(sq) if self.rmse is None else math.sqrt(0.98 * self.rmse**2 + 0.02 * sq)
        self._project()
        return True

    def _project(self) -> None:
        """Keep parameters plausible and the covariance bounded."""
        a, b, c = self.theta
        self.theta = [_clamp(a, A_MIN, A_MAX), _clamp(b, B_MIN, B_MAX), _clamp(c, C_MIN, C_MAX)]
        # Without excitation (valve always shut) forgetting would blow up the
        # covariance of b; cap every variance at its initial value.
        for i in range(3):
            pii = self.p[i][i]
            if not math.isfinite(pii) or pii <= 0:
                self.p = [[P0[k] if k == j else 0.0 for j in range(3)] for k in range(3)]
                return
            if pii > P0[i]:
                scale = math.sqrt(P0[i] / pii)
                for j in range(3):
                    self.p[i][j] *= scale
                    self.p[j][i] *= scale

    # --- outputs ---------------------------------------------------------
    @property
    def time_constant_h(self) -> float:
        return 1.0 / self.theta[0]

    @property
    def heating_rate(self) -> float:
        """K/h the room would warm with full demand (floor fully charged)."""
        return self.theta[1]

    @property
    def foreign_heat(self) -> float:
        """K/h of heat that is not ours (neighbours, sun, people)."""
        return self.theta[2]

    def confidence(self) -> dict[str, float]:
        """0..1 per parameter: 1 - relative standard deviation."""
        out = {}
        for name, i, scale in (("a", 0, max(self.theta[0], 0.01)), ("b", 1, max(self.theta[1], 0.2)), ("c", 2, 0.5)):
            sd = math.sqrt(max(0.0, self.p[i][i]))
            out[name] = round(_clamp(1.0 - sd / scale, 0.0, 1.0), 2)
        return out

    def steady_demand(self, target: float, outside: float) -> float | None:
        """Demand (0..100 %) the model expects to hold ``target``."""
        a, b, c = self.theta
        if b < 0.05:
            return None
        u = (a * (target - outside) - c) / b
        return round(_clamp(u, 0.0, 1.0) * 100.0, 1)

    def predict(self, temp: float, outside: float, demand_percent: float, hours: float) -> float:
        """Room temperature after ``hours`` at a fixed demand."""
        a, b, c = self.theta
        u = _clamp(demand_percent / 100.0, 0.0, 1.0)
        steps = max(1, math.ceil(hours / FORECAST_STEP_H))
        dt_h = hours / steps
        k = 1.0 - math.exp(-dt_h / max(0.05, self.floor_lag_h))
        t, uf = temp, self.u_f
        for _ in range(steps):
            uf += k * (u - uf)
            t += dt_h * (a * (outside - t) + b * uf + c)
        return t

    def forecast(self, temp: float, outside: float, demand_percent: float) -> list[list[float]]:
        """Room temperature every 30 min for FORECAST_HOURS at a fixed demand."""
        a, b, c = self.theta
        u = _clamp(demand_percent / 100.0, 0.0, 1.0)
        t, uf = temp, self.u_f
        k = 1.0 - math.exp(-FORECAST_STEP_H / max(0.05, self.floor_lag_h))
        points = [[0, round(t, 2)]]
        steps = int(FORECAST_HOURS / FORECAST_STEP_H)
        for step in range(1, steps + 1):
            uf += k * (u - uf)
            t += FORECAST_STEP_H * (a * (outside - t) + b * uf + c)
            if step % FORECAST_POINT_EVERY == 0:
                points.append([int(step * FORECAST_STEP_H * 60), round(t, 2)])
        return points


class SkillTracker:
    """Does the model predict the room better than the trend extrapolation?

    Every control cycle both predictions for the end of the controller's
    horizon (45 min floor, 12 min radiator) are stored; when that time has
    come they are compared with the measured temperature. Result: rolling
    (~12 h) prediction error of both and the model's skill in percent.
    """

    ALPHA = 1.0 / 48.0  # EMA weight per comparison (15 min) -> ~12 h
    MIN_SAMPLES = 48
    MAX_PENDING = 64

    def __init__(self) -> None:
        self.mse_model: float | None = None
        self.mse_trend: float | None = None
        self.samples = 0
        self.pending: list[tuple[float, float, float]] = []  # (due, model, trend)
        self._last_add: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "m": None if self.mse_model is None else round(self.mse_model, 6),
            "t": None if self.mse_trend is None else round(self.mse_trend, 6),
            "n": self.samples,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict):
            return
        try:
            m, t = data.get("m"), data.get("t")
            mse_model = None if m is None else float(m)
            mse_trend = None if t is None else float(t)
            samples = max(0, int(data.get("n", 0)))
        except (TypeError, ValueError):
            return
        if any(v is not None and (not math.isfinite(v) or v < 0) for v in (mse_model, mse_trend)):
            return
        self.mse_model, self.mse_trend, self.samples = mse_model, mse_trend, samples

    def discard_pending(self) -> None:
        """A disturbance (window, draft) invalidates the open predictions."""
        self.pending.clear()

    def add(self, now: float, due: float, model: float, trend: float) -> None:
        if self._last_add is not None and now - self._last_add < MIN_UPDATE_SPACING:
            return
        if not all(math.isfinite(v) for v in (model, trend)):
            return
        self._last_add = now
        self.pending.append((due, model, trend))
        del self.pending[: -self.MAX_PENDING]

    def resolve(self, now: float, actual: float) -> None:
        """Score all predictions that are due (late ones are dropped)."""
        keep = []
        for due, model, trend in self.pending:
            if due > now:
                keep.append((due, model, trend))
            elif now - due <= MIN_UPDATE_SPACING * 1.5:
                self._score(actual - model, actual - trend)
        self.pending = keep

    def _score(self, err_model: float, err_trend: float) -> None:
        em, et = err_model * err_model, err_trend * err_trend
        if self.mse_model is None or self.mse_trend is None:
            self.mse_model, self.mse_trend = em, et
        else:
            self.mse_model += self.ALPHA * (em - self.mse_model)
            self.mse_trend += self.ALPHA * (et - self.mse_trend)
        self.samples += 1

    @property
    def rmse_model(self) -> float | None:
        return None if self.mse_model is None else math.sqrt(self.mse_model)

    @property
    def rmse_trend(self) -> float | None:
        return None if self.mse_trend is None else math.sqrt(self.mse_trend)

    def skill(self) -> float | None:
        """% less prediction error than the trend (negative = worse)."""
        if self.samples < self.MIN_SAMPLES or self.mse_model is None or self.mse_trend is None:
            return None
        rt = math.sqrt(self.mse_trend)
        if rt <= 1e-6:
            return None
        return round(100.0 * (1.0 - math.sqrt(self.mse_model) / rt))


class ComfortTracker:
    """Rolling statistics of the control error over the last 24 h."""

    MAX_SAMPLES = 96  # 24 h at one sample per 15 min
    BAND = 0.3  # K

    def __init__(self) -> None:
        self.samples: list[tuple[float, float]] = []  # (timestamp, temp - target)

    def as_dict(self) -> dict[str, Any]:
        return {"s": [[round(ts), round(dev, 3)] for ts, dev in self.samples]}

    def restore(self, data: dict[str, Any] | None) -> None:
        if not isinstance(data, dict):
            return
        try:
            samples = [(float(ts), float(dev)) for ts, dev in data.get("s", [])]
        except (TypeError, ValueError):
            return
        self.samples = [s for s in samples if all(math.isfinite(v) for v in s)][-self.MAX_SAMPLES :]

    def add(self, now: float, deviation: float) -> None:
        """Add ``temp - target`` (positive = too warm)."""
        if not math.isfinite(deviation):
            return
        if self.samples and now - self.samples[-1][0] < MIN_UPDATE_SPACING:
            return
        self.samples.append((now, deviation))
        cutoff = now - 24 * 3600
        self.samples = [s for s in self.samples if s[0] >= cutoff][-self.MAX_SAMPLES :]

    def stats(self) -> dict[str, Any]:
        n = len(self.samples)
        if n == 0:
            return {"samples": 0, "in_band": None, "rms": None, "mean": None, "max_over": None, "max_under": None}
        devs = [d for _, d in self.samples]
        return {
            "samples": n,
            "in_band": round(100.0 * sum(1 for d in devs if abs(d) <= self.BAND) / n, 1),
            "rms": round(math.sqrt(sum(d * d for d in devs) / n), 2),
            "mean": round(sum(devs) / n, 2),
            "max_over": round(max(devs), 2),
            "max_under": round(min(devs), 2),
        }
