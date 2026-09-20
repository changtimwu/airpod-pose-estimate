import time
from airpod_pose.cli import _with_deadline


class SilentSource:
    """Never yields -- the exact case that used to hang doctor forever."""

    def records(self):
        while True:
            time.sleep(0.05)

    def close(self):
        pass


def test_deadline_returns_on_a_silent_source():
    started = time.monotonic()
    assert list(_with_deadline(SilentSource(), 1.0)) == []
    assert 0.9 < time.monotonic() - started < 2.5
