"""Ball trail — fading line behind the ball showing recent motion.

Pure visual diagnostic. Reveals whether the ball is bouncing correctly
off walls (you see the path bend at the wall) or escaping the chamber
(you see the path go off into the void). Per V1 close-out: needed
because the substrate works but isn't observable without a trail.
"""
from __future__ import annotations

import pyray as rl


# Capture window — last N ball positions. ~30 frames at 60Hz = 0.5s of
# trail history. Long enough to see strike + flight + bounce, short
# enough that the trail doesn't clutter the screen during sustained rally.
TRAIL_LEN = 60


class TrailState:
    """Per-session ring buffer of recent ball positions in BRAIN coords."""

    __slots__ = ("points",)

    def __init__(self):
        self.points: list[tuple[float, float, float]] = []

    def observe(self, manifest_ball: dict | None) -> None:
        """Push current ball position; trim to TRAIL_LEN."""
        if not manifest_ball or not manifest_ball.get("exists"):
            # Ball cleared (rally ended, etc.). Reset the trail so the
            # next serve starts a fresh path.
            self.points.clear()
            return
        bx = float(manifest_ball.get("x", 0.0))
        by = float(manifest_ball.get("y", 0.0))
        bz = float(manifest_ball.get("z", 0.0))
        self.points.append((bx, by, bz))
        if len(self.points) > TRAIL_LEN:
            self.points = self.points[-TRAIL_LEN:]


def render(state: TrailState) -> None:
    """Draw fading line segments connecting recent positions.

    Brain (x lateral, y forward, z up) → raylib (x, z, y).
    Older segments fade toward transparent + dimmer color.
    """
    n = len(state.points)
    if n < 2:
        return
    for i in range(n - 1):
        a = state.points[i]
        b = state.points[i + 1]
        # Fade: oldest = 0%, newest = 100%
        t = (i + 1) / (n - 1)
        alpha = max(40, int(40 + 215 * t))                  # 40..255
        # Color shifts from cool blue (older) → bright yellow (newer)
        r = int(100 + 155 * t)
        g = int(160 + 90 * t)
        b_chan = int(220 - 200 * t)
        color = rl.Color(r, g, b_chan, alpha)
        a_v = rl.Vector3(a[0], a[2], a[1])                 # brain → raylib
        b_v = rl.Vector3(b[0], b[2], b[1])
        rl.draw_line_3d(a_v, b_v, color)
