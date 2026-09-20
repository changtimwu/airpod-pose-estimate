"""Minimal quaternion helpers, pure stdlib so the core math stays testable.

Conventions, chosen once here so nothing downstream has to guess:

* Quaternions are (w, x, y, z), unit length, and rotate a vector from the body
  frame into the reference frame.
* The body frame is x = forward (nose), y = left (ear), z = up (crown).
* Euler angles are intrinsic Z-Y-X (yaw, then pitch, then roll) in degrees,
  **except** that pitch is negated relative to the textbook aerospace form so
  that positive pitch means nose *up*. With x-forward/z-up, the textbook sign
  would make "look up" negative, which reads backwards in every demo and is the
  kind of thing that silently inverts a gesture. So:

      yaw   > 0  turning left
      pitch > 0  looking up
      roll  > 0  tilting the head to the right

`to_euler` and `from_euler` share the flip, so they remain exact inverses.
"""

from __future__ import annotations

import math
from typing import Tuple

from .model import Quat, Vec3

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)

# Body axes implied by the Z-Y-X convention above: nose, left ear, crown.
FORWARD: Vec3 = (1.0, 0.0, 0.0)
LEFT: Vec3 = (0.0, 1.0, 0.0)
UP: Vec3 = (0.0, 0.0, 1.0)


def normalize(q: Quat) -> Quat:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0.0:
        return IDENTITY
    return (w / n, x / n, y / n, z / n)


def conjugate(q: Quat) -> Quat:
    w, x, y, z = q
    return (w, -x, -y, -z)


def multiply(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def relative(reference: Quat, current: Quat) -> Quat:
    """Rotation that takes `reference` to `current` (i.e. reference^-1 * current)."""
    return normalize(multiply(conjugate(normalize(reference)), normalize(current)))


def rotate_vector(q: Quat, v: Vec3) -> Vec3:
    """Apply `q` to `v`."""
    w, x, y, z = normalize(q)
    vx, vy, vz = v
    # t = 2 * (q_vec x v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def to_euler(q: Quat) -> Tuple[float, float, float]:
    """Return (yaw, pitch, roll) in degrees; see the module docstring for signs."""
    w, x, y, z = normalize(q)

    sin_pitch = 2.0 * (w * y - z * x)
    sin_pitch = max(-1.0, min(1.0, sin_pitch))
    pitch = math.asin(sin_pitch)

    if abs(sin_pitch) > 0.99999:  # gimbal lock: fold roll into yaw
        yaw = 2.0 * math.atan2(x, w)
        roll = 0.0
    else:
        yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))

    return (math.degrees(yaw), -math.degrees(pitch), math.degrees(roll))


def from_euler(yaw: float, pitch: float, roll: float) -> Quat:
    """Inverse of :func:`to_euler`; inputs in degrees."""
    cy, sy = _half_cos_sin(yaw)
    cp, sp = _half_cos_sin(-pitch)  # mirror of the nose-up flip in to_euler
    cr, sr = _half_cos_sin(roll)
    return normalize(
        (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )
    )


def angle_between(a: Quat, b: Quat) -> float:
    """Shortest rotation angle between two orientations, in degrees."""
    aw, ax, ay, az = normalize(a)
    bw, bx, by, bz = normalize(b)
    dot = abs(aw * bw + ax * bx + ay * by + az * bz)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Spherical interpolation; `t` in [0, 1]."""
    a = normalize(a)
    b = normalize(b)
    dot = sum(p * q for p, q in zip(a, b))
    if dot < 0.0:  # take the short way round
        b = tuple(-v for v in b)  # type: ignore[assignment]
        dot = -dot
    if dot > 0.9995:  # nearly parallel: lerp and renormalize
        return normalize(tuple(p + t * (q - p) for p, q in zip(a, b)))  # type: ignore[arg-type]
    theta = math.acos(max(-1.0, min(1.0, dot)))
    sin_theta = math.sin(theta)
    wa = math.sin((1.0 - t) * theta) / sin_theta
    wb = math.sin(t * theta) / sin_theta
    return normalize(tuple(wa * p + wb * q for p, q in zip(a, b)))  # type: ignore[arg-type]


def wrap_degrees(angle: float) -> float:
    """Fold an angle into (-180, 180]."""
    wrapped = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def _half_cos_sin(deg: float) -> Tuple[float, float]:
    half = math.radians(deg) * 0.5
    return (math.cos(half), math.sin(half))
