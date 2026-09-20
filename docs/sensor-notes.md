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
| `loc` | Which bud produced the sample: `left`, `right`, `default` | - |

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

## Steep and inverted poses: do not threshold Euler angles

Relevant to anything with the head far from level -- downward dog, cobra,
forward folds, headstands. As pitch approaches vertical, yaw and roll stop being
separable. Measured with our own math:

| head pitch | Euler difference between two poses | actual rotation between them |
| --- | --- | --- |
| 0 deg | yaw +10, roll -10 | 14.1 deg |
| 45 deg | yaw +10, roll -10 | 7.6 deg |
| 80 deg | yaw +10, roll -10 | 1.7 deg |
| 89 deg | yaw +10, roll -10 | **0.17 deg** |

At 89 deg, a 14-degree difference on paper is a sixth of a degree in reality. A
threshold on yaw or roll there fires on noise, and the angle will swing wildly
between frames while the head barely moves.

Two things that stay well behaved everywhere, and what to build classifiers on:

```python
quat.angle_between(reference_pose, current)      # "how far from the target pose?"
quat.rotate_vector(pose.q, quat.FORWARD)         # "where does the nose point?"
```

The second is usually what a pose rule actually means. "Chin tucked" is the nose
vector's elevation; "head square to the mat" is its horizontal bearing. Both are
single numbers, both are continuous through vertical, neither cares about the
Euler parameterisation.

## Known gotchas

- **The audio route, not the Bluetooth connection, is what matters.** Samples
  only arrive while the AirPods are the *selected output device*. Connected but
  idle is not enough, and they auto-switch away to an iPhone without telling you.
  Check with `system_profiler SPAudioDataType | grep -B4 "Default Output Device: Yes"`.
- **Both buds: you get one stream, not two.** Checked against the API and on
  hardware. `CMHeadphoneMotionManager` has no call to select a bud or to open a
  second stream -- there is exactly one `startDeviceMotionUpdates`. Each sample
  carries `CMDeviceMotion.sensorLocation` (`default` / `headphoneLeft` /
  `headphoneRight`), which we surface as the `loc` field, so you can *observe*
  which bud is feeding you but not *choose*. Measured: 250 consecutive samples,
  all `left`.

  The source can switch mid-session (take a bud out, put it back, battery), and
  the orientation can jump at that moment with nothing else announcing it. Watch
  `loc` for a change if a pose estimate suddenly slews.

  **And independent buds would not buy what you might hope.** Both are clamped
  to the same rigid body -- your head -- about 15 cm apart. Two IMUs there give
  you the same orientation twice; the only extra information is a lever-arm
  difference in acceleration, which is buried in noise at this rate. It is not a
  second joint, and it says nothing about torso, hips, shoulders or limbs. For
  anything needing a second body segment, you need a second device: an iPhone at
  the waist (CMMotionManager), an Apple Watch on the wrist, or a camera.

- **Head vs. body.** The IMU cannot tell "turned my head" from "turned my whole
  body". If a demo depends on that distinction, it needs a second reference.
