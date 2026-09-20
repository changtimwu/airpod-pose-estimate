"""Yoga pose matching on top of `HeadPose`.

Owner: SIGNAL (01).

Two halves, and they age differently:

* The **bands** in ``poses.json`` are guesses. Measure them with ``make monitor``
  and replace them. Expect to do this at least twice.
* The **matching logic** here -- hysteresis, hold timing, steadiness -- is what
  stops the UI strobing at a band edge. It should not need changing.

Classification uses ``pitch`` and ``roll`` only. ``yaw`` has no magnetometer
reference and drifts several degrees a minute; see ``docs/sensor-notes.md``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_CONFIG = Path(__file__).with_name("poses.json")

#: A roll band at least this wide is treated as "don't care" and excluded from
#: the error metric, so an unconstrained pose does not report a huge error.
_UNCONSTRAINED_DEG = 180.0


@dataclass(frozen=True)
class PoseDef:
    """One asana, expressed as a band on the calibrated forearm angles."""

    id: str
    label_en: str
    label_sa: str
    hold_ms: int
    pitch: Tuple[float, float]
    roll: Tuple[float, float]
    exit_margin_deg: float = 8.0

    @classmethod
    def from_dict(cls, pose_id: str, d: Dict) -> "PoseDef":
        return cls(
            id=pose_id,
            label_en=d["label_en"],
            label_sa=d.get("label_sa", ""),
            hold_ms=int(d["hold_ms"]),
            pitch=(float(d["pitch"][0]), float(d["pitch"][1])),
            roll=(float(d["roll"][0]), float(d["roll"][1])),
            exit_margin_deg=float(d.get("exit_margin_deg", 8.0)),
        )

    @property
    def roll_constrained(self) -> bool:
        return (self.roll[1] - self.roll[0]) < _UNCONSTRAINED_DEG

    def contains(self, pitch: float, roll: float, margin: float = 0.0) -> bool:
        """Is this pose matched, with the bands widened by ``margin``?"""
        if not (self.pitch[0] - margin <= pitch <= self.pitch[1] + margin):
            return False
        if self.roll_constrained:
            if not (self.roll[0] - margin <= roll <= self.roll[1] + margin):
                return False
        return True

    def error_deg(self, pitch: float, roll: float) -> float:
        """Distance from the band centre, in degrees.

        Smooth and monotonic, so the UI can tighten a target arc as the user
        converges rather than snapping at the boundary. Roll only counts when
        the pose actually constrains it.
        """
        d_pitch = pitch - (self.pitch[0] + self.pitch[1]) / 2.0
        if not self.roll_constrained:
            return abs(d_pitch)
        d_roll = roll - (self.roll[0] + self.roll[1]) / 2.0
        return math.hypot(d_pitch, d_roll)


@dataclass
class PoseConfig:
    """The contents of ``poses.json``."""

    version: int
    sequence: List[str]
    poses: Dict[str, PoseDef]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PoseConfig":
        path = Path(path) if path else DEFAULT_CONFIG
        raw = json.loads(path.read_text(encoding="utf-8"))
        poses = {k: PoseDef.from_dict(k, v) for k, v in raw["poses"].items()}
        sequence = list(raw["sequence"])
        missing = [p for p in sequence if p not in poses]
        if missing:
            raise ValueError(f"sequence references undefined poses: {missing}")
        return cls(version=int(raw.get("version", 1)), sequence=sequence, poses=poses)

    def __getitem__(self, pose_id: str) -> PoseDef:
        return self.poses[pose_id]


class PoseMatcher:
    """Band matching with hysteresis.

    Entry uses the band as written; exit uses the band widened by
    ``exit_margin_deg``. Without this the match flickers at 25 Hz whenever the
    user sits on a boundary, the hold timer resets constantly, and the UI
    strobes. It is the cheapest reliability win in the whole system.
    """

    def __init__(self, config: PoseConfig) -> None:
        self.config = config
        self._inside = False
        self._target: Optional[str] = None

    def reset(self) -> None:
        self._inside = False
        self._target = None

    def update(
        self, pitch: float, roll: float, target_id: str
    ) -> Tuple[bool, Optional[str], float]:
        """Returns ``(match, detected_pose_id, error_deg)`` for this sample."""
        if target_id != self._target:
            self._target = target_id
            self._inside = False

        target = self.config[target_id]
        margin = target.exit_margin_deg if self._inside else 0.0
        self._inside = target.contains(pitch, roll, margin=margin)

        return self._inside, self._detect(pitch, roll), target.error_deg(pitch, roll)

    def _detect(self, pitch: float, roll: float) -> Optional[str]:
        """Whichever pose the arm is actually in, for display and debugging.

        Never drives the flow -- the flow only cares whether the *target*
        matched. Nearest centre wins when bands overlap.
        """
        hits = [p for p in self.config.poses.values() if p.contains(pitch, roll)]
        if not hits:
            return None
        return min(hits, key=lambda p: p.error_deg(pitch, roll)).id


class HoldTimer:
    """Accumulates matched time and scores how still the user was.

    Steadiness is ``1 - normalised angular spread`` over the hold, clamped to
    0..1. It is what separates "held it" from "held it well", and it is the
    number worth putting on the completion screen.
    """

    #: Spread, in degrees, at which steadiness reaches zero.
    SPREAD_FLOOR_DEG = 18.0

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.hold_ms = 0.0
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def update(self, dt_ms: float, matched: bool, error_deg: float) -> float:
        if not matched:
            self.reset()
            return 0.0
        self.hold_ms += dt_ms
        # Welford, so a long hold does not accumulate float error.
        self._n += 1
        delta = error_deg - self._mean
        self._mean += delta / self._n
        self._m2 += delta * (error_deg - self._mean)
        return self.hold_ms

    @property
    def steadiness(self) -> float:
        if self._n < 2:
            return 1.0
        spread = math.sqrt(self._m2 / (self._n - 1))
        return max(0.0, min(1.0, 1.0 - spread / self.SPREAD_FLOOR_DEG))


@dataclass
class PoseState:
    """Everything the wire contract's ``pose`` and ``session`` blocks need."""

    target: str
    detected: Optional[str]
    match: bool
    confidence: float
    error_deg: float
    hold_ms: int
    target_ms: int

    def as_dict(self) -> Dict:
        return {
            "target": self.target,
            "detected": self.detected,
            "match": self.match,
            "confidence": round(self.confidence, 3),
            "error_deg": round(self.error_deg, 1),
            "hold_ms": int(self.hold_ms),
            "target_ms": int(self.target_ms),
        }


def confidence_from_error(error_deg: float, matched: bool) -> float:
    """Map angular error onto 0..1 for the UI.

    Deliberately crude: it drives a progress ring, not a decision. The decision
    is the band, and the band is binary.
    """
    if not matched:
        return 0.0
    return max(0.0, min(1.0, 1.0 - error_deg / 45.0))
