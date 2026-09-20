# What the hardware actually gives us

Notes to save the next person a re-discovery. Anything marked **verify** is an
assumption we have not yet checked against real hardware.

## Supported devices

Head motion requires an IMU in the buds: AirPods Pro (all gens), AirPods 3rd
gen and later, AirPods Max, Beats Fit Pro. AirPods 1/2 and most Beats have no
IMU and will report `isDeviceMotionAvailable == false`.

## Rate and latency

- Sample rate is whatever the OS gives you and there is no API to change it.
  **Measured here: 50.0 Hz, dead steady** (20.0 ms between samples, min 19.8 /
  max 20.0 over a 6 s window) on AirPods Pro 2 with macOS 26. Older hardware is
  widely reported at 25 Hz. Derive `dt` from `t`; never hard-code a rate.
  Either way a fast gesture is only a few tenths of a second long, so smoothing
  has to be cheap or it eats the whole gesture.
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

- **The audio route, not the Bluetooth connection, is what matters.** Samples
  only arrive while the AirPods are the *selected output device*. Connected but
  idle is not enough, and they auto-switch away to an iPhone without telling you.
  Check with `system_profiler SPAudioDataType | grep -B4 "Default Output Device: Yes"`.
- **Both buds.** Motion comes from whichever bud Apple decides is primary, and
  that can switch mid-session (for example when you take one out). Expect an
  orientation discontinuity; nothing tells you it happened. **Verify** how bad
  this is before building anything precise.
- **Permission, and who asks for it.** macOS gates this behind Motion & Fitness
  in TCC. Two things have to be true, and we got both wrong at first:
  1. The binary must be **bundled and signed** (`make bundle`) -- a bare SwiftPM
     binary has no identity to attach a grant to.
  2. It must be **launched through LaunchServices** (`open Foo.app --args ...`),
     not from a terminal. TCC attributes the request to the *responsible*
     process, and a terminal-launched child inherits the terminal's context
     instead of asking for itself. Measured: launched from a shell it sits at
     `authorization=notDetermined` and receives zero samples indefinitely;
     launched via `open`, the grant appears and samples flow.
  Because LaunchServices owns stdout, the app mirrors its stream to UDP and the
  Python side reads that back. `sources.AppSource` does all of this for you.
- **Head vs. body.** The IMU cannot tell "turned my head" from "turned my whole
  body". If a demo depends on that distinction, it needs a second reference.
