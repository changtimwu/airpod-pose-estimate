"""Where samples come from.

Four interchangeable sources, all yielding the same newline-JSON records:

    DeviceSource     live AirPods, via the Swift `airpod-motion` subprocess
    UDPSource        the same records arriving over UDP (capture on another Mac)
    FileSource       replay of a recorded .jsonl, optionally at real speed
    SyntheticSource  scripted fake motion -- lets the whole Python side be
                     developed and tested with no hardware and no AirPods
"""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from . import quaternion as quat
from .model import Sample

Record = Dict[str, Any]

REPO_ROOT = Path(__file__).resolve().parents[2]
#: Bundled binary first: on macOS the unbundled one never gets motion permission.
BINARY_CANDIDATES: Sequence[Path] = (
    REPO_ROOT / "build" / "AirPodMotion.app" / "Contents" / "MacOS" / "airpod-motion",
    REPO_ROOT / "swift-capture" / ".build" / "release" / "airpod-motion",
    REPO_ROOT / "swift-capture" / ".build" / "debug" / "airpod-motion",
)


class SourceError(RuntimeError):
    pass


def find_binary() -> Path:
    for candidate in BINARY_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("airpod-motion")
    if found:
        return Path(found)
    raise SourceError(
        "airpod-motion binary not found. Run `make build bundle` at the repo root, "
        "or pass --source synthetic to work without hardware."
    )


class DeviceSource:
    """Runs the Swift capture tool and parses its stdout."""

    def __init__(self, binary: Optional[Path] = None, extra_args: Iterable[str] = ()) -> None:
        self.binary = Path(binary) if binary else find_binary()
        self.extra_args = list(extra_args)
        self.process: Optional[subprocess.Popen] = None

    def records(self) -> Iterator[Record]:
        cmd = [str(self.binary)] + self.extra_args
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                record = _parse(line)
                if record is not None:
                    yield record
        finally:
            self.close()

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.process.stderr is not None:
            stderr = self.process.stderr.read()
            if stderr.strip():
                print("[airpod-motion] " + stderr.strip(), file=sys.stderr)
        self.process = None


class UDPSource:
    def __init__(self, host: str = "0.0.0.0", port: int = 9870) -> None:
        self.host = host
        self.port = port

    def records(self) -> Iterator[Record]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        try:
            while True:
                payload, _ = sock.recvfrom(65535)
                for line in payload.decode("utf-8", "replace").splitlines():
                    record = _parse(line)
                    if record is not None:
                        yield record
        finally:
            sock.close()


class FileSource:
    """Replay a recorded session.

    `realtime=True` paces playback by the recorded timestamps, which matters
    when testing anything time-based (gesture windows, cooldowns, the viewer).
    """

    def __init__(self, path: os.PathLike, realtime: bool = False, loop: bool = False) -> None:
        self.path = Path(path)
        self.realtime = realtime
        self.loop = loop

    def records(self) -> Iterator[Record]:
        while True:
            started = time.monotonic()
            first_t: Optional[float] = None
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record = _parse(line)
                    if record is None:
                        continue
                    if self.realtime and record.get("type") == "sample":
                        t = float(record["t"])
                        first_t = t if first_t is None else first_t
                        target = t - first_t - (time.monotonic() - started)
                        if target > 0:
                            time.sleep(target)
                    yield record
            if not self.loop:
                return


class SyntheticSource:
    """Scripted fake head motion: idle drift plus a loop of gestures.

    Useful for two things: developing the Python side with no AirPods, and
    giving the gesture tests a signal with known ground truth.
    """

    #: (start_time, kind) -- kind is one of nod, shake, look_left, lean
    DEFAULT_SCRIPT: Sequence[tuple] = (
        (2.0, "nod"),
        (4.0, "shake"),
        (6.0, "look_left"),
        (9.0, "lean"),
    )

    def __init__(
        self,
        duration: float = 12.0,
        rate: float = 25.0,
        realtime: bool = False,
        script: Optional[Sequence[tuple]] = None,
        noise: float = 0.3,
    ) -> None:
        self.duration = duration
        self.rate = rate
        self.realtime = realtime
        self.script = list(self.DEFAULT_SCRIPT if script is None else script)
        self.noise = noise

    def records(self) -> Iterator[Record]:
        dt = 1.0 / self.rate
        n = int(self.duration * self.rate)
        yield {"type": "status", "wall": time.time(), "event": "connected", "detail": "synthetic"}
        prev = (0.0, 0.0, 0.0)
        for i in range(n):
            t = i * dt
            yaw, pitch, roll = self._angles(t)
            q = quat.from_euler(yaw, pitch, roll)
            rot = tuple(math.radians(a - b) / dt for a, b in zip((roll, pitch, yaw), prev[::-1]))
            prev = (yaw, pitch, roll)
            yield {
                "type": "sample",
                "t": t,
                "wall": time.time(),
                "seq": i + 1,
                "q": list(q),
                "euler": {"roll": roll, "pitch": pitch, "yaw": yaw},
                "rot": list(rot),
                "acc": [0.0, 0.0, 0.0],
                "grav": [0.0, -1.0, 0.0],
            }
            if self.realtime:
                time.sleep(dt)

    def _angles(self, t: float) -> tuple:
        # Slow wander so nothing is ever perfectly still, like a real head.
        yaw = 3.0 * math.sin(t * 0.3) + self.noise * math.sin(t * 7.3)
        pitch = 2.0 * math.sin(t * 0.21 + 1.0) + self.noise * math.sin(t * 6.1)
        roll = 1.5 * math.sin(t * 0.17 + 2.0) + self.noise * math.sin(t * 5.7)

        for start, kind in self.script:
            local = t - start
            if kind == "nod" and 0 <= local < 1.0:
                pitch += 22.0 * math.sin(local * 2 * math.pi * 1.5)
            elif kind == "shake" and 0 <= local < 1.2:
                yaw += 28.0 * math.sin(local * 2 * math.pi * 1.6)
            elif kind == "look_left" and 0 <= local < 2.0:
                yaw += 40.0 * _ramp(local, 2.0)
            elif kind == "lean" and 0 <= local < 2.0:
                roll += 30.0 * _ramp(local, 2.0)
        return (yaw, pitch, roll)


def open_source(
    kind: str = "device",
    path: Optional[os.PathLike] = None,
    host: str = "0.0.0.0",
    port: int = 9870,
    realtime: bool = True,
    loop: bool = False,
    duration: float = 12.0,
):
    """Factory used by the CLI so every command accepts the same --source flags."""
    if kind == "device":
        return DeviceSource()
    if kind == "udp":
        return UDPSource(host=host, port=port)
    if kind == "file":
        if path is None:
            raise SourceError("--source file requires --path")
        return FileSource(path, realtime=realtime, loop=loop)
    if kind == "synthetic":
        return SyntheticSource(duration=duration, realtime=realtime)
    raise SourceError("unknown source: %s" % kind)


def samples(source, on_status=None) -> Iterator[Sample]:
    """Filter a record stream down to parsed samples."""
    for record in source.records():
        if record.get("type") == "status":
            if on_status is not None:
                on_status(record)
            continue
        if "q" not in record:
            continue
        yield Sample.from_record(record)


def read_jsonl(path: os.PathLike) -> List[Record]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return [r for r in (_parse(line) for line in handle) if r is not None]


def _parse(line: str) -> Optional[Record]:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        print("[warn] dropped malformed line: %s" % line[:120], file=sys.stderr)
        return None
    return record if isinstance(record, dict) else None


def _ramp(local: float, total: float) -> float:
    """0 -> 1 -> 0 raised-cosine, for hold-style gestures."""
    return 0.5 * (1.0 - math.cos(2 * math.pi * min(local / total, 1.0)))
