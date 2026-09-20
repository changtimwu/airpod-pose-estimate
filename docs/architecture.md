# Architecture

The point of this layout is that the risky part (getting trustworthy motion data
off the AirPods) is isolated from the part we will rewrite ten times during the
hackathon (what the app actually does with a head pose).

```
  AirPods (IMU, ~25 Hz)
        |  Bluetooth, Apple's fusion
        v
  swift-capture/  airpod-motion            <- CoreMotion, Swift, macOS 14+
        |  newline-delimited JSON on stdout (and/or UDP)
        v
  python/airpod_pose
        sources.py     device | udp | file | synthetic
        model.py       Sample, HeadPose
        quaternion.py  orientation math (pure, stateless, unit-tested)
        filters.py     slerp EMA, wrap-aware derivative
        calibration.py "straight ahead" reference frame
        pipeline.py    Sample stream -> HeadPose stream
        gestures.py    HeadPose stream -> GestureEvent stream
        viz.py         live 3D axes + angle history
        cli.py         airpod-pose doctor|record|monitor|gestures|dump|viz
        |
        v
  the demo (not written yet -- see ideas.md)
```

## Why a Swift process plus Python, not one language

`CMHeadphoneMotionManager` is the only way to read AirPods motion, and it is
Objective-C/Swift only. Everything above the driver is easier to iterate on in
Python, and a JSON-lines pipe between the two costs nothing at 25 Hz. It also
buys three things we want for a hackathon:

- **Recording is free.** The wire format is the file format, so
  `airpod-pose record` dumps exactly what the live stream carries and
  `--source file` replays it. Tuning thresholds against a recording beats
  re-performing a gesture twenty times.
- **The hardware is optional.** `--source synthetic` generates scripted motion,
  so the whole Python side (and CI) runs with no AirPods at all.
- **The capture can move.** `--udp host:port` lets the Mac that owns the AirPods
  feed a different machine.

## The seam that matters

Application code consumes `HeadPose` and nothing below it. `HeadPose` carries
the smoothed quaternion, the three Euler angles in degrees, and their rates --
relative to a calibrated reference frame, never to CoreMotion's arbitrary one.
If we swap AirPods for a phone IMU or a webcam later, only `sources.py` and the
frame conventions change.

## State of each layer

| Layer | Status |
| --- | --- |
| `swift-capture` | Works. Streams, mirrors to UDP, exits cleanly on Ctrl-C. |
| `quaternion`, `filters`, `calibration` | Works, unit-tested, conventions pinned. |
| `pipeline` | Works. Auto-calibrates on the first N samples. |
| `gestures` | **Placeholder.** Threshold detectors with guessed constants, enough to prove the stream can trigger things. Expect to replace them. |
| `viz` | Works, deliberately ugly. |
| the app | Not started. |
