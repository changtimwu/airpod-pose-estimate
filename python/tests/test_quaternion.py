import math

import pytest

from airpod_pose import quaternion as quat
from airpod_pose.quaternion import FORWARD, LEFT, UP


@pytest.mark.parametrize(
    "euler",
    [(0, 0, 0), (30, 0, 0), (0, 25, 0), (0, 0, -45), (10, 20, 30), (170, -40, 15), (-120, 15, -80)],
)
def test_euler_roundtrip(euler):
    yaw, pitch, roll = quat.to_euler(quat.from_euler(*euler))
    assert yaw == pytest.approx(euler[0], abs=1e-6)
    assert pitch == pytest.approx(euler[1], abs=1e-6)
    assert roll == pytest.approx(euler[2], abs=1e-6)


def test_yaw_rotates_forward_vector():
    # Body frame is x=forward, y=left, z=up; +90 deg yaw turns forward to left.
    assert quat.rotate_vector(quat.from_euler(90, 0, 0), FORWARD) == pytest.approx(LEFT, abs=1e-9)


def test_positive_pitch_means_nose_up():
    x, y, z = quat.rotate_vector(quat.from_euler(0, 90, 0), FORWARD)
    assert (x, y, z) == pytest.approx(UP, abs=1e-9)


def test_positive_roll_tips_the_crown_to_the_right():
    right = (0.0, -1.0, 0.0)
    x, y, z = quat.rotate_vector(quat.from_euler(0, 0, 90), UP)
    assert (x, y, z) == pytest.approx(right, abs=1e-9)


def test_relative_cancels_reference():
    reference = quat.from_euler(35, -12, 8)
    assert quat.to_euler(quat.relative(reference, reference)) == pytest.approx((0, 0, 0), abs=1e-9)


def test_relative_reports_offset_from_reference():
    reference = quat.from_euler(35, 0, 0)
    current = quat.multiply(reference, quat.from_euler(20, 0, 0))
    yaw, pitch, roll = quat.to_euler(quat.relative(reference, current))
    assert yaw == pytest.approx(20, abs=1e-6)
    assert (pitch, roll) == pytest.approx((0, 0), abs=1e-6)


def test_angle_between_is_hemisphere_agnostic():
    a = quat.from_euler(0, 0, 0)
    b = quat.from_euler(90, 0, 0)
    assert quat.angle_between(a, b) == pytest.approx(90, abs=1e-6)
    assert quat.angle_between(a, tuple(-v for v in b)) == pytest.approx(90, abs=1e-6)


def test_slerp_midpoint():
    a = quat.from_euler(0, 0, 0)
    b = quat.from_euler(80, 0, 0)
    yaw, _, _ = quat.to_euler(quat.slerp(a, b, 0.5))
    assert yaw == pytest.approx(40, abs=1e-6)


def test_normalize_handles_zero():
    assert quat.normalize((0, 0, 0, 0)) == quat.IDENTITY


def test_gimbal_lock_is_finite():
    yaw, pitch, roll = quat.to_euler(quat.from_euler(0, 90, 0))
    assert pitch == pytest.approx(90, abs=1e-6)
    assert all(math.isfinite(v) for v in (yaw, pitch, roll))


@pytest.mark.parametrize(
    "angle,expected", [(0, 0), (180, 180), (181, -179), (-190, 170), (360, 0), (-180, 180)]
)
def test_wrap_degrees(angle, expected):
    assert quat.wrap_degrees(angle) == pytest.approx(expected)
