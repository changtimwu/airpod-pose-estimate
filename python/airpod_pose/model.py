"""Value types for the wire protocol and the derived pose."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # (w, x, y, z)


@dataclass(frozen=True)
class Sample:
    """One motion sample as emitted by `airpod-motion`.

    Units follow CoreMotion: `rot` is rad/s, `acc` and `grav` are in g,
    `t` is a monotonic device clock (seconds) and `wall` is unix time.
    """

    t: float
    wall: float
    seq: int
    q: Quat
    rot: Vec3
    acc: Vec3
    grav: Vec3
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Sample":
        return cls(
            t=float(record["t"]),
            wall=float(record.get("wall", 0.0)),
            seq=int(record.get("seq", 0)),
            q=tuple(float(v) for v in record["q"]),  # type: ignore[arg-type]
            rot=tuple(float(v) for v in record.get("rot", (0, 0, 0))),  # type: ignore[arg-type]
            acc=tuple(float(v) for v in record.get("acc", (0, 0, 0))),  # type: ignore[arg-type]
            grav=tuple(float(v) for v in record.get("grav", (0, 0, 0))),  # type: ignore[arg-type]
            raw=record,
        )


@dataclass(frozen=True)
class HeadPose:
    """Head orientation relative to the calibrated reference frame.

    Angles are degrees, sign conventions chosen to read naturally in a demo:
        yaw   > 0  turning left
        pitch > 0  looking up
        roll  > 0  tilting head to the right
    (Verify these against real hardware before trusting them -- see
    docs/sensor-notes.md, "Axis conventions".)
    """

    t: float
    q: Quat
    yaw: float
    pitch: float
    roll: float
    #: Angular velocity of the smoothed pose, deg/s, same order as the angles.
    yaw_rate: float = 0.0
    pitch_rate: float = 0.0
    roll_rate: float = 0.0
    sample: Optional[Sample] = field(default=None, repr=False, compare=False)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "q": list(self.q),
            "yaw": self.yaw,
            "pitch": self.pitch,
            "roll": self.roll,
            "yaw_rate": self.yaw_rate,
            "pitch_rate": self.pitch_rate,
            "roll_rate": self.roll_rate,
        }
