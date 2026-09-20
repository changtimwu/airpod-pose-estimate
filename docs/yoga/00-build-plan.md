# Yoga alignment coach — 70-minute build plan

**Read the arm, not the room.** A yoga alignment coach driven by the IMU in a
single AirPod, rubber-banded to the left forearm.

The capture layer already exists in this repo and works. Seventy minutes buys a
classifier, a bridge and an interface worth demoing.

Interface contract: [`01-wire-contract.md`](01-wire-contract.md) — **read it
before writing code.**

---

## Three facts that decide the architecture

### There is no hand position

The headphone API is **3DoF — orientation only**. We get pitch, roll and yaw of
the forearm. We never get where the hand *is* in space.

This is fine for yoga, because asana is defined by limb **angles**, not
coordinates. Say **alignment** in the demo and everything we claim is true. Say
**position** and a judge who knows the API stops believing us.

### The rig must be unambiguous

Motion streams from **one bud at a time** and can silently hand off to the other,
causing an orientation discontinuity with no notification
([`sensor-notes.md`](../sensor-notes.md)).

Remove the ambiguity physically:

- **Right bud stays in the charging case.** One active bud, no arbitration.
- Left bud banded to the forearm.
- **Automatic Ear Detection off.**
- AirPods must be the **selected audio output device** or the stream never
  starts — and nothing errors, it just goes quiet.
- **`make bundle` is mandatory.** macOS gates motion behind TCC and only prompts
  for a bundled, signed app. An unbundled binary silently gets zero samples.

### 25 Hz, and calibration is not optional

Sample rate is fixed at roughly 25 Hz — no API raises it. CoreMotion picks an
arbitrary reference frame at stream start that is **not repeatable between
runs**, so absolute angles are meaningless on their own.

The user zeroes in Mountain pose, arm hanging. Every angle displayed is relative
to that. Skip it and pose detection appears to work at the desk and fails on
stage when the laptop faces a different wall.

---

## System diagram

```
   AirPod (left forearm)          ALREADY BUILT — DO NOT TOUCH
        │  BLE
        ▼
   airpod-motion  (Swift, macOS 14+, CMHeadphoneMotionManager)
        │  newline-delimited JSON, ~25 Hz, stdout and/or UDP
        ▼
   sources.py → pipeline.py  → HeadPose  (degrees, calibrated, smoothed)
        │
        │  ═══════════════ BUILD THIS — 70 MINUTES ═══════════════
        ▼
   poses.py        classifier + hold timer + hysteresis      ◀── SIGNAL
        │
        ▼
   server.py       SSE fan-out + session state               ◀── BRIDGE
        │           also serves the frontend, same origin
        ▼
   web/            live arm dial, flow engine                ◀── INTERFACE
                   visual system, demo script                ◀── EXPERIENCE


   make synthetic  ·  --source file
   ─────────────────────────────────
   Identical JSON, no hardware. Three of you develop here all
   session. Also the demo safety net.
```

**One machine has the AirPods.** It runs the Swift binary and the classifier.
Everyone else points at synthetic — identical payloads, so integration at T+40 is
a change of host, not a change of code.

> **Windows users cannot run the capture path.** The `Makefile` is
> `SHELL := /bin/bash` with POSIX venv paths, and `swift build` is macOS-only.
> Frontend and docs work is unaffected — point your browser at whoever runs the
> server. Assign roles accordingly.

---

## Division of labour

Each person owns directories nobody else writes to. That is the entire
merge-conflict strategy, and at this timescale it is the only one that survives.

### 01 · SIGNAL — turn angles into asana

The only person with the AirPods and a Mac. Owns hardware truth, so nobody else
is ever blocked on it.

- **Owns:** `python/airpod_pose/poses.py`, `poses.json`, and the calibration
  command. Replaces the placeholder detectors in `gestures.py`.
- **Builds:**
  - Explicit re-zero from Mountain pose
  - Five pose matchers on **pitch and roll only** — never yaw, it drifts
  - Hold timer with hysteresis so state does not flicker at the band boundary
  - Emits the contract payload
- **First move:** `make bundle && make doctor`, then `make monitor`. Band the bud
  on, read real numbers for each pose, write the bands down. **Verify the pitch
  sign** — the repo's own notes mark the conventions unverified.
- **Done when:** standing in Warrior II prints `warrior_ii` for three seconds
  straight without flickering.

### 02 · BRIDGE — get it to the browser

- **Owns:** `python/airpod_pose/server.py`, `web/index.html` scaffold.
- **Builds:**
  - Reads the pipeline, fans out over SSE to any number of clients
  - Serves the frontend on the same origin — no CORS, no second port
  - `--source synthetic` passthrough so it runs with zero hardware
  - Auto-reconnect and a heartbeat
  - Session state machine (see D5 in the contract — server is authoritative)
- **First move:** ship a server streaming the contract payload with **hardcoded
  values in the first ten minutes.** Interface and Experience are blocked until
  you do. This is the critical path.
- **Done when:** two browser tabs on two laptops both show live numbers, and
  killing the pipeline does not kill the page.

### 03 · INTERFACE — make the signal legible

Owns everything that moves in response to the arm. This is the part that proves
the thing is real.

- **Owns:** `web/app.js`, `web/pose-dial.js`
- **Builds:**
  - SSE client (`EventSource` reconnects itself)
  - Live arm dial — an SVG forearm that rotates with the real one
  - Target arc for the current pose, tightening as error shrinks
  - Hold ring that fills over the target duration
  - Writes the `data-*` attributes and CSS custom properties from §8 of the contract
- **First move:** drive it all from a fake payload at 25 Hz in a `setInterval`.
  Do not wait for Bridge.
- **Done when:** moving the arm moves the dial with no perceptible lag, and
  completing a hold advances the flow.

### 04 · EXPERIENCE — win the room

Judges score what they see in ninety seconds. This role exists because a working
demo that looks unfinished loses to a prettier one that does less.

- **Owns:** `web/style.css`, `web/index.html`, the pitch
- **Builds:**
  - Visual system — calm studio, large type, readable across a room
  - Calibration screen that makes zeroing feel intentional, not like a bug
  - A treatment for all seven `status` values (§6 of the contract is a screen inventory)
  - Pose cards with Sanskrit and English names
  - Completion screen with hold time and steadiness
  - The 90-second script, rehearsed twice
- **First move:** agree DOM ids and class names with Owner 03 at T+05. Neither of
  you renames anything after that.
- **Done when:** it reads from three metres away and the script lands in under 90
  seconds.

---

## The seventy minutes

Two synchronisation points only. Everything else is heads-down.

### 00–10 · Setup

Everyone runs `make setup` and `make synthetic` and confirms they see data
**before anyone writes code.** Agree the JSON contract and the DOM ids out loud.
Four branches created.

> **Gate:** four people, four branches, all seeing synthetic data.

### 10–40 · Build, nobody blocked

Signal reads real angles off the arm and writes the bands. Bridge ships the
hardcoded stream by T+20 at the latest. Interface and Experience both build
against fakes. No integration attempts, no "quick sync" — the contract is the
interface.

### 40–55 · Integrate

Merge all four branches. Swap the frontend's fake source for the real `/stream`.
Put the AirPods on and walk the flow end to end.

**Expect the pose bands to be wrong on first contact.** That is Signal's
ten-minute job, and exactly why the bands live in YAML instead of in code.

> **Gate:** one full flow completed live.

### 55–65 · Insure, then rehearse

`make record OUT=data/golden.jsonl` the moment the flow works. If the demo fails
on stage — dropped Bluetooth, wrong audio device, flat battery — replay it and
narrate over the top.

Rehearse the 90 seconds twice, out loud, with the laptop where it will actually
sit.

> **Gate:** `data/golden.jsonl` committed.

### 65–70 · Buffer. Write no code.

Charge the AirPods. Disable notifications and screen sleep. Recalibrate facing
the direction you will present from. The last five minutes belong to whatever
broke, and something will.

---

## Working agreement

| Branch | Owner |
|--------|-------|
| `feat/signal` | 01 |
| `feat/bridge` | 02 |
| `feat/interface` | 03 |
| `feat/experience` | 04 |

Push every ten minutes even when broken. A branch that only exists on a laptop
is a branch that dies with its battery.

**Non-negotiable:**

- **Nobody edits another owner's files.** Need a change? Ask them, in the room.
- **The contract is frozen at T+05.** Add fields, never rename or remove.
- **Pose bands live in `poses.json`**, re-read on every command — retune without restarting.
- **No new dependencies after T+40.**

---

## The pitch

Every camera-based form coach needs you to set up a phone, stand in frame, and be
in a well-lit room you are willing to be filmed in.

This needs a pair of earbuds most people already own. It works in the dark, works
in a hotel room, and never captures an image of anyone.

The demo is a person in Warrior II holding an arm level while a dial on screen
confirms it — and the judges understanding, without being told, that no camera is
involved.

> **Say:** "We read forearm **alignment** from the IMU in a single AirPod."
> Precise, defensible, still impressive.
>
> **Never say:** "We track hand position in 3D." It is not true, and it is the
> first thing a technical judge will probe.
