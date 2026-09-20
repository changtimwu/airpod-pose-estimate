"""Sample stream -> HeadPose stream.

This is the seam the application sits on. Whatever demo we settle on should
consume `HeadPose` objects and never touch CoreMotion field names.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Optional

from . import quaternion as quat
from .calibration import Calibrator
from .filters import Derivative, QuaternionFilter
from .model import HeadPose, Quat, Sample


class PosePipeline:
    """Calibrate, smooth, and differentiate a stream of samples.

    Parameters
    ----------
    smoothing:
        Slerp coefficient, 0..1. Lower = smoother but laggier. 0.35 at 25 Hz is
        roughly a 60 ms time constant, which felt like a sane starting point;
        tune it once we know whether the demo cares more about latency or calm.
    auto_calibrate:
        Use the first `calibration_window` samples as the reference frame. Handy
        for headless runs; a real app should calibrate on an explicit cue.
    """

    def __init__(
        self,
        smoothing: float = 0.35,
        auto_calibrate: bool = True,
        calibration_window: int = 12,
    ) -> None:
        self.calibrator = Calibrator(window=calibration_window)
        self.filter = QuaternionFilter(alpha=smoothing)
        self._auto_calibrate = auto_calibrate
        self._yaw_rate = Derivative()
        self._pitch_rate = Derivative()
        self._roll_rate = Derivative()
        self.last_pose: Optional[HeadPose] = None

    # -- calibration ----------------------------------------------------

    def recalibrate(self) -> None:
        """Drop the reference frame and re-capture from the next samples."""
        self.calibrator.begin()
        self.filter.reset()
        self._yaw_rate.reset()
        self._pitch_rate.reset()
        self._roll_rate.reset()
        self.last_pose = None

    def set_reference(self, q: Quat) -> None:
        self.calibrator.set_reference(q)

    @property
    def is_calibrated(self) -> bool:
        return self.calibrator.is_calibrated

    # -- main entry point -----------------------------------------------

    def feed(self, sample: Sample) -> Optional[HeadPose]:
        """Push one sample. Returns None while calibration is still filling."""
        if not self.calibrator.is_calibrated:
            if not self._auto_calibrate:
                return None
            if not self.calibrator.feed(sample):
                return None

        q = self.filter.update(self.calibrator.apply(sample.q))
        yaw, pitch, roll = quat.to_euler(q)
        pose = HeadPose(
            t=sample.t,
            q=q,
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            yaw_rate=self._yaw_rate.update(yaw, sample.t),
            pitch_rate=self._pitch_rate.update(pitch, sample.t),
            roll_rate=self._roll_rate.update(roll, sample.t),
            sample=sample,
        )
        self.last_pose = pose
        return pose

    def run(self, samples: Iterable[Sample]) -> Iterator[HeadPose]:
        """Convenience wrapper: map a sample iterable to a pose iterable."""
        for sample in samples:
            pose = self.feed(sample)
            if pose is not None:
                yield pose
