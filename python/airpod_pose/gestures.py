"""HeadPose stream -> discrete events.

STATUS: deliberately thin. These three detectors exist to prove the pose stream
is good enough to trigger something, and to give us a shape to write real
detectors into once the team picks a demo. Thresholds are guesses; calibrate
them against recorded sessions (`airpod-pose record`) rather than by feel.

Ideas that need a real model instead of thresholds (template matching, a small
classifier over a sliding window of poses) go in docs/ideas.md.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Iterator, List, Optional

from .model import HeadPose


@dataclass(frozen=True)
class GestureEvent:
    name: str
    t: float
    #: 0..1 rough quality score; currently derived from peak amplitude.
    confidence: float
    detail: str = ""


class GestureDetector:
    """Stateful detector fed one pose at a time."""

    name = "gesture"

    def feed(self, pose: HeadPose) -> Optional[GestureEvent]:
        raise NotImplementedError

    def reset(self) -> None:
        pass


class OscillationDetector(GestureDetector):
    """Detects a there-and-back movement on one axis (nod, shake).

    Mechanism: watch the signed angular rate on the axis, ignore anything below
    `rate_threshold` as drift, and fire when we see `required_swings` sign
    changes within `window_s`. That is enough to separate "shook my head" from
    "turned to look at something", which a pure angle threshold cannot do.
    """

    def __init__(
        self,
        name: str,
        axis: str = "yaw",
        rate_threshold: float = 60.0,
        required_swings: int = 2,
        window_s: float = 1.2,
        # A single physical nod contains several swings; without a cooldown at
        # least as long as the gesture itself it fires two or three times.
        cooldown_s: float = 1.0,
    ) -> None:
        self.name = name
        self.axis = axis
        self.rate_threshold = rate_threshold
        self.required_swings = required_swings
        self.window_s = window_s
        self.cooldown_s = cooldown_s
        self._swings: Deque[float] = deque()
        self._last_sign = 0
        self._peak_rate = 0.0
        self._last_fire = float("-inf")

    def feed(self, pose: HeadPose) -> Optional[GestureEvent]:
        rate = getattr(pose, self.axis + "_rate")
        sign = 0 if abs(rate) < self.rate_threshold else (1 if rate > 0 else -1)

        while self._swings and pose.t - self._swings[0] > self.window_s:
            self._swings.popleft()
        if not self._swings:
            self._peak_rate = 0.0

        if sign != 0:
            self._peak_rate = max(self._peak_rate, abs(rate))
            if self._last_sign != 0 and sign != self._last_sign:
                self._swings.append(pose.t)
            self._last_sign = sign

        if len(self._swings) >= self.required_swings and pose.t - self._last_fire > self.cooldown_s:
            peak = self._peak_rate  # read before reset_swings() clears it
            self._last_fire = pose.t
            self.reset_swings()
            return GestureEvent(
                name=self.name,
                t=pose.t,
                confidence=min(1.0, peak / (self.rate_threshold * 3.0)),
                detail="peak_rate=%.0f deg/s" % peak,
            )
        return None

    def reset_swings(self) -> None:
        self._swings.clear()
        self._last_sign = 0
        self._peak_rate = 0.0

    def reset(self) -> None:
        self.reset_swings()
        self._last_fire = float("-inf")


class HoldDetector(GestureDetector):
    """Fires when an angle stays past a threshold for `hold_s` (look-and-dwell)."""

    def __init__(
        self,
        name: str,
        axis: str = "yaw",
        threshold: float = 25.0,
        hold_s: float = 0.7,
        cooldown_s: float = 1.0,
    ) -> None:
        self.name = name
        self.axis = axis
        self.threshold = threshold
        self.hold_s = hold_s
        self.cooldown_s = cooldown_s
        self._entered_at: Optional[float] = None
        self._entered_sign = 0
        self._last_fire = float("-inf")

    def feed(self, pose: HeadPose) -> Optional[GestureEvent]:
        value = getattr(pose, self.axis)
        sign = 0 if abs(value) < self.threshold else (1 if value > 0 else -1)

        if sign == 0 or sign != self._entered_sign:
            self._entered_at = pose.t if sign != 0 else None
            self._entered_sign = sign
            return None

        if (
            self._entered_at is not None
            and pose.t - self._entered_at >= self.hold_s
            and pose.t - self._last_fire > self.cooldown_s
        ):
            self._last_fire = pose.t
            self._entered_at = None
            return GestureEvent(
                name=self.name,
                t=pose.t,
                confidence=min(1.0, abs(value) / (self.threshold * 2.0)),
                detail="%s=%.0f deg %s" % (self.axis, value, "positive" if sign > 0 else "negative"),
            )
        return None

    def reset(self) -> None:
        self._entered_at = None
        self._entered_sign = 0
        self._last_fire = float("-inf")


def default_detectors() -> List[GestureDetector]:
    """Starter set. Replace/extend once we know what the app needs."""
    return [
        OscillationDetector("nod", axis="pitch", rate_threshold=55.0),
        OscillationDetector("shake", axis="yaw", rate_threshold=70.0),
        HoldDetector("look_left", axis="yaw", threshold=25.0),
        HoldDetector("lean", axis="roll", threshold=20.0),
    ]


class GestureRecognizer:
    """Runs several detectors over one pose stream."""

    def __init__(self, detectors: Optional[List[GestureDetector]] = None) -> None:
        self.detectors = detectors if detectors is not None else default_detectors()

    def feed(self, pose: HeadPose) -> List[GestureEvent]:
        events = []
        for detector in self.detectors:
            event = detector.feed(pose)
            if event is not None:
                events.append(event)
        return events

    def run(self, poses: Iterable[HeadPose]) -> Iterator[GestureEvent]:
        for pose in poses:
            for event in self.feed(pose):
                yield event

    def reset(self) -> None:
        for detector in self.detectors:
            detector.reset()
