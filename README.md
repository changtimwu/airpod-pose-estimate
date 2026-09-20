# airpod-pose-estimate

Head-pose estimation from AirPods motion sensors. Hackathon skeleton: the goal
of this repo is to **prove the underlying mechanism works** — that we can get
trustworthy head orientation off a pair of AirPods, at a usable rate, and turn
it into something an app can act on — *before* committing to what the app is.

We have not picked the demo yet. Candidates, with an honest read on what the
sensor can and cannot support, are in [docs/ideas.md](docs/ideas.md).

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
docs/              architecture, sensor notes and gotchas, demo backlog
scripts/           app-bundle wrapper
data/              recorded sessions (git-ignored)
```

[docs/architecture.md](docs/architecture.md) explains why it is split this way.
[docs/sensor-notes.md](docs/sensor-notes.md) is the important one: rate, drift,
reference frames, and the traps.

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
