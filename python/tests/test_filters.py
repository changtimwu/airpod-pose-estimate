import pytest

from airpod_pose import quaternion as quat
from airpod_pose.calibration import Calibrator
from airpod_pose.filters import Derivative, ExponentialFilter, QuaternionFilter
from airpod_pose.model import Sample


def make_sample(q, t=0.0, seq=0):
    return Sample(t=t, wall=0.0, seq=seq, q=q, rot=(0, 0, 0), acc=(0, 0, 0), grav=(0, -1, 0))


def test_exponential_filter_starts_at_first_value():
    f = ExponentialFilter(alpha=0.5)
    assert f.update(10.0) == 10.0
    assert f.update(20.0) == pytest.approx(15.0)


def test_exponential_filter_converges():
    f = ExponentialFilter(alpha=0.5)
    for _ in range(40):
        f.update(5.0)
    assert f.value == pytest.approx(5.0, abs=1e-6)


def test_exponential_filter_rejects_bad_alpha():
    with pytest.raises(ValueError):
        ExponentialFilter(alpha=0.0)


def test_quaternion_filter_lags_toward_target():
    f = QuaternionFilter(alpha=0.5)
    f.update(quat.from_euler(0, 0, 0))
    yaw, _, _ = quat.to_euler(f.update(quat.from_euler(40, 0, 0)))
    assert yaw == pytest.approx(20, abs=1e-6)


def test_derivative_is_wrap_aware():
    d = Derivative()
    d.update(179.0, 0.0)
    # 179 -> -179 is +2 deg across the wrap, not -358.
    assert d.update(-179.0, 1.0) == pytest.approx(2.0)


def test_derivative_ignores_non_monotonic_time():
    d = Derivative()
    d.update(0.0, 1.0)
    assert d.update(10.0, 1.0) == 0.0


def test_calibrator_needs_a_full_window():
    c = Calibrator(window=3)
    assert c.feed(make_sample(quat.from_euler(10, 0, 0))) is False
    assert c.progress == pytest.approx(1 / 3)
    c.feed(make_sample(quat.from_euler(10, 0, 0)))
    assert c.feed(make_sample(quat.from_euler(10, 0, 0))) is True
    assert c.is_calibrated


def test_calibrator_zeroes_the_reference_pose():
    c = Calibrator(window=3)
    reference = quat.from_euler(35, -10, 5)
    for _ in range(3):
        c.feed(make_sample(reference))
    assert quat.to_euler(c.apply(reference)) == pytest.approx((0, 0, 0), abs=1e-6)


def test_calibrator_rejects_a_moving_window():
    c = Calibrator(window=4, max_spread_deg=5.0)
    for yaw in (0, 30, 60, 90):
        assert c.feed(make_sample(quat.from_euler(yaw, 0, 0))) is False
    assert not c.is_calibrated


def test_apply_is_identity_before_calibration():
    c = Calibrator(window=10)
    q = quat.from_euler(12, 3, 4)
    assert c.apply(q) == pytest.approx(q)
