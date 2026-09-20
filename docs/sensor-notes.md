# What the hardware actually gives us

Notes to save the next person a re-discovery. Anything marked **verify** is an
assumption we have not yet checked against real hardware.

## Supported devices

Head motion requires an IMU in the buds: AirPods Pro (all gens), AirPods 3rd
gen and later, AirPods Max, Beats Fit Pro. AirPods 1/2 and most Beats have no
IMU and will report `isDeviceMotionAvailable == false`.

## Rate and latency

- Sample rate is fixed at roughly **25 Hz**. There is no API to raise it, so
  fast gestures are only ~8-12 samples long. Any smoothing has to be cheap or it
  eats the whole gesture.
- Bluetooth adds latency, empirically tens of milliseconds, and it is not
  constant. `CMDeviceMotion.timestamp` (our `t`) is the device clock, so use it
  -- not arrival time -- for anything rate-based.
- Samples stop arriving when the AirPods are not the active audio output.
  Nothing errors; the stream just goes quiet.

## What each field means

| Field | Meaning | Units |
| --- | --- | --- |
| `q` | Fused attitude, `[w, x, y, z]` | unit quaternion |
| `euler` | Convenience angles from CoreMotion itself | degrees |
| `rot` | Gyroscope rotation rate | rad/s |
| `acc` | Acceleration with gravity removed | g |
| `grav` | Gravity direction in the body frame | g |

Attitude is already sensor-fused by the OS, so we are not writing a Madgwick
filter. Yaw still drifts (no magnetometer reference we can trust), which is why
calibration exists and why long-running absolute yaw is not dependable.

## Reference frame

CoreMotion picks its own reference frame when the stream starts -- it is not
world-aligned and not repeatable between runs. Absolute angles are therefore
meaningless on their own. `calibration.py` captures a "looking straight ahead"
pose and every `HeadPose` is expressed relative to it.

## Axis conventions

Fixed in `quaternion.py` and enforced by tests: body frame is x = forward
(nose), y = left (ear), z = up (crown), and

    yaw   > 0  turning left
    pitch > 0  looking up
    roll  > 0  tilting the head to the right

Note the pitch sign is flipped relative to textbook aerospace Z-Y-X so that
"look up" is positive. **Verify** the signs on hardware before trusting them in
a demo: run `airpod-pose monitor`, turn your head left, and confirm yaw goes
positive. A flipped axis is a 20-minute bug if you find it late.

## Known gotchas

- **Both buds.** Motion comes from whichever bud Apple decides is primary, and
  that can switch mid-session (for example when you take one out). Expect an
  orientation discontinuity; nothing tells you it happened. **Verify** how bad
  this is before building anything precise.
- **Permission.** macOS gates this behind Motion & Fitness in TCC, and the
  prompt only appears for a bundled, signed app -- an unbundled SwiftPM binary
  silently receives zero samples. Hence `make bundle`.
- **Head vs. body.** The IMU cannot tell "turned my head" from "turned my whole
  body". If a demo depends on that distinction, it needs a second reference.
