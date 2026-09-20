<img width="1142" height="601" alt="image" src="https://github.com/user-attachments/assets/ad3a2980-771f-4cb1-bd05-28e168e354bd" /># airpod-pose-estimate

**Your AirPods already know which way your head is pointing. This repo turns
that into a signal an app can act on.**

---

## The idea in one minute

AirPods Pro, AirPods 3+, AirPods Max and Beats Fit Pro each contain an IMU — an
accelerometer and a gyroscope — that Apple put there for Spatial Audio, so the
sound can stay anchored in place when you turn your head. iOS and macOS fuse
those raw readings into an orientation estimate and hand it to any app through
`CMHeadphoneMotionManager` — 50 times a second on the AirPods Pro 2 we
tested, 25 Hz on older hardware.

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
| Head orientation at 25-50 Hz, already fused and fairly smooth | Position — no leaning distance, no walking, no reaching |
| Reliable *relative* angles (vs. a calibrated forward) | Reliable *absolute* heading — yaw drifts, there is no compass anchor |
| Rotation rates, good enough for nod/shake/tilt detection | Any way to tell "I turned my head" from "I turned my whole body" |
| A signal that survives darkness, pockets and bad lighting | Fine timing — Bluetooth latency makes twitchy input mushy |

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
  from `CMHeadphoneMotionManager` as newline-delimited JSON (50 Hz measured on
  AirPods Pro 2), to stdout and/or a UDP endpoint.
- **Pose pipeline** — Python: calibration to a "straight ahead" reference frame,
  slerp smoothing on the quaternion, wrap-aware angle rates, out to a
  `HeadPose` stream (yaw / pitch / roll in degrees, plus deg/s).
- **Gestures** — placeholder nod / shake / dwell detectors. They fire correctly
  on scripted motion and stay quiet on idle drift. The constants are guesses;
  see [Where to start hacking](#where-to-start-hacking).
- **Tooling** — record and replay sessions, a terminal readout, a live 3D plot,
  and a `doctor` command that tells you which part of the chain is broken.
- **Confirmed on real hardware** — AirPods Pro 2 on macOS 26: permission granted,
  50.0 Hz, steady 20.0 ms between samples, poses tracking correctly through the
  full pipeline. What the sensor gives us is no longer guesswork.
- **Held-pose coach** — capture a pose by holding it, then get live distance,
  hold timing and steadiness, with a left/right comparison at the end. See
  [Demo: the held-pose coach](#demo-the-held-pose-coach).
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
make test       # 48 tests, no hardware needed
make synthetic  # live-looking pose readout from fake data -- start here

make bundle     # compile the Swift tool and wrap it in a .app (see below)
make doctor     # verify the real capture path end to end
make monitor    # live readout from your AirPods
make viz        # live 3D head axes + angle history
```

Put the AirPods in, make sure they are the **selected audio output** (not just
connected), then `make doctor`.

### Two macOS gotchas that cost us an afternoon

Both are now handled in code, but you need to know they exist, because the
failure mode for each is **silence** — no error, no samples, ever.

**1. The permission needs a bundle *and* the right launcher.** AirPods motion is
gated behind Motion & Fitness in TCC. Two conditions:

- the binary must be bundled and ad-hoc signed (`make bundle`), and
- it must be started by **LaunchServices** (`open Foo.app --args …`), not from a
  terminal. TCC blames the *responsible* process for a request, and a
  terminal-launched child inherits the terminal instead of asking for itself.

Started from a shell, the tool sits at `authorization=notDetermined` forever.
Started via `open`, the prompt appears, you click Allow, and samples flow.
Because LaunchServices owns stdout, the app mirrors its stream to UDP and Python
reads that back — `sources.AppSource` does all of it, and `make doctor` reports
which path it took. If you dismissed the prompt, re-enable it under
**System Settings → Privacy & Security → Motion & Fitness**.

**2. Connected is not the same as selected.** Motion only arrives while the
AirPods are the Mac's *active audio output*. Paired-but-idle gives you nothing,
and they auto-switch to your iPhone without saying so — which is exactly how a
working stream goes quiet mid-session. Check with:

```bash
system_profiler SPAudioDataType | grep -B4 "Default Output Device: Yes"
```

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
data/              your recordings (git-ignored); data/samples/ holds a committed one
```

[docs/primer.md](docs/primer.md) walks the data path end to end and explains the
concepts. [docs/architecture.md](docs/architecture.md) explains why it is split
this way. [docs/sensor-notes.md](docs/sensor-notes.md) is the one to read before
trusting a number: rate, drift, reference frames, and the traps.

## What the data looks like

Two levels, and you can inspect both. Everything below is a real excerpt from
[`data/samples/head-shake.jsonl`](data/samples/head-shake.jsonl), recorded off
AirPods Pro 2 on macOS 26 — it is committed, so you can replay it with no
hardware at all.

### Raw: one JSON object per line

A recording opens with a header, then a status record, then samples at 50 Hz:

```jsonl
{"type": "header", "wall": 1789900918.214352, "label": "repeated head shakes, AirPods Pro 2 / macOS 26", "source": "device"}
{"type": "status", "wall": 1789900918.334955, "event": "starting", "detail": "authorization=authorized"}
{"wall": 1789900924.543288, "rot": [0.36711663007736206, -0.00919135008007288, -0.0627526342868805], "q": [0.9497065198316527, -0.08895600808170206, 0.155409124449585, -0.2568897769334656], "seq": 297, "grav": [0.2494824081659317, 0.24881017208099365, -0.9358696937561035], "t": 271850.6476515024, "acc": [0.002883113222196698, -0.008853279985487461, 0.05264042690396309], "euler": {"pitch": -14.407119037912313, "roll": 14.926678449495288, "yaw": -28.374699770984904}, "type": "sample"}
```

That third line is one sample. Rounded and reordered for reading:

```json
{
  "type":  "sample",
  "t":     271850.6477,                               // device clock, seconds
  "wall":  1789900924.5433,                           // unix time, for aligning with other recordings
  "seq":   297,                                       // sample counter; gaps mean dropped samples
  "q":     [0.9497, -0.0890, 0.1554, -0.2569],        // attitude quaternion, [w, x, y, z]
  "euler": {"yaw": -28.37, "pitch": -14.41, "roll": 14.93},  // CoreMotion's own angles, degrees
  "rot":   [0.3671, -0.0092, -0.0628],                // gyro rotation rate, rad/s
  "acc":   [0.0029, -0.0089, 0.0526],                 // acceleration minus gravity, g
  "grav":  [0.2495, 0.2488, -0.9359]                  // gravity direction in head coordinates, g
}
```

Notes that will save you time:

- **Key order varies.** Swift's `JSONEncoder` does not promise field order, so
  parse by name. `sources.py` already does.
- **`t` is the device clock, not wall time.** Use it for anything rate-based —
  Bluetooth delivery jitter lives in arrival time, not in `t`.
- **`q` is the source of truth, `euler` is a convenience.** The pipeline derives
  its own angles from `q` after calibration, with the sign conventions pinned in
  `quaternion.py`. CoreMotion's `euler` is raw, uncalibrated, and uses its own
  reference frame — handy for eyeballing, not for logic.
- **Every record carries `type`.** `header` once, `status` on connect /
  disconnect / error, `sample` for data. Filter before parsing.
- **`loc` tells you which bud the sample came from** (`left` / `right` /
  `default`). CoreMotion delivers one fused stream and picks the source itself;
  it can switch mid-session, and the orientation may jump when it does. The
  committed sample above predates this field, so live streams have one more key
  than that excerpt shows. There is no way to read both buds at once -- see
  [docs/sensor-notes.md](docs/sensor-notes.md).

### What movement actually looks like

The same recording, after calibration and smoothing, during one left-right swing
(every 4th pose, so 80 ms per row):

```
 time    yaw    pitch    roll   yaw_rate
 0.00   -0.3     -9.3    +3.5      +16 deg/s
 0.08   +1.0     -7.7    +4.0      +18
 0.16   +2.8     -6.6    +3.2      +27
 0.24   +5.7     -6.2    +0.8      +38     <- turning one way
 0.32   +7.3     -5.4    -1.0       +7     <- momentarily still
 0.40   +6.8     -5.0    -0.5      -12
 0.48   +5.3     -5.3    +1.3      -24
 0.56   +2.9     -6.8    +2.6      -34     <- coming back
 0.64   -0.2     -9.7    +2.5      -41
 0.72   -4.3    -13.6    -0.0      -61
```

That sign change in `yaw_rate` is exactly what `OscillationDetector` counts: a
shake is several of them inside about a second, while turning to look at
something is one crossing and then a hold.

### Derived: the `HeadPose` stream

`airpod-pose dump` emits the calibrated, smoothed poses application code
consumes — one per line, ready to pipe into anything:

```bash
airpod-pose dump --source file --path data/samples/head-shake.jsonl --fast
```

```jsonl
{"t": 271850.9277, "q": [0.9388, 0.0112, 0.2599, -0.2259], "yaw": -28.743, "pitch": -29.5353, "roll": -6.3661, "yaw_rate": 5.1083, "pitch_rate": -6.6594, "roll_rate": -2.6382}
{"t": 271850.9476, "q": [0.9388, 0.0116, 0.2606, -0.2249], "yaw": -28.6081, "pitch": -29.638, "roll": -6.3026, "yaw_rate": 6.7537, "pitch_rate": -5.1435, "roll_rate": 3.1764}
```

### Replay the sample, no AirPods required

```bash
airpod-pose monitor  --source file --path data/samples/head-shake.jsonl   # watch it in real time
airpod-pose gestures --source file --path data/samples/head-shake.jsonl --fast
```

Because the wire format *is* the file format, a recording replays byte-for-byte
what the live stream carried — which is why tuning against recordings works.

## Demo: the held-pose coach

The first thing here that is a *demo* rather than a tool. Built for
[Trikonasana](https://github.com/changtimwu/airpod-pose-estimate/issues/3), but
nothing in it is yoga-specific — it recognises any orientation you can hold.

```bash
make bundle                                              # once
make capture NAME=mountain        LABEL="Mountain"       # stand up, hold 5 s
make capture NAME=triangle_right  LABEL="Triangle (right)"
make capture NAME=triangle_left   LABEL="Triangle (left)"
make asana                                               # the coach
```

Each `capture` gives you five seconds to get into position, then averages a
second of samples into a reference and reports how much you moved while it was
recording — a reference captured while wobbling is one nobody can hit twice.

`make asana` then shows, live:

```
  steadiness   4.2 deg/s  [############----]
> Triangle (right)      6.1 deg [##################--]  [######----] 3.1/5.0s
  Triangle (left)      88.4 deg [##------------------]
  Mountain             71.2 deg [####----------------]

   12.44s  ** HELD triangle_right for 5.0s, steadiness 4.2 deg/s
```

and on exit, the comparison that is the actual point:

```
--- session ---
  Triangle (right)       held  11.4s   wobble  4.2 deg/s
  Triangle (left)        held   9.8s   wobble  7.1 deg/s

steadiest hold: Triangle (right) (4.2 deg/s)
```

### Why it is built this way

**Poses are captured, not typed as angle ranges.** Euler bands break down exactly
where yoga lives: with 0.5° of real noise, reported roll wobbles ±14° at 88° of
pitch, so a band there thresholds noise ([sensor-notes.md](docs/sensor-notes.md)).
Matching is `angle_between` against a captured quaternion — one number,
continuous through vertical, no parameterisation to go singular. It also means
nobody has to guess what "Triangle" is in degrees.

**Steadiness is the signal that always works.** `‖rate‖` over the hold needs no
reference, no calibration and no tuning, cannot drift, and does not care where
the sensor is mounted. It is also the honest thing to report: it says what
happened ("steadier on the right") instead of prescribing a target angle, which
matters when the one thing this sensor cannot see is neck strain.

**Nothing assumes a head.** An AirPod in an ear, banded to a forearm, or taped to
a broom handle all work identically — calibrate a neutral, capture references,
match. That keeps the demo alive whichever way the
[placement question](https://github.com/changtimwu/airpod-pose-estimate/issues/3)
lands.

### Tuning without a body

Everything runs off recordings and fake data too, so you can iterate on the
couch:

```bash
airpod-pose asana --source file --path data/samples/head-shake.jsonl --fast
airpod-pose asana --source synthetic --fast
```

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
live stream carried — see [What the data looks like](#what-the-data-looks-like)
for an annotated excerpt.

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
- The rate is fixed by the OS (50 Hz measured here, 25 Hz on older hardware),
  so a fast nod is only a couple of dozen samples long.
- Motion can switch between buds mid-session, which shows up as an orientation
  jump with no notification.

## License

MIT — see [LICENSE](LICENSE).
