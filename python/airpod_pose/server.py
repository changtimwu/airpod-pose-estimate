"""The bridge: pose state out to the browser, commands back in.

Owner: BRIDGE (02).

Server-Sent Events rather than WebSocket, for three reasons that matter at
hackathon scale: it is stdlib-only so nobody runs ``pip install`` on four
laptops, ``EventSource`` reconnects by itself, and the whole transport is about
fifteen lines instead of a hand-rolled frame codec.

Per D5 in ``docs/yoga/01-wire-contract.md`` this process is **authoritative**
for session state. The browser renders whatever the last frame said and owns
nothing.

    GET  /            -> web/index.html
    GET  /<path>      -> web/<path>
    GET  /stream      -> text/event-stream, ~25 Hz
    POST /command     -> {"cmd": "calibrate"|"start"|"skip"|"reset"}

Run it::

    python -m airpod_pose.server                  # self-driving fake arm
    python -m airpod_pose.server --source device  # real AirPods (macOS only)
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import posixpath
import queue
import random
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from .poses import (
    HoldTimer,
    PoseConfig,
    PoseMatcher,
    PoseState,
    confidence_from_error,
)

CONTRACT_VERSION = 1
TICK_HZ = 25.0
TICK_S = 1.0 / TICK_HZ

#: Pitch, in degrees, that the calibration pose is *defined* to be. Calibrating
#: with the arm hanging therefore yields -90 there, 0 with the arm level and
#: +90 overhead -- the convention the wire contract and poses.json are written
#: in. Without this offset every band would sit near 0 and wrap at 180.
MOUNTAIN_PITCH_DEG = -90.0

CALIBRATION_MS = 2000.0
CALIBRATION_MAX_SPREAD_DEG = 5.0
DEVICE_TIMEOUT_MS = 1000.0

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #


class Hub:
    """Fan-out to every connected browser.

    Each subscriber gets a small bounded queue. A browser that cannot keep up
    drops frames rather than growing the server's memory without limit -- every
    frame is a full snapshot, so a dropped one costs nothing.
    """

    QUEUE_DEPTH = 8

    def __init__(self) -> None:
        self._subs: List["queue.Queue[str]"] = []
        self._lock = threading.Lock()

    def subscribe(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue(maxsize=self.QUEUE_DEPTH)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[str]") -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._subs)

    def broadcast(self, payload: Dict) -> None:
        line = json.dumps(payload, separators=(",", ":"))
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(line)
            except queue.Full:
                pass  # slow client; the next snapshot supersedes this one


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #


@dataclass
class RawSample:
    """Uncalibrated forearm angles, exactly as a source produces them."""

    t: float
    pitch: float
    roll: float
    yaw: float


class ScriptedSource:
    """A fake arm that walks itself through the sequence.

    Emits *uncalibrated* angles with an arbitrary frame offset, the same way
    CoreMotion does, so the calibration path is genuinely exercised rather than
    bypassed. Before the flow starts the arm hangs still, which is what the user
    would be doing while calibrating.

    This is what the frontend develops against: a full session cycles on its own
    with nobody wearing anything.
    """

    #: Stands in for CoreMotion's arbitrary, non-repeatable reference frame.
    RAW_OFFSET = (37.5, 12.0, -64.0)

    APPROACH_RATE = 2.6  # degrees per tick toward the target
    NOISE_DEG = 0.55

    def __init__(self, config: PoseConfig, seed: int = 7) -> None:
        self.config = config
        self._rng = random.Random(seed)
        self._pitch = MOUNTAIN_PITCH_DEG
        self._roll = 0.0
        self._t = 0.0

    def sample(self, target_id: Optional[str], active: bool) -> RawSample:
        self._t += TICK_S

        if active and target_id:
            pose = self.config[target_id]
            want_pitch = (pose.pitch[0] + pose.pitch[1]) / 2.0
            want_roll = (
                (pose.roll[0] + pose.roll[1]) / 2.0 if pose.roll_constrained else 0.0
            )
        else:
            want_pitch, want_roll = MOUNTAIN_PITCH_DEG, 0.0

        self._pitch += _step_toward(self._pitch, want_pitch, self.APPROACH_RATE)
        self._roll += _step_toward(self._roll, want_roll, self.APPROACH_RATE)

        n = self.NOISE_DEG
        return RawSample(
            t=self._t,
            pitch=self._pitch + self._rng.uniform(-n, n) + self.RAW_OFFSET[0],
            roll=self._roll + self._rng.uniform(-n, n) + self.RAW_OFFSET[1],
            yaw=self._rng.uniform(-n, n) + self.RAW_OFFSET[2],
        )


def _step_toward(current: float, target: float, rate: float) -> float:
    delta = target - current
    return delta if abs(delta) <= rate else math.copysign(rate, delta)


class DeviceSource:
    """Real AirPods, via the existing pipeline. macOS only.

    Runs the pipeline on its own thread and keeps only the newest ``HeadPose``;
    the tick loop samples it at its own rate. Deliberately lazy-imported so that
    everyone on Windows and Linux can run the bridge without the capture path
    existing at all.
    """

    def __init__(self, source: str = "device", path: Optional[str] = None) -> None:
        self._latest: Optional[RawSample] = None
        self._lock = threading.Lock()
        self._source = source
        self._path = path
        self._error: Optional[str] = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            from .pipeline import PosePipeline  # type: ignore
            from .sources import open_source, samples as iter_samples  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on repo internals
            self._error = (
                f"could not import the capture pipeline ({exc}). "
                "Run with --source scripted, or check python/airpod_pose/."
            )
            return

        try:
            stream = (
                open_source(self._source, path=self._path)
                if self._path
                else open_source(self._source)
            )
            pipeline = PosePipeline()
            # open_source returns a source object, not an iterable of Samples:
            # iter_samples() drives its records() and filters out status lines.
            # And the pipeline's method is feed(), not update() -- both of these
            # raised into the broad except below, so the live path failed silently
            # into an error string while --source scripted kept working.
            for sample in iter_samples(stream):
                pose = pipeline.feed(sample)
                if pose is None:
                    continue
                with self._lock:
                    self._latest = RawSample(
                        t=pose.t, pitch=pose.pitch, roll=pose.roll, yaw=pose.yaw
                    )
        except Exception as exc:  # pragma: no cover
            self._error = str(exc)

    @property
    def error(self) -> Optional[str]:
        return self._error

    def sample(self, target_id: Optional[str], active: bool) -> Optional[RawSample]:
        with self._lock:
            return self._latest


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #


@dataclass
class Calibration:
    pitch_zero: float
    roll_zero: float
    yaw_zero: float

    def apply(self, s: RawSample) -> Tuple[float, float, float]:
        return (
            (s.pitch - self.pitch_zero) + MOUNTAIN_PITCH_DEG,
            _wrap180(s.roll - self.roll_zero),
            _wrap180(s.yaw - self.yaw_zero),
        )


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class Session:
    """The authoritative state machine. Everything the browser shows lives here.

    Thread-safe: the tick loop calls :meth:`step`, HTTP handler threads call
    :meth:`command`, and both take the same lock.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self._config_path = config_path
        self.config = PoseConfig.load(config_path)
        self.lock = threading.RLock()

        self.status = "uncalibrated"
        self.index = 0
        self.calibration: Optional[Calibration] = None

        self.matcher = PoseMatcher(self.config)
        self.hold = HoldTimer()

        self._events: List[Dict] = []
        self._cal_samples: List[Tuple[float, float, float]] = []
        self._cal_started_ms = 0.0
        self._started_ms = 0.0
        self._elapsed_ms = 0.0
        self._scores: List[float] = []
        self._last_sample_ms = 0.0
        self._device_seen = False

        self.arm = (MOUNTAIN_PITCH_DEG, 0.0, 0.0)
        self.pose_state = self._idle_pose_state()

    # -- helpers ----------------------------------------------------------- #

    @property
    def target_id(self) -> str:
        return self.config.sequence[min(self.index, len(self.config.sequence) - 1)]

    def _idle_pose_state(self) -> PoseState:
        target = self.config[self.target_id]
        return PoseState(
            target=target.id,
            detected=None,
            match=False,
            confidence=0.0,
            error_deg=0.0,
            hold_ms=0,
            target_ms=target.hold_ms,
        )

    def _emit(self, event: str, **fields) -> None:
        self._events.append({"event": event, **fields})

    def drain_events(self) -> List[Dict]:
        with self.lock:
            out, self._events = self._events, []
            return out

    def _reload_config(self) -> None:
        """Re-read poses.json so bands can be retuned between runs."""
        try:
            self.config = PoseConfig.load(self._config_path)
            self.matcher = PoseMatcher(self.config)
        except Exception:
            pass  # keep the working config rather than dying mid-demo

    # -- commands ---------------------------------------------------------- #

    def command(self, cmd: str) -> bool:
        with self.lock:
            if cmd == "calibrate":
                self._reload_config()
                self.status = "calibrating"
                self._cal_samples = []
                self._cal_started_ms = _now_ms()
            elif cmd == "start":
                if self.calibration is None:
                    return False
                self._reload_config()
                self.status = "active"
                self.index = 0
                self._scores = []
                self._started_ms = _now_ms()
                self._elapsed_ms = 0.0
                self.matcher.reset()
                self.hold.reset()
            elif cmd == "skip":
                if self.status != "active":
                    return False
                self._advance(steadiness=0.0, completed=False)
            elif cmd == "reset":
                self._reload_config()
                self.status = "ready" if self.calibration else "uncalibrated"
                self.index = 0
                self._scores = []
                self._elapsed_ms = 0.0
                self.matcher.reset()
                self.hold.reset()
                self.pose_state = self._idle_pose_state()
            else:
                return False
            return True

    def _advance(self, steadiness: float, completed: bool) -> None:
        pose = self.config[self.target_id]
        if completed:
            self._scores.append(steadiness)
            self._emit(
                "pose_complete",
                pose=pose.id,
                hold_ms=int(pose.hold_ms),
                steadiness=round(steadiness, 3),
            )
        self.index += 1
        self.matcher.reset()
        self.hold.reset()
        if self.index >= len(self.config.sequence):
            self.index = len(self.config.sequence) - 1
            self.status = "complete"
            self._emit("session_complete", score=round(self.score, 3))
        self.pose_state = self._idle_pose_state()

    @property
    def score(self) -> float:
        return sum(self._scores) / len(self._scores) if self._scores else 0.0

    # -- tick -------------------------------------------------------------- #

    def step(self, sample: Optional[RawSample], dt_ms: float) -> None:
        with self.lock:
            now = _now_ms()

            if sample is None:
                if self._device_seen and now - self._last_sample_ms > DEVICE_TIMEOUT_MS:
                    if self.status != "no_device":
                        self._emit("device_lost")
                        self.status = "no_device"
                return

            if self.status == "no_device":
                self._emit("device_found")
                self.status = "ready" if self.calibration else "uncalibrated"
            self._device_seen = True
            self._last_sample_ms = now

            if self.status == "calibrating":
                self._step_calibrating(sample, now)
                return

            if self.calibration is None:
                self.arm = (sample.pitch, sample.roll, sample.yaw)
                return

            pitch, roll, yaw = self.calibration.apply(sample)
            self.arm = (pitch, roll, yaw)

            if self.status != "active":
                self.pose_state = self._idle_pose_state()
                return

            self._elapsed_ms = now - self._started_ms
            target = self.config[self.target_id]
            was_matched = self.pose_state.match

            matched, detected, error = self.matcher.update(pitch, roll, target.id)
            hold_ms = self.hold.update(dt_ms, matched, error)

            if matched and not was_matched:
                self._emit("pose_entered", pose=target.id)
            elif was_matched and not matched:
                self._emit("pose_lost", pose=target.id)

            self.pose_state = PoseState(
                target=target.id,
                detected=detected,
                match=matched,
                confidence=confidence_from_error(error, matched),
                error_deg=error,
                hold_ms=int(hold_ms),
                target_ms=target.hold_ms,
            )

            if hold_ms >= target.hold_ms:
                self._advance(steadiness=self.hold.steadiness, completed=True)

    def _step_calibrating(self, sample: RawSample, now: float) -> None:
        self._cal_samples.append((sample.pitch, sample.roll, sample.yaw))
        self.arm = (sample.pitch, sample.roll, sample.yaw)
        if now - self._cal_started_ms < CALIBRATION_MS:
            return

        pitches = [s[0] for s in self._cal_samples]
        rolls = [s[1] for s in self._cal_samples]
        if len(pitches) < 2 or max(
            _spread(pitches), _spread(rolls)
        ) > CALIBRATION_MAX_SPREAD_DEG:
            # The user was moving. Better to ask again than to zero on a lie.
            self.status = "uncalibrated"
            self._cal_samples = []
            self._emit("calibration_rejected", reason="moved")
            return

        self.calibration = Calibration(
            pitch_zero=_mean(pitches),
            roll_zero=_mean(rolls),
            yaw_zero=_mean([s[2] for s in self._cal_samples]),
        )
        self._cal_samples = []
        self.status = "ready"
        self.index = 0
        self.pose_state = self._idle_pose_state()
        self._emit("calibrated")

    # -- serialisation ----------------------------------------------------- #

    def frame(self, sample_t: float) -> Dict:
        with self.lock:
            pitch, roll, yaw = self.arm
            stale = self.status == "no_device"
            return {
                "v": CONTRACT_VERSION,
                "type": "frame",
                "t": round(sample_t, 3),
                "wall": round(time.time(), 3),
                "status": self.status,
                "arm": {
                    "pitch": round(pitch, 1),
                    "roll": round(roll, 1),
                    "yaw": round(yaw, 1),
                    "quality": "stale" if stale else "good",
                },
                "pose": self.pose_state.as_dict(),
                "session": {
                    "index": self.index,
                    "total": len(self.config.sequence),
                    "sequence": list(self.config.sequence),
                    "score": round(self.score, 3),
                    "elapsed_ms": int(self._elapsed_ms),
                    "labels": {
                        p.id: {"en": p.label_en, "sa": p.label_sa}
                        for p in self.config.poses.values()
                    },
                },
            }


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs)


def _spread(xs: List[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #


def make_handler(hub: Hub, session: Session, web_root: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "airpod-pose-bridge/1.0"

        def log_message(self, fmt, *args):
            pass  # 25 Hz of access logging helps nobody

        # -- GET ----------------------------------------------------------- #

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/stream":
                return self._stream()
            if path in ("/", "/index.html"):
                return self._static("index.html")
            return self._static(path.lstrip("/"))

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = hub.subscribe()
            try:
                # Retry hint plus an immediate snapshot, so a freshly opened tab
                # paints before the next tick rather than flashing empty.
                self.wfile.write(b"retry: 1000\n\n")
                self._send_event(json.dumps(session.frame(0.0), separators=(",", ":")))
                while True:
                    try:
                        line = q.get(timeout=5.0)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")  # keep idle proxies open
                        self.wfile.flush()
                        continue
                    self._send_event(line)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # browser went away; entirely normal
            finally:
                hub.unsubscribe(q)

        def _send_event(self, line: str) -> None:
            self.wfile.write(b"data: " + line.encode("utf-8") + b"\n\n")
            self.wfile.flush()

        def _static(self, rel: str):
            safe = posixpath.normpath(unquote(rel)).lstrip("/")
            if safe.startswith("..") or Path(safe).is_absolute():
                return self._plain(403, "forbidden")
            target = (web_root / safe).resolve()
            try:
                target.relative_to(web_root.resolve())
            except ValueError:
                return self._plain(403, "forbidden")
            if not target.is_file():
                return self._plain(404, f"not found: /{safe}")

            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # -- POST ---------------------------------------------------------- #

        def do_POST(self):
            if urlparse(self.path).path != "/command":
                return self._plain(404, "not found")
            try:
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                cmd = str(payload.get("cmd", ""))
            except Exception:
                return self._plain(400, "bad json")

            ok = session.command(cmd)
            return self._plain(200 if ok else 409, "ok" if ok else f"rejected: {cmd}")

        def _plain(self, code: int, text: str):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def tick_loop(session: Session, hub: Hub, source) -> None:
    last = time.monotonic()
    while True:
        now = time.monotonic()
        dt_ms = (now - last) * 1000.0
        last = now

        with session.lock:
            active = session.status == "active"
            target_id = session.target_id
        sample = source.sample(target_id, active)

        session.step(sample, dt_ms)
        hub.broadcast(session.frame(sample.t if sample else 0.0))
        for ev in session.drain_events():
            hub.broadcast({"v": CONTRACT_VERSION, "type": "event",
                           "t": round(sample.t, 3) if sample else 0.0, **ev})

        time.sleep(max(0.0, TICK_S - (time.monotonic() - now)))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Yoga coach bridge (SSE).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument(
        "--source",
        default="scripted",
        choices=["scripted", "device", "synthetic", "udp", "file"],
        help="'scripted' is a self-driving fake arm and needs no hardware.",
    )
    ap.add_argument("--file", help="recording to replay, with --source file")
    ap.add_argument("--poses", type=Path, help="path to poses.json")
    ap.add_argument("--web", type=Path, default=WEB_ROOT)
    args = ap.parse_args(argv)

    session = Session(args.poses)
    hub = Hub()

    if args.source == "scripted":
        source = ScriptedSource(session.config)
    else:
        source = DeviceSource(args.source, args.file)

    threading.Thread(target=tick_loop, args=(session, hub, source), daemon=True).start()

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(hub, session, args.web))
    httpd.daemon_threads = True

    print(f"  bridge   http://localhost:{args.port}")
    print(f"  source   {args.source}")
    print(f"  poses    {len(session.config.sequence)} in sequence")
    print(f"  web      {args.web}")
    if args.source != "scripted":
        print("  note     real capture needs `make bundle` first, macOS 14+")
    print("\nCtrl-C to stop.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
