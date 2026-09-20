"""Smoothing primitives.

AirPods motion arrives at 25-50 Hz depending on hardware, already fused by the
OS, so it is not
noisy in the IMU sense -- but it is jittery enough that raw angles look bad on
screen and trip naive thresholds. Everything here is intentionally cheap and
causal (no look-ahead), so the same code can run on a live stream and a replay.
"""

from __future__ import annotations

from typing import Optional

from . import quaternion as quat
from .model import Quat


class ExponentialFilter:
    """Scalar EMA. `alpha` closer to 1 follows the input faster."""

    def __init__(self, alpha: float = 0.35) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self.value: Optional[float] = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value

    def reset(self) -> None:
        self.value = None


class QuaternionFilter:
    """EMA on the rotation manifold: slerp toward each new orientation.

    Filtering the quaternion instead of the Euler angles avoids artifacts at
    the +/-180 deg wrap and near gimbal lock.
    """

    def __init__(self, alpha: float = 0.35) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self.value: Optional[Quat] = None

    def update(self, q: Quat) -> Quat:
        self.value = q if self.value is None else quat.slerp(self.value, q, self.alpha)
        return self.value

    def reset(self) -> None:
        self.value = None


class Derivative:
    """Angle rate in deg/s, wrap-aware so a jump across 180 deg is not a spike."""

    def __init__(self) -> None:
        self.last_value: Optional[float] = None
        self.last_t: Optional[float] = None

    def update(self, value: float, t: float) -> float:
        if self.last_value is None or self.last_t is None or t <= self.last_t:
            self.last_value, self.last_t = value, t
            return 0.0
        rate = quat.wrap_degrees(value - self.last_value) / (t - self.last_t)
        self.last_value, self.last_t = value, t
        return rate

    def reset(self) -> None:
        self.last_value = None
        self.last_t = None
