"""Live 3D view of the head frame, plus a rolling angle plot.

This is the fastest way to answer "is the sensor data actually sane?", which is
the whole point of the skeleton. matplotlib is deliberately the only dependency
-- swapping in something prettier later is easy once we know what we are showing.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from . import quaternion as quat
from . import sources
from .gestures import GestureRecognizer
from .pipeline import PosePipeline

#: Body axes drawn from the head origin, matching quaternion.py's convention.
AXES = (
    (quat.FORWARD, "tab:red", "forward"),
    (quat.LEFT, "tab:green", "left"),
    (quat.UP, "tab:blue", "up"),
)


def run_viz(source, pipeline: PosePipeline, trail: int = 120) -> int:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers 3d projection)
    except ImportError:
        print("matplotlib is required for `viz`: pip install -e 'python[viz]'")
        return 1

    stream = sources.samples(source)
    recognizer = GestureRecognizer()

    history: Deque[tuple] = deque(maxlen=trail)
    events: Deque[str] = deque(maxlen=5)

    fig = plt.figure(figsize=(10, 5))
    ax3d = fig.add_subplot(1, 2, 1, projection="3d")
    ax2d = fig.add_subplot(1, 2, 2)
    fig.suptitle("AirPods head pose")

    quivers = []
    lines = {
        name: ax2d.plot([], [], label=name)[0] for name in ("yaw", "pitch", "roll")
    }
    ax2d.set_ylim(-90, 90)
    ax2d.set_xlim(0, trail)
    ax2d.set_ylabel("degrees")
    ax2d.set_xlabel("samples")
    ax2d.legend(loc="upper left")
    ax2d.grid(alpha=0.3)
    event_text = ax2d.text(0.98, 0.02, "", transform=ax2d.transAxes, ha="right", va="bottom")

    for axis in ("set_xlim", "set_ylim", "set_zlim"):
        getattr(ax3d, axis)(-1.2, 1.2)
    ax3d.set_xlabel("x")
    ax3d.set_ylabel("y")
    ax3d.set_zlabel("z")

    def update(_frame):
        # Drain whatever arrived since the last frame so we never lag behind.
        for _ in range(8):
            sample = next(stream, None)
            if sample is None:
                break
            pose = pipeline.feed(sample)
            if pose is None:
                continue
            history.append((pose.yaw, pose.pitch, pose.roll))
            for event in recognizer.feed(pose):
                events.appendleft("%s (%.2f)" % (event.name, event.confidence))

        while quivers:
            quivers.pop().remove()
        if pipeline.last_pose is not None:
            q = pipeline.last_pose.q
            for vector, color, label in AXES:
                x, y, z = quat.rotate_vector(q, vector)
                quivers.append(
                    ax3d.quiver(0, 0, 0, x, y, z, color=color, label=label, arrow_length_ratio=0.15)
                )

        for index, name in enumerate(("yaw", "pitch", "roll")):
            values = [h[index] for h in history]
            lines[name].set_data(range(len(values)), values)
        event_text.set_text(" | ".join(events))
        return list(lines.values())

    animation = FuncAnimation(fig, update, interval=40, blit=False, cache_frame_data=False)
    fig._airpod_animation = animation  # keep a reference alive
    plt.tight_layout()
    plt.show()
    return 0
