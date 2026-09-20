# Demo ideas backlog

We built the plumbing before picking the demo. This is the shortlist, scored on
what the sensor can actually deliver: ~25 Hz fused orientation, reliable
relative angles, drifting absolute yaw, no position, no way to separate head
rotation from body rotation.

## Plays to the sensor's strengths

- **Hands-free control / accessibility.** Nod = accept, shake = dismiss, dwell
  left/right = navigate. Works entirely on relative angles and rates, which is
  exactly what is solid. Needs no new math -- just better versions of the
  detectors already in `gestures.py`.
- **Posture and focus coach.** Slouch and head-drop show up clearly in pitch
  over minutes. Drift does not matter if you re-calibrate on a cue. Strong demo
  because the signal is large and slow.
- **Head-tracked spatial UI.** Pan a map, a 3D model, or a spreadsheet by
  looking around. Instantly legible on a projector, and `viz.py` is already 80%
  of the visual.
- **Attention / meeting analytics.** How often does someone turn away? Coarse,
  aggregate, robust to drift.

## Possible, with caveats

- **Gesture-based game input** (dodge, lean, aim). Fun, but 25 Hz and Bluetooth
  latency make anything twitchy feel mushy. Prototype the latency first.
- **Sign / gesture vocabulary via a small classifier.** Record labelled sessions
  with `airpod-pose record`, train on windows of `HeadPose`. Realistic only if
  we collect data early -- budget an hour for recording.
- **Two-device relative pose** (AirPods + iPhone IMU) to separate head rotation
  from body rotation. Fixes the biggest limitation, costs an iOS app.

## Probably not

- Anything needing **absolute heading** (compass-style). Yaw drifts and has no
  magnetometer anchor.
- Anything needing **position** (leaning distance, walking). No usable position
  from this IMU; double-integrating `acc` diverges in seconds.
- Anything needing **fast, precise timing** (rhythm games). Rate and latency are
  both against us.

## Next steps regardless of which we pick

1. Verify axis signs and both-bud switching on hardware (docs/sensor-notes.md).
2. Record 5-10 sessions of whatever gesture the demo needs, and tune the
   detectors against the recordings instead of live.
3. Decide where smoothing lives: calm visuals and fast triggers want different
   `--smoothing` values, and one number currently serves both.
