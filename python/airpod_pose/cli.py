"""Command line entry point: `airpod-pose <command>`.

Commands are thin wrappers over the library so that a broken demo is always
debuggable one layer down.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Iterator, Optional

from . import sources
from .gestures import GestureRecognizer
from .model import HeadPose
from .pipeline import PosePipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airpod-pose",
        description="AirPods head-pose prototyping toolkit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_source_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--source",
            choices=["device", "udp", "file", "synthetic"],
            default="device",
            help="where samples come from (default: device)",
        )
        p.add_argument("--path", type=Path, help="recording to replay with --source file")
        p.add_argument("--host", default="0.0.0.0", help="bind host for --source udp")
        p.add_argument("--port", type=int, default=9870, help="bind port for --source udp")
        p.add_argument("--loop", action="store_true", help="loop a file replay")
        p.add_argument(
            "--fast",
            action="store_true",
            help="replay/synthesize as fast as possible instead of real time",
        )
        p.add_argument("--duration", type=float, default=12.0, help="synthetic stream length (s)")

    def add_pose_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--smoothing", type=float, default=0.35, help="slerp alpha, 0..1")
        p.add_argument(
            "--calibration-window",
            type=int,
            default=12,
            help="samples averaged into the reference frame",
        )

    doctor = sub.add_parser("doctor", help="check the capture path end to end")
    doctor.add_argument("--seconds", type=float, default=5.0, help="how long to listen")

    record = sub.add_parser("record", help="write raw records to a .jsonl file")
    add_source_args(record)
    record.add_argument("--out", type=Path, required=True, help="output .jsonl")
    record.add_argument("--seconds", type=float, help="stop after N seconds")
    record.add_argument("--label", help="free-text note stored in a header record")

    monitor = sub.add_parser("monitor", help="live pose readout in the terminal")
    add_source_args(monitor)
    add_pose_args(monitor)
    monitor.add_argument("--no-gestures", action="store_true", help="skip gesture detection")

    gestures = sub.add_parser("gestures", help="print gesture events only")
    add_source_args(gestures)
    add_pose_args(gestures)

    dump = sub.add_parser("dump", help="print poses as JSON lines (pipe into anything)")
    add_source_args(dump)
    add_pose_args(dump)

    viz = sub.add_parser("viz", help="live 3D head-axes plot (needs matplotlib)")
    add_source_args(viz)
    add_pose_args(viz)
    viz.add_argument("--trail", type=int, default=120, help="history length for the angle plot")

    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "record": cmd_record,
        "monitor": cmd_monitor,
        "gestures": cmd_gestures,
        "dump": cmd_dump,
        "viz": cmd_viz,
    }
    try:
        return handlers[args.command](args)
    except sources.SourceError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


# --------------------------------------------------------------------------
# commands


def cmd_doctor(args) -> int:
    print("1. locating the capture tool ...", end=" ")
    try:
        source = sources.DeviceSource()
    except sources.SourceError as exc:
        print("FAIL\n   %s" % exc)
        return 1
    if source.strategy == "app":
        print("ok\n   %s (launched via LaunchServices, mirrored over UDP)" % sources.APP_PATH)
    else:
        print("ok\n   %s" % sources.find_binary())
        print(
            "   warning: no app bundle, so the binary runs straight from this terminal.\n"
            "   macOS will not prompt for motion permission that way and you will get\n"
            "   zero samples. Run `make bundle`."
        )

    print("2. listening for %.0fs ..." % args.seconds)
    count = 0
    try:
        for record in _with_deadline(source, args.seconds):
            if record.get("type") == "status":
                print("   status: %s %s" % (record.get("event"), record.get("detail") or ""))
            else:
                count += 1
    finally:
        source.close()

    print("3. result: %d samples in %.0fs (~%.1f Hz)" % (count, args.seconds, count / args.seconds))
    if count == 0:
        print(
            "   No samples. Checklist, in the order these actually go wrong:\n"
            "     - AirPods are the SELECTED audio output, not merely connected\n"
            "       (they auto-switch to your iPhone; play a sound to force the route back)\n"
            "     - wearing them: some models stop reporting when idle or in the case\n"
            "     - motion permission: System Settings > Privacy & Security > Motion & Fitness\n"
            "     - AirPods Pro / AirPods 3+ / AirPods Max / Beats Fit Pro (older models have no IMU)\n"
            "     - `make bundle` after any Swift change: the .app holds a COPY of the binary\n"
            "   Meanwhile: `airpod-pose monitor --source synthetic` exercises everything above the driver."
        )
        return 1
    print("   Now check the signs: `airpod-pose monitor`, turn your head left and")
    print("   confirm yaw goes positive. See docs/sensor-notes.md.")
    return 0


def cmd_record(args) -> int:
    source = _open(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    deadline = None if args.seconds is None else time.monotonic() + args.seconds
    written = 0
    with args.out.open("w", encoding="utf-8") as handle:
        header = {
            "type": "header",
            "wall": time.time(),
            "label": args.label or "",
            "source": args.source,
        }
        handle.write(json.dumps(header) + "\n")
        try:
            for record in source.records():
                handle.write(json.dumps(record) + "\n")
                if record.get("type") != "status":
                    written += 1
                    if written % 25 == 0:
                        print("\r  %d samples" % written, end="", flush=True)
                if deadline is not None and time.monotonic() > deadline:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            _close(source)
    print("\nwrote %d samples to %s" % (written, args.out))
    return 0 if written else 1


def cmd_monitor(args) -> int:
    pipeline = _pipeline(args)
    recognizer = None if args.no_gestures else GestureRecognizer()
    source = _open(args)
    last_draw = 0.0
    try:
        for sample in sources.samples(source, on_status=_print_status):
            pose = pipeline.feed(sample)
            if pose is None:
                continue
            if recognizer is not None:
                for event in recognizer.feed(pose):
                    print("\r%s  %-10s conf=%.2f  %s" % (
                        _clock(event.t), event.name, event.confidence, event.detail))
            now = time.monotonic()
            if now - last_draw > 0.05:  # ~20 fps redraw; the stream is faster
                print("\r" + _bars(pose), end="", flush=True)
                last_draw = now
    finally:
        _close(source)
        print()
    return 0


def cmd_gestures(args) -> int:
    pipeline = _pipeline(args)
    recognizer = GestureRecognizer()
    source = _open(args)
    count = 0
    try:
        for pose in pipeline.run(sources.samples(source, on_status=_print_status)):
            for event in recognizer.feed(pose):
                count += 1
                print("%s  %-10s conf=%.2f  %s" % (
                    _clock(event.t), event.name, event.confidence, event.detail))
    finally:
        _close(source)
    print("%d events" % count, file=sys.stderr)
    return 0


def cmd_dump(args) -> int:
    pipeline = _pipeline(args)
    source = _open(args)
    try:
        for pose in pipeline.run(sources.samples(source)):
            print(json.dumps(pose.as_dict()), flush=True)
    finally:
        _close(source)
    return 0


def cmd_viz(args) -> int:
    from .viz import run_viz  # imported lazily: matplotlib is an optional extra

    source = _open(args)
    try:
        return run_viz(source, _pipeline(args), trail=args.trail)
    finally:
        _close(source)


# --------------------------------------------------------------------------
# helpers


def _open(args):
    return sources.open_source(
        kind=args.source,
        path=args.path,
        host=args.host,
        port=args.port,
        realtime=not args.fast,
        loop=args.loop,
        duration=args.duration,
    )


def _close(source) -> None:
    close = getattr(source, "close", None)
    if callable(close):
        close()


def _pipeline(args) -> PosePipeline:
    return PosePipeline(
        smoothing=args.smoothing,
        calibration_window=args.calibration_window,
    )


def _with_deadline(source, seconds: float) -> Iterator[dict]:
    """Yield records for `seconds`, then stop -- even if nothing ever arrives.

    A silent stream is the normal failure here (AirPods connected but not the
    selected output), and the naive `for record in source.records()` loop simply
    blocks forever on the socket. Reading in a daemon thread bounds the wait for
    every source type rather than just the one we happened to test.
    """
    inbox: "queue.Queue" = queue.Queue()

    def reader() -> None:
        try:
            for record in source.records():
                inbox.put(record)
        except Exception as exc:  # surfaced below; the thread must not die silently
            inbox.put({"type": "status", "event": "error", "detail": str(exc)})

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            yield inbox.get(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue


def _print_status(record) -> None:
    print("[status] %s %s" % (record.get("event"), record.get("detail") or ""), file=sys.stderr)


def _clock(t: float) -> str:
    return "%7.2fs" % t


def _bars(pose: HeadPose, width: int = 21) -> str:
    return "  ".join(
        "%s %s %+7.1f" % (label, _bar(value, limit, width), value)
        for label, value, limit in (
            ("yaw", pose.yaw, 90.0),
            ("pitch", pose.pitch, 60.0),
            ("roll", pose.roll, 60.0),
        )
    )


def _bar(value: float, limit: float, width: int) -> str:
    half = width // 2
    clamped = max(-limit, min(limit, value))
    offset = int(round(clamped / limit * half))
    cells = ["-"] * width
    cells[half] = "|"
    cells[max(0, min(width - 1, half + offset))] = "#"
    return "".join(cells)


if __name__ == "__main__":
    sys.exit(main())
