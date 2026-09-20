"""Band matching for the yoga poses, including the mirrored side bend.

`poses.py` is SIGNAL's, and arrived without tests. These cover the behaviour
the live demo depends on: which head positions count, that the hysteresis
margin keeps a settling body in the pose, and that a symmetric pose matches on
either side without needing a second pose id.
"""

import pytest

from airpod_pose.poses import PoseConfig, PoseDef, PoseMatcher

LEVEL = -90.0  # server.py defines the calibration pose as pitch -90


def triangle():
    return PoseDef.from_dict("triangle", {
        "label_en": "Triangle", "label_sa": "Trikonasana", "hold_ms": 5000,
        "pitch": [-145, -35], "roll": [15, 90], "exit_margin_deg": 12,
        "mirror_roll": True,
    })


@pytest.mark.parametrize("roll,expected", [
    (0, False),     # head level: not the pose
    (10, False),    # a lean, not a tilt
    (20, True),     # tilted right
    (45, True),
    (-20, True),    # and the same tilt to the left
    (-45, True),
    (-10, False),
    (120, False),   # past anything a neck does
])
def test_mirrored_band_matches_either_side(roll, expected):
    assert triangle().contains(LEVEL, roll) is expected


def test_pitch_is_dont_care_within_the_band():
    pose = triangle()
    assert pose.contains(LEVEL - 40, 30) is True   # looking down while tilted
    assert pose.contains(LEVEL + 40, 30) is True   # looking up while tilted
    assert pose.contains(LEVEL + 70, 30) is False  # past the band


def test_error_is_symmetric_about_zero_roll():
    pose = triangle()
    assert pose.error_deg(LEVEL, 40) == pytest.approx(pose.error_deg(LEVEL, -40))


def test_error_falls_as_you_approach_the_band_centre():
    pose = triangle()
    assert pose.error_deg(LEVEL, 52) < pose.error_deg(LEVEL, 20) < pose.error_deg(LEVEL, 0)


def test_without_the_flag_only_one_side_matches():
    pose = PoseDef.from_dict("one_sided", {
        "label_en": "One sided", "hold_ms": 1000, "pitch": [-145, -35], "roll": [15, 90],
    })
    assert pose.contains(LEVEL, 40) is True
    assert pose.contains(LEVEL, -40) is False


def test_exit_margin_keeps_a_settling_head_in_the_pose():
    """Entering is strict, leaving is not -- otherwise the pose strobes."""
    matcher = PoseMatcher(PoseConfig.load())
    assert matcher.update(LEVEL, 40, "triangle")[0] is True
    assert matcher.update(LEVEL, 10, "triangle")[0] is True   # inside the margin
    assert matcher.update(LEVEL, 0, "triangle")[0] is False   # genuinely upright


def test_shipped_config_is_the_single_pose_demo():
    config = PoseConfig.load()
    assert config.sequence == ["triangle"]
    assert config["triangle"].mirror_roll is True
