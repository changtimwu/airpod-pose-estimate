"""AirPods head-pose estimation toolkit (hackathon skeleton).

Layering, from raw sensor to application:

    sources   -> raw JSON records from the Swift capture tool (or a replay/fake)
    model     -> Sample / HeadPose value types
    quaternion-> orientation math, no state
    filters   -> smoothing, stateful
    calibration -> defines "straight ahead"
    pipeline  -> sources + calibration + filters => HeadPose stream
    gestures  -> HeadPose stream => discrete events (nod, shake, tilt, ...)

Only `gestures` and whatever app we build on top should need to change once we
pick a demo. Everything below it is hardware plumbing.
"""

from .model import HeadPose, Sample
from .pipeline import PosePipeline

__all__ = ["Sample", "HeadPose", "PosePipeline", "__version__"]
__version__ = "0.1.0"
