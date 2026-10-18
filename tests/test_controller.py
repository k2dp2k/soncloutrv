"""Unit tests for the room controller (no Home Assistant needed)."""
from __future__ import annotations

from custom_components.soncloutrv.controller import (
    CONTROL_MODE_BINARY,
    ControllerSettings,
    RoomController,
    TemperatureTrend,
    demand_to_opening,
    is_legacy_default_gains,
    pwm_on_seconds,
)


def test_trend_slope_and_hold():
    trend = TemperatureTrend(3600)
    # 0.1 K steps every 12 minutes -> 0.5 K/h
    for i in range(6):
        trend.add(i * 720.0, 20.0 + i * 0.1)
    value, slope = trend.estimate(3600.0)
    assert 0.3 < slope < 0.7
    assert abs(value - 20.5) <= 0.15
    # held value without new reports -> slope decays towards 0
    _, slope_later = trend.estimate(3 * 3600.0)
    assert abs(slope_later) < 0.05


def test_integral_is_kept_at_setpoint():
    """The old controller decayed the integral near the set-point (limit cycle)."""
    ctrl = RoomController("r")
    ctrl.integral = 30.0
    now = 0.0
    for _ in range(20):
        ctrl.add_temperature(now, 21.5)
        res = ctrl.compute(now, 21.5)
        now += 900
    assert res.demand > 25.0
    assert abs(ctrl.integral - 30.0) < 1.0


def test_prediction_closes_before_overshoot():
    ctrl = RoomController("r")
    ctrl.integral = 20.0
    # rising 0.6 K/h, still 0.2 K below target
    for i in range(7):
        ctrl.add_temperature(i * 600.0, 20.7 + i * 0.1)
    res = ctrl.compute(3600.0, 21.5)
    assert res.predicted_error < res.error
    no_pred = RoomController("r2", settings=ControllerSettings(horizon_s=0))
    no_pred.integral = 20.0
    for i in range(7):
        no_pred.add_temperature(i * 600.0, 20.7 + i * 0.1)
    res2 = no_pred.compute(3600.0, 21.5)
    assert res.demand < res2.demand


def test_anti_windup_and_no_supply():
    ctrl = RoomController("r")
    now = 0.0
    for _ in range(40):  # 10 h cold, valve saturated, no temperature rise
        ctrl.add_temperature(now, 18.0)
        ctrl.compute(now, 21.5)
        now += 900
    assert ctrl.integral <= 100.0
    assert ctrl.no_heat_supply is True


def test_overtemperature_cutoff():
    ctrl = RoomController("r")
    ctrl.integral = 60.0
    for i in range(4):
        ctrl.add_temperature(i * 900.0, 22.3)
    res = ctrl.compute(3600.0, 21.5)
    assert res.demand == 0.0
    assert res.reason == "over_temperature"


def test_cutoff_unlearns_positive_integral_but_not_below_zero():
    """Summer / sun: a high integral is reduced, but never driven far negative."""
    ctrl = RoomController("r")
    ctrl.integral = 60.0
    now = 0.0
    for _ in range(8):  # 2 h at +0.8 K
        ctrl.add_temperature(now, 22.3)
        ctrl.compute(now, 21.5)
        now += 900
    assert ctrl.integral < 60.0
    # weeks of over-temperature (heating left on in summer)
    for _ in range(4 * 24 * 14):
        ctrl.add_temperature(now, 24.0)
        res = ctrl.compute(now, 21.5)
        now += 900
    assert res.demand == 0.0
    assert ctrl.integral >= -0.01
    # a normal winter day afterwards starts from a neutral integral: the room
    # cools down at a realistic 0.3 K/h and the valve opens below the target
    temp = 24.0
    while temp > 20.9:
        temp -= 0.075
        ctrl.add_temperature(now, round(temp, 2))
        res = ctrl.compute(now, 21.5)
        now += 900
    assert res.demand > 0


def test_rate_limiter_ignores_drafts_but_follows_real_cooling():
    """Screed floors cannot move the air faster than ~0.8 K/h."""
    ctrl = RoomController("r")
    ctrl.integral = 10.0
    now = 0.0
    for _ in range(8):
        ctrl.add_temperature(now, 21.5)
        ctrl.compute(now, 21.5)
        now += 900
    integral = ctrl.integral
    # a draft: the air drops by 2 K within one cycle
    ctrl.add_temperature(now - 300, 19.5)
    res = ctrl.compute(now, 21.5)
    assert res.disturbance is True
    assert res.temperature == 21.5 - 0.2  # 0.8 K/h * 15 min
    assert res.demand < 30.0  # the old controller asked for ~85 %
    assert ctrl.integral == integral  # nothing learned from the draft
    # the air recovers by itself -> back to normal
    ctrl.add_temperature(now + 600, 21.5)
    res = ctrl.compute(now + 900, 21.5)
    assert res.disturbance is False
    # a radiator profile is not limited
    rad = RoomController("x", settings=ControllerSettings(heating_type="radiator"))
    rad.add_temperature(0, 21.5)
    rad.compute(0, 21.5)
    rad.add_temperature(300, 19.5)
    assert abs(rad.compute(600, 21.5).temperature - 19.5) <= 0.15  # trend smoothing only


def test_stale_integral_is_unlearned_while_room_stays_warm():
    """Neighbours heat the room: the closed valve must not keep a high integral."""
    ctrl = RoomController("r")
    ctrl.integral = 13.0
    now = 0.0
    for _ in range(4 * 12):  # 12 h at +1.2 K, valve shut
        ctrl.add_temperature(now, 23.7)
        res = ctrl.compute(now, 22.5)
        now += 900
    assert res.demand == 0.0
    assert ctrl.integral < 3.0
    assert ctrl.integral >= 0.0


def test_binary_mode_hysteresis():
    ctrl = RoomController("r", settings=ControllerSettings(hysteresis=0.3))
    ctrl.add_temperature(0, 20.0)
    assert ctrl.compute(0, 21.5, mode=CONTROL_MODE_BINARY).demand == 100.0
    ctrl.add_temperature(3600, 21.6)
    # inside band -> keep state
    assert ctrl.compute(3600, 21.5, mode=CONTROL_MODE_BINARY).demand == 100.0


def test_feed_forward_learning_is_bumpless():
    ctrl = RoomController("r")
    ctrl.integral = 40.0
    ctrl.add_outside_temperature(0, 1.5)
    now = 0.0
    last_demand = None
    for _ in range(12):
        ctrl.add_temperature(now, 21.5)
        res = ctrl.compute(now, 21.5)
        if last_demand is not None:
            assert abs(res.demand - last_demand) < 2.0
        last_demand = res.demand
        now += 900
    assert ctrl.ff_coeff is not None and ctrl.ff_coeff > 0


def test_persistence_roundtrip():
    ctrl = RoomController("r")
    ctrl.integral = 12.3
    ctrl.ff_coeff = 1.5
    other = RoomController("r")
    other.restore(ctrl.as_dict())
    assert other.integral == 12.3 and other.ff_coeff == 1.5
    other.restore({"integral": "garbage", "ff_coeff": "x"})
    assert other.integral == 0.0 and other.ff_coeff is None
    # a stored value from an older version is clamped into the new bounds
    other.restore({"integral": -50.0, "ff_coeff": None})
    assert other.integral == -25.0


def test_demand_to_opening():
    assert demand_to_opening(0, 40) == 0
    assert demand_to_opening(1.0, 40) == 0
    assert demand_to_opening(100, 40) == 40
    assert demand_to_opening(50, 40) == 20
    assert demand_to_opening(5, 40, min_opening=8) >= 8
    assert demand_to_opening(50, 0) == 0
    assert demand_to_opening(80, 40, share=2.0) == 40


def test_pwm_on_seconds():
    assert pwm_on_seconds(0, 3600) == 0
    assert pwm_on_seconds(5, 3600) == 0  # below minimum switching time
    assert pwm_on_seconds(50, 3600) == 1800
    assert pwm_on_seconds(95, 3600) == 3600


def test_legacy_gain_detection():
    assert is_legacy_default_gains(10.0, 0.005, 0.0)
    assert is_legacy_default_gains(20, 0.01, 500)
    assert not is_legacy_default_gains(15.0, 0.002, 0.0)
