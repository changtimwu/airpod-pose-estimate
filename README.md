# airpod-pose-estimate

**Your AirPods already know which way your head is pointing. This repo turns
that into a signal an app can act on.**

---

## The idea in one minute

AirPods Pro, AirPods 3+, AirPods Max and Beats Fit Pro each contain an IMU — an
accelerometer and a gyroscope — that Apple put there for Spatial Audio, so the
sound can stay anchored in place when you turn your head. iOS and macOS fuse
those raw readings into an orientation estimate and hand it to any app through
`CMHeadphoneMotionManager`, about 25 times a second.

That means **anyone wearing modern AirPods is already wearing a head tracker**,
and it has properties a camera does not:

- it works in the dark, from any angle, with nothing pointed at your face
- it keeps working while you walk around, or while the phone is in your pocket
- nothing leaves the device, and there is no video to worry about
- it costs nothing extra — millions of people are already wearing the hardware

Our hackathon question is what to *do* with that. This repo is the part that
comes first: getting the signal out cleanly and proving it is good enough to
build on.

## What "pose" means here

Pose = the orientation of your head, expressed as three angles relative to a
"looking straight ahead" reference we capture during calibration:

```
                    ^ up (+z)
                    |                pitch  nodding "yes"
                    |                       + = looking up
      looking       |    yaw   shaking "no"
      left (+y) <---o---> forward (+x)      + = turning left
                   /                 roll   tilting ear to shoulder
                  /                         + = crown tips right
                 v  (roll rotates about the forward axis)
```

Every angle is in degrees, and each one comes with its rate of change in
degrees per second. A nod is pitch swinging down-and-back-up; a shake is yaw
oscillating; "looking left" is yaw holding past a threshold for a while. That
is the entire vocabulary the sensor gives us — and it is more than it sounds.

## What the signal can and cannot do

The honest version, because it determines which demos are even possible:

| We get | We do **not** get |
| --- | --- |
| Head orientation, ~25 Hz, already fused and fairly smooth | Position — no leaning distance, no walking, no reaching |
| Reliable *relative* angles (vs. a calibrated forward) | Reliable *absolute* heading — yaw drifts, there is no compass anchor |
| Rotation rates, good enough for nod/shake/tilt detection | Any way to tell "I turned my head" from "I turned my whole body" |
| A signal that survives darkness, pockets and bad lighting | Fine timing — Bluetooth latency plus 25 Hz makes twitchy input mushy |

So: gestures, dwell-based control, posture and attention tracking, head-steered
views — all realistic. Anything needing a compass heading, a position in space,
or millisecond precision — not with this sensor alone.

## Why this repo exists

We had the idea before we had the app, so we deliberately built the plumbing
first and left the demo open. Three questions had to be answered before the
choice of demo mattered at all:

1. **Can we get the data at all?** (macOS permissions, device support, rate)
2. **Is it clean enough to act on?** (drift, smoothing, reference frames)
3. **Can it trigger something reliably?** (gestures, with false positives low
   enough that a live demo does not embarrass us)

All three now have a working answer you can run. The demo candidates, scored
against the table above, are in **[docs/ideas.md](docs/ideas.md)** — that is the
document to read if you are here to argue about what we should build.

## Try it in 60 seconds, no AirPods needed

```bash
make setup      # venv + install
make synthetic  # live pose readout driven by fake, scripted head motion
```

You will see the three angles moving as bars, and nod / shake / dwell events
firing as they occur. Everything except the driver itself is exercised by that
one command, which is also how CI tests the repo and how teammates without
compatible AirPods can still contribute.

New to the code? Read **[docs/primer.md](docs/primer.md)** — it walks the whole
path from raw sensor to gesture event in about ten minutes, and explains the
parts (quaternions, calibration, smoothing) that look like magic otherwise.

---

## What works today

- **Capture** — a Swift CLI (`airpod-motion`) streams fused head orientation
  from `CMHeadphoneMotionManager` as newline-delimited JSON, ~25 Hz, to stdout
  and/or a UDP endpoint.
- **Pose pipeline** — Python: calibration to a "straight ahead" reference frame,
  slerp smoothing on the quaternion, wrap-aware angle rates, out to a
  `HeadPose` stream (yaw / pitch / roll in degrees, plus deg/s).
- **Gestures** — placeholder nod / shake / dwell detectors. They fire correctly
  on scripted motion and stay quiet on idle drift. The constants are guesses;
  see [Where to start hacking](#where-to-start-hacking).
- **Tooling** — record and replay sessions, a terminal readout, a live 3D plot,
  and a `doctor` command that tells you which part of the chain is broken.
- **No hardware required** — `--source synthetic` drives the whole Python side
  with scripted fake motion, so teammates without compatible AirPods (and CI)
  can still work on everything above the driver.

## Requirements

- macOS 14+ with a Swift toolchain (Xcode **not** required; Command Line Tools
  is enough — `swift build` works).
- Python 3.9+.
- AirPods Pro / AirPods 3+ / AirPods Max / Beats Fit Pro. **AirPods 1 & 2 have no
  IMU** and cannot do this.

## Quickstart

```bash
make setup      # venv + editable install of the python package
make test       # 44 tests, no hardware needed
make synthetic  # live-looking pose readout from fake data -- start here

make bundle     # compile the Swift tool and wrap it in a .app (see below)
make doctor     # verify the real capture path end to end
make monitor    # live readout from your AirPods
make viz        # live 3D head axes + angle history
```

Put the AirPods in, make sure they are the **selected audio output** (not just
connected), then `make doctor`.

### The macOS permission wrinkle

AirPods motion is gated behind **Motion & Fitness** in TCC, and macOS only shows
that prompt for a *bundled, signed* app. A bare `swift build` binary receives
zero samples, forever, with no error. `make bundle` wraps the binary in a
minimal ad-hoc-signed `AirPodMotion.app` so the prompt appears; the Python side
prefers that bundled copy automatically. If you dismissed the prompt, re-enable
it under **System Settings → Privacy & Security → Motion & Fitness**.

## Layout

```
swift-capture/     Swift package -> airpod-motion (CoreMotion -> JSON lines)
python/airpod_pose/
  sources.py       device | udp | file replay | synthetic
  quaternion.py    orientation math; the axis/sign conventions live here
  filters.py       slerp EMA, wrap-aware derivative
  calibration.py   captures "straight ahead" as the reference frame
  pipeline.py      Sample stream -> HeadPose stream   <- the app-facing seam
  gestures.py      HeadPose stream -> GestureEvent stream   <- placeholder
  viz.py           matplotlib live 3D view
  cli.py           airpod-pose doctor|record|monitor|gestures|dump|viz
docs/              primer, architecture, sensor notes and gotchas, demo backlog
scripts/           app-bundle wrapper
data/              recorded sessions (git-ignored)
```

[docs/primer.md](docs/primer.md) walks the data path end to end and explains the
concepts. [docs/architecture.md](docs/architecture.md) explains why it is split
this way. [docs/sensor-notes.md](docs/sensor-notes.md) is the one to read before
trusting a number: rate, drift, reference frames, and the traps.

## Using it as a library

```python
from airpod_pose import PosePipeline, sources
from airpod_pose.gestures import GestureRecognizer

pipeline = PosePipeline(smoothing=0.35)
recognizer = GestureRecognizer()

for pose in pipeline.run(sources.samples(sources.DeviceSource())):
    print(f"yaw={pose.yaw:+6.1f} pitch={pose.pitch:+6.1f} roll={pose.roll:+6.1f}")
    for event in recognizer.feed(pose):
        print("gesture:", event.name, event.confidence)
```

Swap `DeviceSource()` for `SyntheticSource()` or `FileSource(path)` and nothing
else changes.

## Recording and replaying

Tuning thresholds against a live head is miserable — record once, iterate offline:

```bash
.venv/bin/airpod-pose record --out data/nod-01.jsonl --seconds 20 --label "3 slow nods"
.venv/bin/airpod-pose gestures --source file --path data/nod-01.jsonl --fast
```

The wire format is the file format, so a recording is byte-for-byte what the
live stream carried.

## Where to start hacking

1. **Verify the axis signs on real hardware** (`make monitor`, turn left, check
   yaw goes positive). Conventions are pinned in `quaternion.py` and enforced by
   tests, but they have not been confirmed against a real head yet.
2. **Replace `gestures.py`.** It exists to prove the stream can trigger
   something, not to be good. Record sessions, then tune or train against them.
3. **Pick a demo** from `docs/ideas.md` and build it on `HeadPose`. Application
   code should not need to know CoreMotion exists.

## Known limitations

- No position, only orientation — leaning distance and walking are out.
- Absolute yaw drifts; only relative angles are dependable. Re-calibrate often.
- The IMU cannot distinguish "turned my head" from "turned my whole body".
- ~25 Hz is fixed by the OS, so fast gestures are only ~8-12 samples long.
- Motion can switch between buds mid-session, which shows up as an orientation
  jump with no notification.

## License

MIT — see [LICENSE](LICENSE).
