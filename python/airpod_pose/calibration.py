"""Defining "straight ahead".

CoreMotion gives orientation in its own arbitrary reference frame, fixed when
the AirPods start reporting. Any application-level pose has to be expressed
relative to a pose we chose deliberately, which means a calibration step:
hold still, look forward, capture, and treat that as identity.
"""

from __future__ import annotations

from typing import List, Optional

from . import quaternion as quat
from .model import Quat, Sample


class Calibrator:
    """Averages a short window of samples into a reference orientation.

    The average is a normalized component-wise mean, which is only valid for
    closely-spaced orientations -- fine for "hold still for half a second",
    wrong for anything else. Hence `max_spread_deg`: if the head moved during
    capture we reject the window instead of producing a bogus reference.
    """

    def __init__(self, window: int = 12, max_spread_deg: float = 8.0) -> None:
        self.window = window
        self.max_spread_deg = max_spread_deg
        self._collected: List[Quat] = []
        self.reference: Optional[Quat] = None

    @property
    def is_calibrated(self) -> bool:
        return self.reference is not None

    @property
    def progress(self) -> float:
        if self.reference is not None:
            return 1.0
        return min(1.0, len(self._collected) / float(self.window))

    def begin(self) -> None:
        """Start (or restart) a capture; clears any existing reference."""
        self._collected.clear()
        self.reference = None

    def feed(self, sample: Sample) -> bool:
        """Add a sample to an in-progress capture. True once a reference exists."""
        if self.reference is not None:
            return True
        self._collected.append(quat.normalize(sample.q))
        if len(self._collected) < self.window:
            return False

        candidate = _mean_quaternion(self._collected)
        spread = max(quat.angle_between(candidate, q) for q in self._collected)
        if spread > self.max_spread_deg:
            # Too much movement: slide the window instead of locking in garbage.
            self._collected = self._collected[len(self._collected) // 2 :]
            return False

        self.reference = candidate
        self._collected.clear()
        return True

    def set_reference(self, q: Quat) -> None:
        self.reference = quat.normalize(q)
        self._collected.clear()

    def apply(self, q: Quat) -> Quat:
        """Express `q` in the calibrated frame (identity if not calibrated yet)."""
        if self.reference is None:
            return quat.normalize(q)
        return quat.relative(self.reference, q)


def _mean_quaternion(quats: List[Quat]) -> Quat:
    pivot = quats[0]
    acc = [0.0, 0.0, 0.0, 0.0]
    for q in quats:
        # Hemisphere-align against the pivot, otherwise q and -q cancel out.
        sign = -1.0 if sum(a * b for a, b in zip(pivot, q)) < 0.0 else 1.0
        for i in range(4):
            acc[i] += sign * q[i]
    return quat.normalize((acc[0], acc[1], acc[2], acc[3]))
