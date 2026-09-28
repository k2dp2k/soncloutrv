"""Room heating controller for SonTRV.

This module is intentionally free of Home Assistant imports so it can be
unit-tested and simulated in isolation.

Why a dedicated controller?
---------------------------
The integration drives SONOFF TRVZB valves that sit on ClouSet single-room
floor-heating boxes (Multi SK / Multi HK). Each room has its own heating
loop in a screed floor, the valve sits in the supply line and the maximum
flow of the loop is fixed by a pre-setting (kv / flow limiter). All loops
share one supply, so rooms influence each other hydraulically.

That results in a plant with

* a long dead time and large thermal mass (screed): the room keeps warming
  for 1-2 h after the valve closes,
* a strongly non-linear valve: most of the flow change happens in the first
  part of the stroke, above that the pre-setting limits the flow,
* disturbances from neighbouring loops (pressure changes when other rooms
  open or close) and from the sun.

A plain PI(D) controller on the current error either overshoots (fast gains)
or is far too slow (slow gains). The old implementation additionally decayed
and reset the integral close to the set-point, so it could never learn the
steady-state heat demand: the valve fell back to 0 whenever the room reached
its target, the room cooled down, the valve opened again - a limit cycle.

The controller below therefore uses:

1. A trend estimate (linear regression over a time window) of the room
   temperature, which gives a smoothed value and the slope in K/h.
2. **Predictive P-term**: the proportional part acts on the temperature that
   is expected after the dead time (``T + slope * horizon``). While the floor
   is still charging the room, the valve closes early instead of after the
   overshoot happened.
3. **Integral that keeps its value** (no decay, no reset on sign change),
   with conditional integration (only close to the set-point) and
   anti-windup at the output limits. It represents the steady-state demand
   and is persisted across restarts.
4. **Learned weather feed-forward**: during quiet phases the controller learns
   how many percent of demand are needed per Kelvin indoor/outdoor
   difference. Changes of the outdoor temperature then act immediately,
   while the integral only corrects the remainder.
5. Detection of a missing heat supply (valve open for hours, temperature not
   rising) which freezes learning so the integral does not wind up while the
   boiler is off.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Heating profiles
# --------------------------------------------------------------------------

HEATING_TYPE_FLOOR = "floor"
HEATING_TYPE_RADIATOR = "radiator"
HEATING_TYPES = [HEATING_TYPE_FLOOR, HEATING_TYPE_RADIATOR]

CONTROL_MODE_PID = "pid"
CONTROL_MODE_PWM = "pwm"
CONTROL_MODE_BINARY = "binary"
CONTROL_MODE_PROPORTIONAL = "proportional"


@dataclass(frozen=True)
class HeatingProfile:
    """Default parameters for a heating type."""

    kp: float  # % demand per K
    ki: float  # % demand per (K * s)
    horizon_s: float  # prediction horizon (roughly the dead time)
    interval_s: int  # control / valve update interval
    slope_window_s: float  # window for the temperature trend
    integration_band: float  # |error| in K within which the integral learns
    pwm_period_s: int  # period for the PWM mode
    ff_learn_tau_s: float  # time constant for feed-forward learning


PROFILES: dict[str, HeatingProfile] = {
    # Screed floor heating (ClouSet Multi SK / HK). Ti = kp/ki = 4 h.
    # Tuned in tests/sim_clouset.py across fast/slow rooms and valve curves.
    HEATING_TYPE_FLOOR: HeatingProfile(
        kp=25.0,
        ki=25.0 / (4 * 3600),
        horizon_s=45 * 60,
        interval_s=15 * 60,
        slope_window_s=60 * 60,
        integration_band=0.8,
        pwm_period_s=60 * 60,
        ff_learn_tau_s=24 * 3600,
    ),
    # Radiator / towel radiator. Ti = 40 min.
    HEATING_TYPE_RADIATOR: HeatingProfile(
        kp=25.0,
        ki=25.0 / (40 * 60),
        horizon_s=12 * 60,
        interval_s=5 * 60,
        slope_window_s=20 * 60,
        integration_band=1.0,
        pwm_period_s=20 * 60,
        ff_learn_tau_s=12 * 3600,
    ),
}


def get_profile(heating_type: str | None) -> HeatingProfile:
    """Return the profile for a heating type (floor as safe default)."""
    return PROFILES.get(heating_type or HEATING_TYPE_FLOOR, PROFILES[HEATING_TYPE_FLOOR])


# Gains that earlier versions wrote into the options as defaults. When the
# stored gains match one of these sets they were never tuned by the user and
# are replaced by the profile defaults during migration.
LEGACY_DEFAULT_GAINS: tuple[tuple[float, float, float], ...] = (
    (10.0, 0.005, 0.0),
    (20.0, 0.01, 500.0),
    (3.0, 0.0, 0.0),
    (3.0, 0.005, 0.0),
    (10.0, 0.01, 0.0),
)


def is_legacy_default_gains(kp: Any, ki: Any, kd: Any) -> bool:
    """Return True if the given gains are an untouched legacy default."""
    try:
        kp_f, ki_f, kd_f = float(kp), float(ki), float(kd)
    except (TypeError, ValueError):
        return True
    for lkp, lki, lkd in LEGACY_DEFAULT_GAINS:
        if abs(kp_f - lkp) < 1e-9 and abs(ki_f - lki) < 1e-9 and abs(kd_f - lkd) < 1e-9:
            return True
    return False


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a value into [low, high]."""
    return max(low, min(high, value))


class TemperatureTrend:
    """Trend estimator (linear regression over a sliding time window).

    Temperature sensors report on change only (0.1 K steps). A regression over
    the window gives a smooth value and a slope that is robust against the
    quantisation, as long as we assume the value is held between reports.
    """

    def __init__(self, window_s: float, max_samples: int = 240) -> None:
        self.window_s = window_s
        self.max_samples = max_samples
        self._samples: list[tuple[float, float]] = []

    def add(self, ts: float, value: float) -> None:
        """Add a sample (timestamp in seconds, value in °C)."""
        if self._samples and ts < self._samples[-1][0]:
            # Clock went backwards - start over instead of producing garbage.
            self._samples.clear()
        if self._samples and ts - self._samples[-1][0] < 1.0:
            self._samples[-1] = (ts, value)
        else:
            self._samples.append((ts, value))
        self._trim(ts)

    def _trim(self, now: float) -> None:
        # Keep one sample older than the window so the held value at the window
        # start is known.
        cutoff = now - self.window_s
        while len(self._samples) > 2 and self._samples[1][0] <= cutoff:
            self._samples.pop(0)
        if len(self._samples) > self.max_samples:
            self._samples = self._samples[-self.max_samples :]

    def clear(self) -> None:
        """Forget all samples."""
        self._samples.clear()

    @property
    def last(self) -> float | None:
        """Return the last raw value."""
        return self._samples[-1][1] if self._samples else None

    @property
    def last_ts(self) -> float | None:
        """Return the timestamp of the last raw value."""
        return self._samples[-1][0] if self._samples else None

    def estimate(self, now: float) -> tuple[float | None, float]:
        """Return (smoothed temperature at ``now``, slope in K/h).

        The signal is treated as a step function (value held until the next
        report) and sampled on a regular grid, then a least squares line is
        fitted. Too little history yields slope 0.
        """
        if not self._samples:
            return None, 0.0
        start = now - self.window_s
        first_ts = self._samples[0][0]
        if first_ts > start:
            start = first_ts
        span = now - start
        if span < min(600.0, self.window_s / 3):
            return self._samples[-1][1], 0.0

        steps = 30
        step = span / steps
        xs: list[float] = []
        ys: list[float] = []
        idx = 0
        n = len(self._samples)
        for k in range(steps + 1):
            t = start + k * step
            while idx + 1 < n and self._samples[idx + 1][0] <= t:
                idx += 1
            xs.append(t - now)
            ys.append(self._samples[idx][1])

        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        sxx = sum((x - mean_x) ** 2 for x in xs)
        if sxx <= 0:
            return self._samples[-1][1], 0.0
        sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        slope_per_s = sxy / sxx
        # Value of the fitted line at "now" (x = 0), but never further than
        # 0.15 K away from the last measurement - the fit lags on fresh steps.
        fitted = mean_y - slope_per_s * mean_x
        last = self._samples[-1][1]
        smoothed = clamp(fitted, last - 0.15, last + 0.15)
        return smoothed, slope_per_s * 3600.0


# --------------------------------------------------------------------------
# Controller
# --------------------------------------------------------------------------


@dataclass
class ControllerSettings:
    """Tunable settings (may change at runtime)."""

    heating_type: str = HEATING_TYPE_FLOOR
    kp: float = PROFILES[HEATING_TYPE_FLOOR].kp
    ki: float = PROFILES[HEATING_TYPE_FLOOR].ki
    kd: float = 0.0  # % per (K/h) of slope, extra damping, default off
    ka: float = 0.0  # manual feed-forward %/K; 0 = learn automatically
    horizon_s: float = PROFILES[HEATING_TYPE_FLOOR].horizon_s
    hysteresis: float = 0.15
    adaptive_ff: bool = True

    @property
    def profile(self) -> HeatingProfile:
        return get_profile(self.heating_type)


@dataclass
class ControllerResult:
    """Result of one controller step."""

    demand: float  # 0-100 % heating demand of the room
    error: float
    predicted_error: float
    temperature: float | None
    slope: float  # K/h
    p: float
    i: float
    d: float
    ff: float
    learning: bool
    no_heat_supply: bool
    reason: str = ""


@dataclass
class RoomController:
    """Shared controller for all circuits of one room and heating type."""

    key: str
    settings: ControllerSettings = field(default_factory=ControllerSettings)
    integral: float = 0.0  # % contribution of the I-term
    ff_coeff: float | None = None  # learned % per K indoor/outdoor difference
    last_time: float | None = None
    last_result: ControllerResult | None = None
    frozen: bool = False  # window open, exercise, ...
    # heat supply supervision
    _saturated_since: float | None = None
    no_heat_supply: bool = False
    _outside_filtered: float | None = None
    _outside_ts: float | None = None

    def __post_init__(self) -> None:
        self.trend = TemperatureTrend(self.settings.profile.slope_window_s)

    # --- configuration -------------------------------------------------
    def apply_settings(self, settings: ControllerSettings) -> None:
        """Apply new settings, keeping learned state."""
        old_window = self.settings.profile.slope_window_s
        self.settings = settings
        new_window = settings.profile.slope_window_s
        if new_window != old_window:
            self.trend.window_s = new_window

    # --- inputs --------------------------------------------------------
    def add_temperature(self, ts: float, value: float) -> None:
        """Feed a room temperature measurement."""
        self.trend.add(ts, value)

    def add_outside_temperature(self, ts: float, value: float) -> None:
        """Feed an outside temperature measurement (low-pass filtered, 2 h)."""
        if self._outside_filtered is None or self._outside_ts is None:
            self._outside_filtered = value
        else:
            dt = max(0.0, ts - self._outside_ts)
            alpha = clamp(dt / 7200.0, 0.0, 1.0)
            self._outside_filtered += alpha * (value - self._outside_filtered)
        self._outside_ts = ts

    @property
    def outside_temperature(self) -> float | None:
        return self._outside_filtered

    # --- persistence ---------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        """Serialise learned state."""
        return {
            "integral": round(self.integral, 4),
            "ff_coeff": None if self.ff_coeff is None else round(self.ff_coeff, 5),
            "heating_type": self.settings.heating_type,
        }

    def restore(self, data: dict[str, Any] | None) -> None:
        """Restore learned state."""
        if not data:
            return
        try:
            self.integral = clamp(float(data.get("integral", 0.0)), -50.0, 100.0)
        except (TypeError, ValueError):
            self.integral = 0.0
        coeff = data.get("ff_coeff")
        try:
            self.ff_coeff = None if coeff is None else clamp(float(coeff), 0.0, 10.0)
        except (TypeError, ValueError):
            self.ff_coeff = None

    def reset_learning(self) -> None:
        """Forget the integral and the learned feed-forward."""
        self.integral = 0.0
        self.ff_coeff = None
        self.no_heat_supply = False
        self._saturated_since = None

    # --- main step -----------------------------------------------------
    def feed_forward(self, target: float) -> float:
        """Current weather feed-forward in % for a target temperature."""
        return self._feed_forward(target)

    def _feed_forward(self, target: float) -> float:
        outside = self._outside_filtered
        if outside is None:
            return 0.0
        delta = target - outside
        if delta <= 0:
            return 0.0
        s = self.settings
        if s.ka > 0:
            return s.ka * delta
        if s.adaptive_ff and self.ff_coeff is not None:
            return self.ff_coeff * delta
        return 0.0

    def compute(
        self,
        now: float,
        target: float,
        *,
        heating_enabled: bool = True,
        mode: str = CONTROL_MODE_PID,
    ) -> ControllerResult:
        """Run one control step and return the room demand in percent."""
        s = self.settings
        profile = s.profile
        temp, slope = self.trend.estimate(now)

        dt = 0.0 if self.last_time is None else max(0.0, now - self.last_time)
        self.last_time = now

        if temp is None:
            result = ControllerResult(
                demand=0.0,
                error=0.0,
                predicted_error=0.0,
                temperature=None,
                slope=0.0,
                p=0.0,
                i=self.integral,
                d=0.0,
                ff=0.0,
                learning=False,
                no_heat_supply=self.no_heat_supply,
                reason="no_temperature",
            )
            self.last_result = result
            return result

        slope = clamp(slope, -3.0, 3.0)
        error = target - temp
        horizon_h = s.horizon_s / 3600.0
        # Limit how far we look ahead so a sensor glitch cannot flip the output.
        predicted_shift = clamp(slope * horizon_h, -1.0, 1.0)
        predicted_error = target - (temp + predicted_shift)

        if mode == CONTROL_MODE_PROPORTIONAL:
            demand = clamp(error / 3.0 * 100.0, 0.0, 100.0)
            if error < -s.hysteresis:
                demand = 0.0
            result = ControllerResult(
                demand=demand,
                error=error,
                predicted_error=predicted_error,
                temperature=temp,
                slope=slope,
                p=demand,
                i=0.0,
                d=0.0,
                ff=0.0,
                learning=False,
                no_heat_supply=self.no_heat_supply,
                reason="proportional",
            )
            self.last_result = result
            return result

        if mode == CONTROL_MODE_BINARY:
            previous_on = bool(self.last_result and self.last_result.demand > 0)
            if predicted_error > s.hysteresis:
                on = True
            elif predicted_error < -s.hysteresis:
                on = False
            else:
                on = previous_on
            demand = 100.0 if on else 0.0
            result = ControllerResult(
                demand=demand,
                error=error,
                predicted_error=predicted_error,
                temperature=temp,
                slope=slope,
                p=demand,
                i=0.0,
                d=0.0,
                ff=0.0,
                learning=False,
                no_heat_supply=self.no_heat_supply,
                reason="binary",
            )
            self.last_result = result
            return result

        # PID (and PWM, which uses the same demand)
        p_term = s.kp * predicted_error
        d_term = -s.kd * slope  # kd in % per K/h
        ff_term = self._feed_forward(target)

        unclamped = p_term + self.integral + d_term + ff_term

        learning = False
        can_learn = heating_enabled and not self.frozen and 0 < dt <= 3 * profile.interval_s
        # Conditional integration: learn freely close to the set-point. Further
        # away only learn while the room is not already moving towards the
        # target by itself (otherwise a heat-up after a set-back would wind the
        # integral up and overshoot later), and then at half the rate.
        in_band = abs(error) <= profile.integration_band
        stuck = (error > 0 and slope < 0.1) or (error < 0 and slope > -0.1)
        if can_learn and not self.no_heat_supply and (in_band or stuck):
            # Anti-windup: do not integrate further into a saturated output.
            pushing_up = error > 0 and unclamped >= 100.0
            pushing_down = error < 0 and unclamped <= 0.0
            if not (pushing_up or pushing_down):
                rate = 1.0 if in_band else 0.5
                self.integral += s.ki * error * dt * rate
                learning = True
        # The integral alone may never exceed the actuator range.
        self.integral = clamp(self.integral, -50.0, 100.0)

        demand_unclamped = p_term + self.integral + d_term + ff_term
        demand = clamp(demand_unclamped, 0.0, 100.0)

        # Hard over-temperature cut-off (also in PID mode) so a strong sun
        # gain closes the valve even if the integral is high.
        overtemp_limit = max(0.5, 2.0 * s.hysteresis)
        reason = "pid"
        if error < -overtemp_limit and predicted_error < -overtemp_limit:
            demand = 0.0
            reason = "over_temperature"

        if can_learn:
            self._supervise_supply(now, demand, error, slope)
            self._learn_feed_forward(dt, target, demand, error, slope, ff_term)

        result = ControllerResult(
            demand=demand,
            error=error,
            predicted_error=predicted_error,
            temperature=temp,
            slope=slope,
            p=p_term,
            i=self.integral,
            d=d_term,
            ff=ff_term,
            learning=learning,
            no_heat_supply=self.no_heat_supply,
            reason=reason,
        )
        self.last_result = result
        return result

    def _supervise_supply(self, now: float, demand: float, error: float, slope: float) -> None:
        """Detect that the valve is open but no heat arrives (boiler off)."""
        if demand >= 80.0 and error > 0.5:
            if self._saturated_since is None:
                self._saturated_since = now
            elif now - self._saturated_since > 3 * 3600 and slope <= 0.05:
                if not self.no_heat_supply:
                    self.no_heat_supply = True
        else:
            self._saturated_since = None
        if self.no_heat_supply and (slope > 0.2 or demand < 50.0):
            self.no_heat_supply = False
            self._saturated_since = None

    def _learn_feed_forward(
        self,
        dt: float,
        target: float,
        demand: float,
        error: float,
        slope: float,
        ff_term: float,
    ) -> None:
        """Learn % demand per K indoor/outdoor difference in quiet phases."""
        s = self.settings
        if s.ka > 0 or not s.adaptive_ff:
            return
        outside = self._outside_filtered
        if outside is None or self.no_heat_supply:
            return
        delta = target - outside
        if delta < 5.0:
            return  # too warm outside, the ratio is meaningless
        if abs(error) > 0.25 or abs(slope) > 0.15 or demand <= 0.0 or demand >= 100.0:
            return
        observed = clamp(demand / delta, 0.0, 10.0)
        if self.ff_coeff is None:
            # Start conservatively at half of what is observed; the integral
            # keeps the rest so the output stays continuous.
            new_coeff = observed * 0.5
        else:
            alpha = clamp(dt / s.profile.ff_learn_tau_s, 0.0, 0.2)
            new_coeff = self.ff_coeff + alpha * (observed - self.ff_coeff)
        new_ff = new_coeff * delta
        # Bumpless: move the same amount out of the integral.
        self.integral = clamp(self.integral - (new_ff - ff_term), -50.0, 100.0)
        self.ff_coeff = new_coeff


# --------------------------------------------------------------------------
# Output stage: demand -> valve opening
# --------------------------------------------------------------------------


def demand_to_opening(
    demand: float,
    max_opening: int,
    *,
    share: float = 1.0,
    min_opening: int = 0,
    close_below: float = 2.0,
) -> int:
    """Map a room demand (0-100 %) to a TRV opening degree (0-100 %).

    ``max_opening`` is the configured valve step (e.g. 40 % for step 2),
    ``share`` weights this circuit within the room and ``min_opening`` is the
    opening at which the valve actually starts to pass water.
    """
    if max_opening <= 0:
        return 0
    effective = clamp(demand * clamp(share, 0.0, 2.0), 0.0, 100.0)
    if effective < close_below:
        return 0
    low = clamp(min_opening, 0, max_opening)
    opening = low + (max_opening - low) * effective / 100.0
    return int(round(clamp(opening, 1 if low == 0 else low, max_opening)))


def pwm_on_seconds(demand: float, period_s: float, min_switch_s: float = 300.0) -> float:
    """Return the on-time within a PWM period for a demand in percent."""
    on = clamp(demand, 0.0, 100.0) / 100.0 * period_s
    if on < min_switch_s:
        return 0.0
    if period_s - on < min_switch_s:
        return period_s
    return on
