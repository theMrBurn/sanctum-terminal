"""World-revision diff: detects regen events from the manifest stream.

Brain bumps `manifest.world_revision` on every regen_world() call
(brain_server.py:330-335). Client must teleport the camera to
manifest.spawn.location when this happens — but NOT on the very first
manifest, since that's the initial spawn and the camera starts there.
"""
from __future__ import annotations


class WorldRevisionTracker:
    def __init__(self) -> None:
        self._seen: int | None = None

    def observe(self, revision: int | None) -> bool:
        """Return True if this revision is a real bump (regen, not initial)."""
        if revision is None:
            return False
        if self._seen is None:
            self._seen = revision
            return False
        if revision == self._seen:
            return False
        self._seen = revision
        return True
