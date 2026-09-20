"""Held-pose recognition: reference orientations, hold timing, steadiness.

Design notes, because the obvious approach is the wrong one here:

**Reference orientations, not angle bands.** A pose could be described as
per-axis Euler ranges, but Euler angles degenerate as an axis approaches
vertical -- with 0.5 deg of real noise, reported roll wobbles +/-14 deg at 88 deg
of pitch (docs/sensor-notes.md). Yoga puts limbs and heads near vertical
constantly, so bands there threshold noise. Instead a pose is one captured
quaternion plus a tolerance, and matching is `angle_between`: a single number,
continuous everywhere, with no parameterisation to go singular.

**Captured, not hand-written.** You hold the pose, we record it. Nobody has to
guess that Triangle is "pitch 58-88".

**Placement-agnostic.** Nothing here assumes the device is on a head. An AirPod
in an ear, banded to a forearm, or taped to a broom handle all work the same
way: calibrate a neutral, capture references, match against them.

**Hysteresis on entry/exit.** Without it a pose sitting near its tolerance
flickers in and out at the sample rate and the hold timer never accumulates.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Iterable, Iterator, List, Optional

from . import quaternion as quat
from .model import HeadPose, Quat

DEFAULT_LIBRARY = Path(__file__).resolve().parents[2] / "data" / "asanas.json"


@dataclass
class PoseTarget:
    """One held pose: where to be, how close counts, and for how long."""

    name: str
    reference: Quat
    label: str = ""
    #: Enter the pose when within this many degrees of the reference.
    tolerance_deg: float = 20.0
    #: Leave only after exceeding tolerance + this, so the edge does not chatter.
    exit_margin_deg: float = 8.0
    #: Seconds inside tolerance before the hold counts as complete.
    hold_s: float = 5.0
    #: Optional note shown in the UI ("gaze down at the front foot").
    cue: str = ""

    def distance(self, q: Quat) -> float:
        return quat.angle_between(self.reference, q)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "label": self.label,
            "reference": list(self.reference),
            "tolerance_deg": self.tolerance_deg,
            "exit_margin_deg": self.exit_margin_deg,
            "hold_s": self.hold_s,
            "cue": self.cue,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PoseTarget":
        return cls(
            name=d["name"],
            reference=tuple(float(v) for v in d["reference"]),  # type: ignore[arg-type]
            label=d.get("label", ""),
            tolerance_deg=float(d.get("tolerance_deg", 20.0)),
            exit_margin_deg=float(d.get("exit_margin_deg", 8.0)),
            hold_s=float(d.get("hold_s", 5.0)),
            cue=d.get("cue", ""),
        )


@dataclass
class AsanaLibrary:
    """A named set of pose targets, persisted as JSON."""

    targets: List[PoseTarget] = field(default_factory=list)
    path: Optional[Path] = None

    def __len__(self) -> int:
        return len(self.targets)

    def __iter__(self) -> Iterator[PoseTarget]:
        return iter(self.targets)

    def get(self, name: str) -> Optional[PoseTarget]:
        return next((t for t in self.targets if t.name == name), None)

    def add(self, target: PoseTarget) -> None:
        """Add, replacing any existing target of the same name."""
        self.targets = [t for t in self.targets if t.name != target.name] + [target]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AsanaLibrary":
        path = Path(path) if path else DEFAULT_LIBRARY
        if not path.is_file():
            return cls(targets=[], path=path)
        data = json.loads(path.read_text())
        return cls(targets=[PoseTarget.from_dict(d) for d in data.get("poses", [])], path=path)

    def save(self, path: Optional[Path] = None) -> Path:
        path = Path(path) if path else (self.path or DEFAULT_LIBRARY)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "poses": [t.to_dict() for t in self.targets]}
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path


class Steadiness:
    """Rolling RMS of angular speed, in deg/s.

    The single most demo-proof signal we have: it needs no reference, no bands
    and no calibration, it does not care where the sensor is mounted, and it
    cannot drift. Low = holding still. It is also the honest thing to report --
    "steadier on the left side" observes, where "go 10 degrees deeper" prescribes.
    """

    def __init__(self, window_s: float = 1.0) -> None:
        self.window_s = window_s
        self._samples: Deque[tuple] = deque()

    def update(self, pose: HeadPose) -> float:
        speed = math.sqrt(pose.yaw_rate ** 2 + pose.pitch_rate ** 2 + pose.roll_rate ** 2)
        self._samples.append((pose.t, speed))
        while self._samples and pose.t - self._samples[0][0] > self.window_s:
            self._samples.popleft()
        return self.value

    @property
    def value(self) -> float:
        if not self._samples:
            return 0.0
        return math.sqrt(sum(s * s for _, s in self._samples) / len(self._samples))

    def reset(self) -> None:
        self._samples.clear()


@dataclass
class AsanaEvent:
    """Something worth announcing: entered, held, or exited a pose."""

    kind: str  # "enter" | "hold" | "exit"
    name: str
    t: float
    duration: float = 0.0
    steadiness: float = 0.0
    distance: float = 0.0


@dataclass
class AsanaState:
    """Everything the UI needs for one frame."""

    t: float
    distances: Dict[str, float]
    steadiness: float
    current: Optional[str] = None
    elapsed: float = 0.0
    hold_s: float = 0.0
    completed: bool = False

    @property
    def progress(self) -> float:
        if self.current is None or self.hold_s <= 0:
            return 0.0
        return min(1.0, self.elapsed / self.hold_s)

    def nearest(self) -> Optional[str]:
        if not self.distances:
            return None
        return min(self.distances, key=lambda k: self.distances[k])


class AsanaMatcher:
    """Match a pose stream against a library, with hold timing and hysteresis."""

    def __init__(self, library: AsanaLibrary, steadiness_window_s: float = 1.0) -> None:
        self.library = library
        self.steadiness = Steadiness(steadiness_window_s)
        self.current: Optional[PoseTarget] = None
        self._entered_at: Optional[float] = None
        self._completed = False
        #: name -> best (longest) hold recorded this session, for the summary.
        self.best_holds: Dict[str, float] = {}
        #: name -> mean steadiness during that best hold, deg/s. This is the
        #: left-vs-right comparison the demo actually reports.
        self.hold_steadiness: Dict[str, float] = {}
        self.events: List[AsanaEvent] = []
        self._during_hold: List[float] = []

    def feed(self, pose: HeadPose) -> tuple:
        """Push one pose. Returns (state, events-produced-this-sample)."""
        steady = self.steadiness.update(pose)
        distances = {t.name: t.distance(pose.q) for t in self.library}
        produced: List[AsanaEvent] = []

        if self.current is not None:
            target = self.current
            # Exit is deliberately harder than entry: without the margin, a pose
            # resting at the tolerance edge toggles every few samples.
            # `is None`, not `or`: an entry time of exactly 0.0 is falsy, and every
            # synthetic and file-replay stream starts at t=0.0 -- which silently
            # pinned `held` to zero so no hold ever completed off hardware.
            entered_at = pose.t if self._entered_at is None else self._entered_at
            if distances[target.name] > target.tolerance_deg + target.exit_margin_deg:
                held = pose.t - entered_at
                self._record_hold(target.name, held)
                produced.append(AsanaEvent("exit", target.name, pose.t, held,
                                           self.hold_steadiness.get(target.name, steady),
                                           distances[target.name]))
                self.current = None
                self._entered_at = None
                self._completed = False
                self._during_hold = []
            else:
                held = pose.t - entered_at
                self._during_hold.append(steady)
                if not self._completed and held >= target.hold_s:
                    self._completed = True
                    self._record_hold(target.name, held)
                    produced.append(AsanaEvent("hold", target.name, pose.t, held,
                                               self.hold_steadiness[target.name],
                                               distances[target.name]))
        else:
            candidates = [t for t in self.library if distances[t.name] <= t.tolerance_deg]
            if candidates:
                target = min(candidates, key=lambda t: distances[t.name])
                self.current = target
                self._entered_at = pose.t
                self._completed = False
                self._during_hold = []
                produced.append(AsanaEvent("enter", target.name, pose.t, 0.0, steady,
                                           distances[target.name]))

        self.events.extend(produced)
        state = AsanaState(
            t=pose.t,
            distances=distances,
            steadiness=steady,
            current=self.current.name if self.current else None,
            elapsed=(pose.t - self._entered_at) if self._entered_at is not None else 0.0,
            hold_s=self.current.hold_s if self.current else 0.0,
            completed=self._completed,
        )
        return state, produced

    def _record_hold(self, name: str, held: float) -> None:
        """Keep the longest hold per pose, and the steadiness measured during it."""
        if held < self.best_holds.get(name, 0.0):
            return
        self.best_holds[name] = held
        if self._during_hold:
            self.hold_steadiness[name] = sum(self._during_hold) / len(self._during_hold)

    def run(self, poses: Iterable[HeadPose]) -> Iterator[tuple]:
        for pose in poses:
            yield self.feed(pose)

    def summary(self) -> List[str]:
        """End-of-session report. Observations, never prescriptions."""
        if not self.best_holds:
            return ["No pose was held long enough to report."]
        lines = []
        for name, held in sorted(self.best_holds.items(), key=lambda kv: -kv[1]):
            target = self.library.get(name)
            label = (target.label or name) if target else name
            wobble = self.hold_steadiness.get(name)
            if wobble is None:
                lines.append("%-22s held %5.1fs" % (label, held))
            else:
                lines.append("%-22s held %5.1fs   wobble %4.1f deg/s" % (label, held, wobble))

        # The comparison Trikonasana actually wants: same pose, two sides.
        pairs = [(n, self.hold_steadiness[n]) for n in self.best_holds
                 if n in self.hold_steadiness]
        if len(pairs) >= 2:
            calmest = min(pairs, key=lambda kv: kv[1])
            target = self.library.get(calmest[0])
            lines.append("")
            lines.append("steadiest hold: %s (%.1f deg/s)" % (
                (target.label or calmest[0]) if target else calmest[0], calmest[1]))
        return lines


def capture_reference(
    poses: Iterable[HeadPose],
    samples: int = 25,
    max_spread_deg: float = 10.0,
) -> tuple:
    """Average a short window of poses into a reference orientation.

    Returns (reference_quaternion, spread_deg). Spread is how much the body moved
    during capture -- report it, because a reference captured while wobbling
    produces a target nobody can hit twice.
    """
    collected: List[Quat] = []
    for pose in poses:
        collected.append(quat.normalize(pose.q))
        if len(collected) >= samples:
            break
    if not collected:
        raise ValueError("no poses to capture from")

    pivot = collected[0]
    acc = [0.0, 0.0, 0.0, 0.0]
    for q in collected:
        sign = -1.0 if sum(a * b for a, b in zip(pivot, q)) < 0.0 else 1.0
        for i in range(4):
            acc[i] += sign * q[i]
    reference = quat.normalize((acc[0], acc[1], acc[2], acc[3]))
    spread = max(quat.angle_between(reference, q) for q in collected)
    return reference, spread
