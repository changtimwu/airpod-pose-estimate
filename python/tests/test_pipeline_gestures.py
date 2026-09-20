"""End-to-end checks over the synthetic source.

These are the tests that tell us a refactor did not break the chain
source -> pipeline -> gestures, without needing AirPods in CI.
"""

import pytest

from airpod_pose import sources
from airpod_pose.gestures import GestureRecognizer, HoldDetector, OscillationDetector
from airpod_pose.model import HeadPose
from airpod_pose.pipeline import PosePipeline


def synthetic_poses(duration=12.0, **kwargs):
    source = sources.SyntheticSource(duration=duration, realtime=False, **kwargs)
    pipeline = PosePipeline(calibration_window=5)
    return list(pipeline.run(sources.samples(source)))


def test_synthetic_source_emits_samples():
    records = list(sources.SyntheticSource(duration=2.0, realtime=False).records())
    samples = [r for r in records if r.get("type") == "sample"]
    assert len(samples) == 50  # 2 s at 25 Hz
    assert all(len(r["q"]) == 4 for r in samples)


def test_pipeline_yields_poses_after_calibration():
    poses = synthetic_poses(duration=4.0)
    assert poses, "pipeline produced no poses"
    assert all(isinstance(p, HeadPose) for p in poses)
    # The sample that completes the calibration window still yields a pose,
    # so only window-1 samples are consumed.
    assert len(poses) == 100 - (5 - 1)


def test_pipeline_starts_near_zero_after_calibration():
    first = synthetic_poses(duration=4.0)[0]
    assert abs(first.yaw) < 5.0
    assert abs(first.pitch) < 5.0
    assert abs(first.roll) < 5.0


def test_recognizer_finds_the_scripted_gestures():
    events = []
    recognizer = GestureRecognizer()
    for pose in synthetic_poses():
        events.extend(recognizer.feed(pose))
    names = {e.name for e in events}
    assert "nod" in names
    assert "shake" in names
    assert "look_left" in names
    assert all(0.0 <= e.confidence <= 1.0 for e in events)


def test_idle_motion_does_not_fire_gestures():
    # No script: only the slow wander. A drifting head must not trigger anything.
    events = []
    recognizer = GestureRecognizer()
    for pose in synthetic_poses(duration=20.0, script=()):
        events.extend(recognizer.feed(pose))
    assert events == []


def test_oscillation_detector_needs_a_return_swing():
    detector = OscillationDetector("shake", axis="yaw", rate_threshold=50.0)
    # One-way turn at constant rate: no sign change, so no event.
    fired = [detector.feed(_pose(t=i * 0.04, yaw_rate=120.0)) for i in range(40)]
    assert not any(fired)


def test_oscillation_detector_fires_on_alternating_swings():
    detector = OscillationDetector("shake", axis="yaw", rate_threshold=50.0, required_swings=2)
    events = []
    for i in range(30):
        rate = 150.0 if (i // 4) % 2 == 0 else -150.0
        event = detector.feed(_pose(t=i * 0.04, yaw_rate=rate))
        if event:
            events.append(event)
    assert events, "alternating swings should fire"


def test_hold_detector_respects_the_dwell_time():
    detector = HoldDetector("look_left", axis="yaw", threshold=25.0, hold_s=0.5)
    assert detector.feed(_pose(t=0.0, yaw=40.0)) is None
    assert detector.feed(_pose(t=0.2, yaw=40.0)) is None
    assert detector.feed(_pose(t=0.6, yaw=40.0)) is not None


def test_hold_detector_resets_when_the_head_returns():
    detector = HoldDetector("look_left", axis="yaw", threshold=25.0, hold_s=0.5)
    detector.feed(_pose(t=0.0, yaw=40.0))
    detector.feed(_pose(t=0.3, yaw=0.0))  # back to center: timer restarts
    assert detector.feed(_pose(t=0.7, yaw=40.0)) is None


def test_recognizer_reset_clears_detector_state():
    recognizer = GestureRecognizer([HoldDetector("hold", axis="yaw", threshold=10.0, hold_s=0.2)])
    recognizer.feed(_pose(t=0.0, yaw=30.0))
    recognizer.reset()
    assert recognizer.feed(_pose(t=0.3, yaw=30.0)) == []


def test_file_replay_roundtrip(tmp_path):
    path = tmp_path / "session.jsonl"
    records = list(sources.SyntheticSource(duration=3.0, realtime=False).records())
    with path.open("w") as handle:
        for record in records:
            handle.write(__import__("json").dumps(record) + "\n")

    replayed = list(sources.FileSource(path, realtime=False).records())
    assert len(replayed) == len(records)
    poses = list(PosePipeline(calibration_window=5).run(sources.samples(sources.FileSource(path))))
    assert len(poses) == 75 - (5 - 1)


def _pose(t, yaw=0.0, pitch=0.0, roll=0.0, yaw_rate=0.0, pitch_rate=0.0, roll_rate=0.0):
    return HeadPose(
        t=t,
        q=(1.0, 0.0, 0.0, 0.0),
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        yaw_rate=yaw_rate,
        pitch_rate=pitch_rate,
        roll_rate=roll_rate,
    )


def test_oscillation_event_reports_its_peak_rate():
    detector = OscillationDetector("shake", axis="yaw", rate_threshold=50.0, required_swings=2)
    event = None
    for i in range(30):
        rate = 200.0 if (i // 4) % 2 == 0 else -200.0
        event = detector.feed(_pose(t=i * 0.04, yaw_rate=rate)) or event
    assert event is not None
    assert "peak_rate=200" in event.detail
    assert event.confidence > 0.0
