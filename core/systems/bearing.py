"""8-way compass bearing utility for HUD active-quest rows.

Per `project_async_quest_refactor` PR 4 — the gap user FELT during
2026-04-30 UAT walk: active quests need on-screen direction. Vector
terminal HUD renders rows like `[NE] Quest Name`; this module
computes the `[NE]` part.

Coordinate convention:
- World-space (brain): (x, y). +x = east, +y = north.
- Vector terminal: camera.position.z maps to brain y (forward = +z = +y).
- Bearing is **absolute** — relative to world axes, not player heading.
  Matches Skyrim-style compass UX (N-up).

Pure Python; no brain imports; trivially unit-testable.
"""
from __future__ import annotations

import math


# Sectors in order of atan2 output, starting at 0 (east) and rotating
# counter-clockwise. Each sector is 45° wide; round to nearest sector.
_COMPASS = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")


def bearing(
    from_pos: tuple[float, float],
    to_pos: tuple[float, float],
) -> str:
    """Return 8-way compass bearing from `from_pos` to `to_pos`.

    Returns one of E / NE / N / NW / W / SW / S / SE, or empty string
    when the positions are within float tolerance (no meaningful direction).

    Sectors are 45° wide, rounded to nearest. Boundaries (22.5° from a
    cardinal) round per Python's `round()` (banker's rounding) — fine
    for HUD display.
    """
    dx = to_pos[0] - from_pos[0]
    dy = to_pos[1] - from_pos[1]
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return ""
    angle = math.atan2(dy, dx)  # -π to π, 0 = east
    if angle < 0:
        angle += 2 * math.pi
    sector = int(round(angle / (math.pi / 4))) % 8
    return _COMPASS[sector]
