# Primer: from a tilted head to a gesture event

Ten-minute read for anyone about to touch the code. It follows one sample all
the way through, and explains the three things that look like magic if you have
not done IMU work before: quaternions, calibration, and smoothing.

If you only want to know what the project *is*, the README covers that. This is
the layer below.

---

## 1. Where the numbers come from

Inside each AirPod is an accelerometer (which feels gravity and shoving) and a
gyroscope (which feels rotation). Neither is useful raw:

- The **accelerometer** tells you which way is down — but it cannot tell gravity
  apart from acceleration, so it lies whenever you move.
- The **gyroscope** tells you how fast you are turning — but you have to add up
  those readings to know where you are pointing, and the small errors add up
  too. Left alone, it drifts away within seconds.

Fusing them fixes both: the gyro handles fast motion, the accelerometer keeps
pulling the estimate back to true vertical. **Apple already does this for us**
and hands over the fused result, which is why there is no filter of our own in
this repo. What we receive per sample:

| Field | Meaning |
| --- | --- |
| `q` | the fused orientation, as a quaternion |
| `rot` | rotation rate from the gyro, rad/s |
| `acc` | acceleration with gravity subtracted, g |
| `grav` | which way gravity points, in head coordinates |
| `t` | device timestamp, seconds — **use this, not arrival time** |

The rate is whatever the OS decides: we measured a rock-steady **50 Hz**
(20.0 ms between samples) on AirPods Pro 2 with macOS 26, while older hardware
is widely reported at 25 Hz. Derive `dt` from `t` rather than assuming either.

One caveat inherited from the physics: fusion fixes *pitch and roll* drift,
because gravity gives an absolute reference for "down". Nothing gives an
absolute reference for "north", so **yaw still drifts**. That single fact is why
calibration exists and why no demo here should depend on absolute heading.

## 2. Why orientations are quaternions, not three angles

Three angles are how humans think, but they break in two ways that will bite a
live demo:

- **Gimbal lock.** Look straight up and yaw and roll stop being distinguishable
  — the math collapses and angles jump around wildly.
- **Wrap-around.** 179° and −179° are two degrees apart, but naive arithmetic
  says they are 358° apart. Average them and you get 0°: exactly backwards.

A quaternion `(w, x, y, z)` is four numbers describing "rotate by this much
about this axis". It has no lock, no wrap, and composing rotations is one
multiply. The rules of thumb in this codebase:

> **Store and filter quaternions. Convert to angles only at the edge, for
> humans, thresholds, and plots.**

You mostly do not need the algebra. `quaternion.py` wraps what we use:

```python
from airpod_pose import quaternion as quat

quat.relative(reference, current)   # "how far from straight ahead?"
quat.to_euler(q)                    # -> (yaw, pitch, roll) in degrees
quat.slerp(a, b, 0.3)               # blend two orientations, the correct way
quat.rotate_vector(q, quat.FORWARD) # where is the nose pointing?
```

Sign conventions are pinned at the top of that module and enforced by tests:
yaw+ = turning left, pitch+ = looking up, roll+ = tilting right.

This is not just theory: with the head near vertical, two poses whose yaw and
roll differ by 10 deg each can be **0.17 deg apart physically**. If your app has
steep head positions in it, classify with `angle_between` or by where a body
axis points, never with a threshold on yaw or roll. Numbers in
[sensor-notes.md](sensor-notes.md).

## 3. Calibration: what "straight ahead" means

When the stream starts, CoreMotion invents a reference frame. It is not
world-aligned, not north-aligned, and **not the same between two runs**. So a
raw yaw of 40° means nothing on its own.

The fix is to pick our own zero. `Calibrator` averages a short window of samples
— you sit still, looking forward — and calls that identity. Every pose after
that is expressed *relative* to it:

```
pose = reference⁻¹ × current
```

Two details worth knowing, both already handled in `calibration.py`:

- Averaging quaternions naively is wrong, because `q` and `−q` are the same
  rotation and cancel each other out in a sum. We flip everything into the same
  hemisphere first.
- If your head moved during the capture window, the average is garbage. The
  calibrator measures the spread and rejects the window rather than locking in a
  bad zero — which is why `--calibration-window` samples sometimes take a moment
  to settle.

Because yaw drifts, **re-calibrating is normal**, not a failure. Any demo we
build should have a cheap "reset to forward" cue.

## 4. Smoothing, and the tradeoff you cannot escape

Raw poses jitter by a degree or two. On screen it looks broken; on a threshold
it causes double-triggers. We smooth with an exponential moving average done on
the quaternion (`slerp` toward each new reading), so nothing breaks at the wrap
or near gimbal lock.

One knob, `--smoothing` (alpha, 0–1):

```
alpha = 0.6   snappy, still a bit jittery     <- gesture triggers
alpha = 0.35  the default, ~30 ms of lag at 50 Hz
alpha = 0.15  glassy smooth, visibly laggy    <- viewers, posture tracking
```

There is no free lunch here: smoothing *is* delay. A fast nod lasts a few tenths
of a second — a couple of dozen samples at 50 Hz, half that on 25 Hz hardware —
so over-smooth it and the gesture is gone before the detector sees it. If the
demo ever needs both calm visuals and fast triggers, run two pipelines with
different alphas off the same source rather than compromising on one number.

## 5. Sample → HeadPose → GestureEvent

That is the whole chain, and it is three lines of code:

```python
from airpod_pose import PosePipeline, sources
from airpod_pose.gestures import GestureRecognizer

pipeline = PosePipeline(smoothing=0.35)
recognizer = GestureRecognizer()

for pose in pipeline.run(sources.samples(sources.SyntheticSource())):
    print(pose.yaw, pose.pitch, pose.roll, pose.yaw_rate)
    for event in recognizer.feed(pose):
        print("gesture:", event.name, event.confidence)
```

`HeadPose` is the seam application code sits on. It carries the smoothed
quaternion, the three angles, and their rates — always relative to the
calibrated frame. **Nothing above this line should know CoreMotion exists**, so
that swapping in a phone IMU or a webcam later touches only `sources.py`.

Swap `SyntheticSource()` for `DeviceSource()` (real AirPods),
`FileSource(path)` (replay a recording) or `UDPSource()` (capture on another
Mac). Nothing else in your code changes — which is the point.

## 6. How the placeholder detectors work

Two shapes cover most head gestures, and both are in `gestures.py`:

**`OscillationDetector`** — nod, shake. It watches the signed *rate* on one
axis, ignores anything under a threshold as drift, and fires when it sees
several sign changes inside a time window. Using sign changes rather than angle
is what separates "I shook my head" from "I turned to look at something" — a
plain angle threshold cannot tell those apart.

**`HoldDetector`** — look-left, lean, dwell. Fires when an *angle* stays past a
threshold for long enough. This is the one to build menus and pointing on.

Both take a cooldown, because one physical nod contains several swings and will
otherwise fire three times.

Adding your own is a `feed(pose) -> Optional[GestureEvent]` method:

```python
class LookDownDetector(GestureDetector):
    name = "look_down"

    def feed(self, pose):
        if pose.pitch < -30 and pose.pitch_rate > -5:  # down and settled
            return GestureEvent(name=self.name, t=pose.t, confidence=1.0)
        return None

recognizer = GestureRecognizer([LookDownDetector()])
```

Note that this one stays silent on `--source synthetic`: the fake script only
performs nod, shake, look-left and lean, and the `pitch_rate` condition
deliberately ignores the transient of a nod. That is the detector working, not
failing — record yourself actually looking down to exercise it.

**Tune against recordings, not against your own head.** Performing a gesture
twenty times in a row is both miserable and unrepresentative:

```bash
airpod-pose record --out data/nod-01.jsonl --seconds 20 --label "3 slow nods"
airpod-pose gestures --source file --path data/nod-01.jsonl --fast
```

The wire format is the file format, so a recording replays exactly what the live
stream carried, and `--fast` means a 20-second session re-tests in milliseconds.

## 7. Debugging order

When something looks wrong, work down the stack — the `doctor` command exists to
tell you which layer broke:

1. `make doctor` — are samples arriving at all, and at what rate? Zero samples is
   almost always the macOS permission prompt (see the README) or the AirPods not
   being the *selected* audio output.
2. `make monitor` — do the bars move the right way when you turn your head? A
   flipped sign found late is a 20-minute bug.
3. `make viz` — does the 3D head frame track you, or does it swim and drift?
4. `airpod-pose gestures --source synthetic --fast` — if the detectors misbehave
   on known-good scripted motion, the bug is in the detector, not the hardware.

## Glossary

| Term | In one line |
| --- | --- |
| **IMU** | The accelerometer + gyroscope package inside the bud. |
| **Sensor fusion** | Combining them into one orientation estimate. Apple does it; we consume it. |
| **Attitude / pose / orientation** | The same thing here: which way the head points. |
| **Quaternion** | Four numbers encoding a rotation, with no gimbal lock or wrap problems. |
| **Euler angles** | Yaw / pitch / roll. Human-readable, math-hostile. |
| **Reference frame** | The orientation we call zero. Ours comes from calibration. |
| **Drift** | Slow error accumulation. Ours shows up in yaw, not pitch/roll. |
| **Gimbal lock** | Angles collapsing when you look straight up or down. |
| **Slerp** | Interpolation between two orientations along the shortest arc. |
| **Dwell** | Holding a pose as a deliberate input, instead of clicking. |

## Where to go next

- [architecture.md](architecture.md) — why the Swift/Python split, and what state each layer is in.
- [sensor-notes.md](sensor-notes.md) — hardware facts and traps: rate, bud switching, permissions.
- [ideas.md](ideas.md) — the demo backlog, scored against what this sensor can actually deliver.
