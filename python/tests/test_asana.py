"""Tests for held-pose matching.

The interesting cases are the ones that make a live demo look broken: a pose
that flickers at the tolerance edge, a hold timer that resets, a reference
captured while the body was still moving.
"""

import pytest

from airpod_pose import quaternion as quat
from airpod_pose.asana import (
    AsanaLibrary,
    AsanaMatcher,
    PoseTarget,
    Steadiness,
    capture_reference,
)
from airpod_pose.model import HeadPose


def pose_at(t, yaw=0.0, pitch=0.0, roll=0.0, rates=(0.0, 0.0, 0.0)):
    q = quat.from_euler(yaw, pitch, roll)
    y, p, r = quat.to_euler(q)
    return HeadPose(t=t, q=q, yaw=y, pitch=p, roll=r,
                    yaw_rate=rates[0], pitch_rate=rates[1], roll_rate=rates[2])


def library_with(**kwargs):
    target = PoseTarget(name="triangle", reference=quat.from_euler(0, 40, 25),
                        label="Triangle", **kwargs)
    return AsanaLibrary(targets=[target]), target


def test_distance_is_zero_at_the_reference():
    _, target = library_with()
    assert target.distance(target.reference) == pytest.approx(0.0, abs=1e-9)


def test_target_survives_a_json_roundtrip():
    _, target = library_with(tolerance_deg=15.0, hold_s=3.0)
    clone = PoseTarget.from_dict(target.to_dict())
    assert clone.name == target.name
    assert clone.tolerance_deg == 15.0
    assert clone.hold_s == 3.0
    assert clone.reference == pytest.approx(target.reference)


def test_library_saves_and_loads(tmp_path):
    library, target = library_with()
    path = library.save(tmp_path / "asanas.json")
    loaded = AsanaLibrary.load(path)
    assert len(loaded) == 1
    assert loaded.get("triangle") is not None
    assert loaded.get("triangle").reference == pytest.approx(target.reference)


def test_missing_library_loads_empty(tmp_path):
    assert len(AsanaLibrary.load(tmp_path / "nope.json")) == 0


def test_adding_the_same_name_replaces_it():
    library, _ = library_with()
    library.add(PoseTarget(name="triangle", reference=quat.IDENTITY, tolerance_deg=1.0))
    assert len(library) == 1
    assert library.get("triangle").tolerance_deg == 1.0


def test_enters_holds_and_exits():
    library, target = library_with(tolerance_deg=20.0, hold_s=2.0)
    matcher = AsanaMatcher(library)
    kinds = []

    for i in range(200):  # 4 s in the pose at 50 Hz
        _, events = matcher.feed(pose_at(i * 0.02, pitch=40, roll=25))
        kinds += [e.kind for e in events]
    for i in range(50):  # then stand up
        _, events = matcher.feed(pose_at(4.0 + i * 0.02, pitch=0, roll=0))
        kinds += [e.kind for e in events]

    assert kinds == ["enter", "hold", "exit"]


def test_hold_fires_once_not_every_sample():
    library, _ = library_with(hold_s=1.0)
    matcher = AsanaMatcher(library)
    holds = 0
    for i in range(300):
        _, events = matcher.feed(pose_at(i * 0.02, pitch=40, roll=25))
        holds += sum(1 for e in events if e.kind == "hold")
    assert holds == 1


def test_hysteresis_stops_the_edge_from_chattering():
    """A pose parked just past tolerance must not toggle at the sample rate."""
    library, target = library_with(tolerance_deg=20.0, exit_margin_deg=8.0)
    matcher = AsanaMatcher(library)
    matcher.feed(pose_at(0.0, pitch=40, roll=25))  # enter at the reference

    transitions = 0
    for i in range(200):
        # oscillate around the tolerance edge, inside the exit margin
        wobble = 21.0 + 2.0 * (i % 2)
        _, events = matcher.feed(pose_at(1.0 + i * 0.02, pitch=40 + wobble, roll=25))
        transitions += len(events)
    assert transitions == 0
    assert matcher.current is not None


def test_leaving_far_enough_does_exit():
    library, _ = library_with(tolerance_deg=20.0, exit_margin_deg=8.0)
    matcher = AsanaMatcher(library)
    matcher.feed(pose_at(0.0, pitch=40, roll=25))
    _, events = matcher.feed(pose_at(0.5, pitch=100, roll=25))
    assert [e.kind for e in events] == ["exit"]


def test_nearest_target_wins_when_two_overlap():
    a = PoseTarget(name="a", reference=quat.from_euler(0, 0, 0), tolerance_deg=90.0)
    b = PoseTarget(name="b", reference=quat.from_euler(0, 30, 0), tolerance_deg=90.0)
    matcher = AsanaMatcher(AsanaLibrary(targets=[a, b]))
    _, events = matcher.feed(pose_at(0.0, pitch=28))
    assert events[0].name == "b"


def test_steadiness_separates_still_from_moving():
    still, moving = Steadiness(), Steadiness()
    for i in range(50):
        still.update(pose_at(i * 0.02, rates=(0.5, 0.3, 0.2)))
        moving.update(pose_at(i * 0.02, rates=(40.0, 30.0, 20.0)))
    assert still.value < 1.5
    assert moving.value > 45.0


def test_steadiness_forgets_old_samples():
    steady = Steadiness(window_s=0.5)
    for i in range(25):
        steady.update(pose_at(i * 0.02, rates=(100.0, 0.0, 0.0)))
    for i in range(25, 75):
        steady.update(pose_at(i * 0.02, rates=(0.0, 0.0, 0.0)))
    assert steady.value < 1.0


def test_capture_reports_a_small_spread_when_still():
    poses = (pose_at(i * 0.02, pitch=40, roll=25) for i in range(60))
    reference, spread = capture_reference(poses, samples=25)
    assert spread < 0.5
    assert quat.angle_between(reference, quat.from_euler(0, 40, 25)) < 0.5


def test_capture_reports_a_large_spread_when_moving():
    poses = (pose_at(i * 0.02, pitch=40 + i, roll=25) for i in range(60))
    _, spread = capture_reference(poses, samples=25)
    assert spread > 5.0


def test_summary_reports_the_longest_hold():
    library, _ = library_with(hold_s=1.0)
    matcher = AsanaMatcher(library)
    for i in range(150):
        matcher.feed(pose_at(i * 0.02, pitch=40, roll=25))
    matcher.feed(pose_at(3.0, pitch=0, roll=0))  # exit records the hold
    assert "Triangle" in matcher.summary()[0]
    assert matcher.best_holds["triangle"] > 2.9


def test_summary_reports_steadiness_per_pose():
    """The left-vs-right comparison: same pose, two sides, which was calmer."""
    left = PoseTarget(name="triangle_left", reference=quat.from_euler(0, 40, 25),
                      label="Triangle (left)", tolerance_deg=20.0, hold_s=1.0)
    right = PoseTarget(name="triangle_right", reference=quat.from_euler(0, 40, -25),
                       label="Triangle (right)", tolerance_deg=20.0, hold_s=1.0)
    matcher = AsanaMatcher(AsanaLibrary(targets=[left, right]))

    for i in range(150):  # steady on the left
        matcher.feed(pose_at(i * 0.02, pitch=40, roll=25, rates=(2.0, 1.0, 1.0)))
    for i in range(150, 300):  # wobbly on the right
        matcher.feed(pose_at(i * 0.02, pitch=40, roll=-25, rates=(30.0, 20.0, 20.0)))
    matcher.feed(pose_at(6.0, pitch=0, roll=0))

    assert matcher.hold_steadiness["triangle_left"] < matcher.hold_steadiness["triangle_right"]
    summary = "\n".join(matcher.summary())
    assert "wobble" in summary
    assert "steadiest hold: Triangle (left)" in summary


def test_steadiness_is_measured_during_the_hold_not_after():
    target = PoseTarget(name="p", reference=quat.IDENTITY, tolerance_deg=20.0, hold_s=0.5)
    matcher = AsanaMatcher(AsanaLibrary(targets=[target]))
    for i in range(100):
        matcher.feed(pose_at(i * 0.02, rates=(3.0, 0.0, 0.0)))
    matcher.feed(pose_at(5.0, pitch=90))  # thrash on the way out must not count
    assert matcher.hold_steadiness["p"] < 6.0
