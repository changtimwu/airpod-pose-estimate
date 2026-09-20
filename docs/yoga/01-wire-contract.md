# Wire contract — yoga alignment coach

**Status: proposed. Freeze at T+05, then additive changes only.**

Everything that crosses a boundary between two people. Every decision has a
recommended default already filled in, so the standup is "any objections?" and
not a design discussion.

This document is written against the code that already exists in this repo. Where
the repo has already settled a question, the answer below is *what the code does*,
not a fresh opinion — see [`architecture.md`](../architecture.md) and
[`sensor-notes.md`](../sensor-notes.md).

---

## 1. Decisions to confirm right now

Twelve. Four are already settled by existing code and are listed so nobody
re-opens them. **D5 is the only genuine architectural call.**

| ID | Decision | Default | Owner | Cost if changed late |
|----|----------|---------|-------|----------------------|
| D1 | Transport | **SSE** for state, `POST` for commands. Stdlib only, no pip install | Bridge | Low |
| D2 | Host & port | `:8765` serves API *and* frontend — one origin, no CORS | Bridge | Low |
| D3 | Angle units | **Settled: degrees.** `HeadPose` is already degrees, rates deg/s | — | — |
| D4 | Axis convention | **Settled in `quaternion.py`**, unit-tested. See §2 | — | — |
| D5 | Who owns session state | **Server authoritative.** Browser is a pure renderer | All | **Very high** |
| D6 | Pose vocabulary | Five frozen `snake_case` ids (§5) | Signal | Medium |
| D7 | Message envelope | `{v, type, t, …}` both directions | Bridge | Medium |
| D8 | State vs. events | Full snapshot at 25 Hz + discrete one-shot events | Bridge | Medium |
| D9 | Calibration | **Partly settled:** `calibration.py` exists, `pipeline` auto-calibrates on first N samples. We add an explicit re-zero command | Signal | Medium |
| D10 | Status vocabulary | Seven frozen strings (§6) | Bridge | Medium |
| D11 | DOM contract | JS writes `data-*`, CSS reads them. Neither crosses | Interface + Experience | **High** |
| D12 | Tuning surface | Bands in `poses.json`, re-read on every command, never in code | Signal | Medium |

### On D5

Hold timing needs the 25 Hz sample stream and hysteresis, which only Python has.
Splitting the state machine across the wire produces sync bugs that are
unreproducible under demo pressure. Server-authoritative also means a second
laptop on the projector shows an identical session for free.

The cost: Bridge is not a dumb pipe. Budget for that.

---

## 2. Axis convention

**Do not invent a new one.** `quaternion.py` has these pinned and unit-tested:

```
body frame:  x = forward (nose)   y = left (ear)   z = up (crown)

yaw   > 0   turning left
pitch > 0   looking up
roll  > 0   tilting to the right
```

Note the pitch sign is deliberately flipped from textbook aerospace Z-Y-X so
that "up" is positive.

### Forearm remapping

Those names describe a bud in an ear. Ours is banded to a **left forearm**, so
the same three numbers mean something different. The mapping depends on which
way the bud faces on the arm, so **it must be measured, not assumed**:

| Angle | Expected forearm meaning | Trust |
|-------|--------------------------|-------|
| `pitch` | Forearm elevation. Arm down ≈ most negative, level ≈ 0, overhead ≈ most positive | Absolute |
| `roll` | Rotation about the forearm's long axis — palm orientation | Absolute |
| `yaw` | Heading of the forearm relative to calibration | **Drifts** |

### Two rules that follow

**Classify on `pitch` and `roll` only.** AirPods have no magnetometer. Gravity
anchors pitch and roll, so both are drift-free indefinitely. Yaw has nothing to
anchor it and wanders several degrees per minute from gyro integration alone —
`sensor-notes.md` already flags this. Yaw ships in the payload for the arm
visualisation and is **never** an input to a pose matcher. If a classifier
"works at the desk and fails after ten minutes", this is why.

**Verify the signs on hardware in the first ten minutes.** The repo's own notes
mark these as unverified. Band the bud on, calibrate with the arm hanging, then
raise it slowly overhead while watching `make monitor`. Pitch must sweep
monotonically in one direction. If it runs backwards or wraps, fix the sign once
in `poses.py` and tell everyone. Sixty seconds now, or a twenty-minute bug at
T+50.

---

## 3. Layer map

```
AirPod  →BLE→  airpod-motion  →NDJSON→  sources.py → pipeline.py
                                              ↓ HeadPose
                                          poses.py  (new — Signal)
                                              ↓ PoseState
                                          server.py (new — Bridge)
                                              ↓ SSE + POST
                                          web/      (new — Interface + Experience)
```

| Boundary | Status |
|----------|--------|
| **A** · Swift → Python | **Exists. Do not modify.** NDJSON, ~25 Hz. `--source synthetic` and `--source file` emit identical frames, which is what lets three people work without hardware. |
| **B** · `pipeline` → classifier | **`HeadPose` is the existing seam** and `architecture.md` is explicit that app code consumes it and nothing below. Our classifier is a `HeadPose` consumer. It replaces the placeholder detectors in `gestures.py`. |
| **C** · Bridge → browser | New. §4. The contract that matters. |
| **D** · Interface ↔ Experience | New. §8. DOM only. |

---

## 4. Layer C — Bridge to browser

Two message types server→client over **SSE** (`GET /stream`), one client→server as
a plain **`POST /command`**. Every message carries `v`, `type` and `t`.
**Unknown fields are ignored, never rejected**, so the schema can grow
mid-hackathon without breaking anyone.

SSE rather than WebSocket because the package has **zero runtime dependencies**
and we are keeping it that way: `EventSource` reconnects by itself, the server
is stdlib `http.server`, and nobody runs `pip install` on four laptops.

### `frame` — server→client via SSE, ~25 Hz, full snapshot

Complete state every tick. The renderer never accumulates — it discards the
previous frame and draws this one. No sync bugs are possible when there is
nothing to keep in sync.

The `arm` block is `HeadPose.as_dict()` with the rates dropped. Reuse the method;
do not hand-roll a second serialiser.

```jsonc
{
  "v": 1,
  "type": "frame",
  "t": 1043.28,              // HeadPose.t — monotonic DEVICE clock, seconds.
                             // Use this for anything rate-based, not arrival time.
  "wall": 1758300512.345,    // unix seconds, for logs only
  "status": "active",        // §6 enum

  "arm": {
    "pitch": -87.4,          // degrees, relative to calibration
    "roll": 2.1,
    "yaw": 13.8,             // display only — drifts, never classified on
    "quality": "good"        // good | noisy | stale
  },

  "pose": {
    "target": "warrior_ii",
    "detected": "warrior_ii", // or null
    "match": true,
    "confidence": 0.92,       // 0..1
    "error_deg": 3.2,         // distance from band centre
    "hold_ms": 4200,          // resets to 0 on loss
    "target_ms": 8000
  },

  "session": {
    "index": 1,               // 0-based cursor
    "total": 5,
    "sequence": ["mountain", "warrior_ii", "upward_salute",
                 "triangle", "side_angle"],
    "score": 0.87,            // 0..1 running mean steadiness
    "elapsed_ms": 45200
  }
}
```

### `event` — server→client via SSE, on transition only

One-shot triggers for animation and sound. Never carries state — if the client
misses one, the next `frame` still corrects it. This split is what lets
Experience hang celebrations off transitions without Interface tracking edges.

```jsonc
{
  "v": 1, "type": "event", "t": 1043.28,
  "event": "pose_complete",
  "pose": "warrior_ii",
  "hold_ms": 8000,
  "steadiness": 0.91          // 1 − normalised angle variance
}
```

Frozen event vocabulary:

| Event | Meaning |
|-------|---------|
| `calibrated` | Zero captured, flow may start |
| `pose_entered` | Target matched, hold timer running |
| `pose_lost` | Dropped out before `target_ms` |
| `pose_complete` | Held full duration, cursor advances |
| `session_complete` | Last pose done |
| `device_lost` | No samples for 1000 ms |
| `device_found` | Samples resumed |

### `command` — client→server, `POST /command`

No correlation ids, no acks. The server acts and the next `frame` reflects it —
which *is* the acknowledgement. Returns `200` if accepted, `409` if the command
is invalid in the current status (e.g. `start` before calibrating).

```jsonc
{ "v":1, "type":"command", "cmd":"calibrate" }
{ "v":1, "type":"command", "cmd":"start" }
{ "v":1, "type":"command", "cmd":"skip" }    // demo escape hatch — build it first
{ "v":1, "type":"command", "cmd":"reset" }
```

> **`skip` is not a nice-to-have.** When a pose refuses to trigger in front of
> judges, a skip key turns a dead demo into a smooth one and the audience never
> knows. Bind it to a keyboard shortcut as well as a control.

---

## 5. Pose vocabulary & tuning file

Ids are frozen strings shared by Python, JS and CSS. **The bands below are
hypotheses.** Owner 01 replaces them with measured values in the first ten
minutes — the whole reason they live in YAML is so tuning needs no code change
and no restart.

```jsonc
// python/airpod_pose/poses.json — Signal owns this file, everyone reads the ids
// JSON not YAML: stdlib has no YAML parser and we have zero dependencies.
version: 1
sequence: [mountain, warrior_ii, upward_salute, triangle, side_angle]

poses:
  mountain:
    label_en: "Mountain"
    label_sa: "Tadasana"
    hold_ms: 3000
    pitch: [-90, -72]        # entry band, degrees, post-calibration
    roll:  [-180, 180]       # unconstrained
    exit_margin_deg: 8

  warrior_ii:
    label_en: "Warrior II"
    label_sa: "Virabhadrasana II"
    hold_ms: 8000
    pitch: [-12, 12]
    roll:  [-30, 30]
    exit_margin_deg: 8

  upward_salute:
    label_en: "Upward Salute"
    label_sa: "Urdhva Hastasana"
    hold_ms: 5000
    pitch: [72, 90]
    roll:  [-45, 45]
    exit_margin_deg: 8

  triangle:
    label_en: "Triangle"
    label_sa: "Trikonasana"
    hold_ms: 6000
    pitch: [58, 88]
    roll:  [45, 135]         # roll is what separates this from upward_salute
    exit_margin_deg: 8

  side_angle:
    label_en: "Extended Side Angle"
    label_sa: "Utthita Parsvakonasana"
    hold_ms: 6000
    pitch: [28, 56]
    roll:  [-45, 45]
    exit_margin_deg: 8
```

### Hysteresis — do not skip this

A pose is **entered** when the angles fall inside the band, and **lost** only
once they exit the band widened by `exit_margin_deg`.

Without it the state flickers at the boundary at 25 Hz, the hold timer resets
constantly, and the UI strobes. Three lines of code, and it is the whole
difference between a demo that looks solid and one that looks broken.

### If you are behind at T+40

**Ship three poses, not five.** `mountain`, `warrior_ii` and `upward_salute` are
furthest apart in pitch and therefore most reliable on stage. `triangle` and
`side_angle` are separated largely by roll, which is noisier on a forearm and
will misfire under demo nerves.

---

## 6. Status vocabulary

Seven strings. Every one needs a visual treatment, so this list is also a screen
inventory for Owner 04.

| Value | Meaning | What the user sees |
|-------|---------|--------------------|
| `disconnected` | SSE stream down (browser-only — the server never sends this) | Reconnecting indicator, last frame greyed |
| `no_device` | Connected, no samples arriving | "Check the AirPod" + rig checklist |
| `uncalibrated` | Samples arriving, no zero captured | Calibration invitation — the opening screen |
| `calibrating` | Averaging the 2 s window | Countdown, "stand still, arm down" |
| `ready` | Zeroed, flow not started | Start control, sequence preview |
| `active` | Flow running | Main screen: dial, target, hold ring |
| `complete` | Sequence finished | Score summary, restart |

---

## 7. Calibration protocol

`pipeline.py` already auto-calibrates on the first N samples. We add an
**explicit re-zero** on top, because the band slips and the arm gets re-strapped
between runs.

1. User stands in Mountain, left arm hanging, bud banded to the forearm.
2. Client sends `{"cmd": "calibrate"}`.
3. Status → `calibrating` for **2000 ms**.
4. Signal averages attitude over the window. If angular variance exceeds **5°**,
   reject and stay `uncalibrated` — the user was moving.
5. On success: store the reference quaternion, emit `calibrated`, status → `ready`.

### Rules everyone honours

- **Every angle on the wire is post-calibration.** Raw CoreMotion attitude never
  crosses a boundary. Its reference frame is arbitrary and not repeatable between
  runs — see `sensor-notes.md`.
- **Recalibration is available from any status.**
- **Recalibrate immediately before the demo**, facing the direction you will
  present from. This is a line in the rehearsal script, not an optional step.

### Bud handoff

`sensor-notes.md` warns that motion comes from whichever bud Apple considers
primary and can switch mid-session, causing an orientation discontinuity with no
notification.

Two mitigations, both cheap:

- **Physical:** leave the right bud in the charging case. One active bud, no
  arbitration. Turn Automatic Ear Detection off.
- **Software:** if `sensorLocation` changes, force status back to `uncalibrated`.
  The reference frame is void and every angle after it is a lie.

---

## 8. DOM contract

The boundary between Owner 03 and Owner 04, and the one most likely to cause a
merge conflict at T+45. The rule is absolute: **JavaScript writes data
attributes, CSS reads them.** Interface never sets a style; Experience never
writes a line of JS.

```js
// Interface writes exactly these, and only these
document.body.dataset.status  = "active";      // §6 enum
document.body.dataset.pose    = "warrior_ii";  // current target
document.body.dataset.match   = "true";        // "true" | "false"
document.body.dataset.quality = "good";

// live numbers as CSS custom properties — CSS animates them directly
root.style.setProperty("--arm-pitch",  pitch + "deg");
root.style.setProperty("--arm-roll",   roll  + "deg");
root.style.setProperty("--hold-pct",   pct);   // 0..1
root.style.setProperty("--error-norm", err);   // 0..1, 0 = perfect
```

Stable ids, never renamed after T+05:

```
#arm-dial   #hold-ring   #pose-name   #pose-sanskrit
#status-banner   #score-value   #sequence-rail
#btn-calibrate   #btn-start   #btn-skip
```

Experience styles against them, touching no JS:

```css
body[data-match="true"] #arm-dial { /* locked-on treatment */ }
body[data-status="no_device"] #status-banner { /* … */ }
#hold-ring { stroke-dashoffset: calc(var(--circumference) * (1 - var(--hold-pct))); }
```

**Why this is worth five minutes now:** Owner 04 can redesign the entire visual
language at T+55 — palette, layout, the lot — without touching a file Owner 03
has open.

---

## 9. Run commands

```bash
# Owner 01 only — the machine with the AirPods (macOS 14+)
make bundle       # MANDATORY. macOS gates motion behind TCC and only prompts
                  # for a bundled, signed app. An unbundled SwiftPM binary
                  # silently receives ZERO samples and reports no error.
make doctor       # verifies the live capture path end to end
make monitor      # live readout — use this to measure the pose bands

# Everyone else, all session — no hardware, identical payloads
make synthetic
airpod-pose monitor --source file --file data/golden.jsonl

# Record the golden run the moment the flow works
make record OUT=data/golden.jsonl
```

Source values are `device | udp | file | synthetic` — there is no `replay`.

> **Windows users:** the `Makefile` is `SHELL := /bin/bash` with POSIX venv
> paths, and `swift build` is macOS-only. You cannot run the capture path. You
> *can* do all frontend and docs work — point your browser at whoever is running
> the server. Plan role assignments around this.

---

## 10. Failure behaviour

| Failure | Detected by | Behaviour — non-negotiable |
|---------|-------------|----------------------------|
| SSE drops | Browser | `EventSource` reconnects itself (`retry: 1000`). Keep last frame on screen, dimmed. **Never blank the UI.** |
| No samples > 1 s | Bridge | `device_lost`, status `no_device`. Pipeline keeps running; do not exit. |
| AirPods not active audio output | Signal | Same as above. The stream just goes quiet, nothing errors — `sensor-notes.md`. |
| Bud swaps | Signal | `sensorLocation` changed → force `uncalibrated`. |
| Pose never triggers | Human | Press skip. Widen the band in YAML between runs. |
| Bluetooth dies on stage | Human | `--source file --file data/golden.jsonl`, narrate over it. |

---

## 11. Definition of integrated

The T+40 gate. All five true, or you are not integrated and should stop adding
features.

- [ ] A browser on a **second laptop** shows the same live session as the first.
- [ ] Calibrating with the arm down, then raising it, moves the dial in the
      correct direction.
- [ ] Holding Warrior II for its full duration fires `pose_complete` and advances
      the cursor.
- [ ] Killing the Python process dims the UI rather than breaking it; restarting
      recovers without a page reload.
- [ ] `data/golden.jsonl` is committed and replays end to end.

---

Contract version 1. **Additive changes only after T+05**: add fields freely,
never rename or remove one. If you need a breaking change, bump `v` and say so
out loud in the room.
