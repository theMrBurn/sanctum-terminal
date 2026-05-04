"""ASCII renderer — pure function mapping the brain's entity state into
a top-down glyph grid. The canonical sanctum-terminal view: player at
center, world rotating around them as they walk.

Coordinate conventions:
  Brain entity (x, y, z): x = world east, y = world north, z = height.
  Grid: rows top→bottom = north→south (row 0 = +Y, max row = -Y).
        cols left→right = west→east (col 0 = -X, max col = +X).

ASCII char per kind comes from a dict built by the caller (typically
from kind_config.json's `ascii` field). Missing kinds fall back to '?'.
Player is always '@' at the exact center. Floor is '.'.
"""
from __future__ import annotations

from typing import Dict, List, Sequence


FLOOR = "."
PLAYER = "@"
UNKNOWN = "?"


def render_view(entities: Sequence[Dict],
                cam_x: float, cam_y: float,
                radius: int,
                kind_chars: Dict[str, str]) -> List[str]:
    """Render a (2*radius+1) × (2*radius+1) grid of glyphs centered on
    (cam_x, cam_y). Entities place by rounding world-relative offset
    to the nearest tile. Overlap priority = larger collision_radius wins.
    Player glyph is never overwritten.
    """
    size = 2 * radius + 1
    # Grid of (priority, char). Priority -1 = floor (never wins).
    cells: List[List[tuple[float, str]]] = [
        [(-1.0, FLOOR) for _ in range(size)] for _ in range(size)
    ]

    for ent in entities:
        ex = ent.get("x", 0.0)
        ey = ent.get("y", 0.0)
        dx = ex - cam_x
        dy = ey - cam_y
        col = radius + round(dx)
        row = radius - round(dy)          # +Y = row 0 (north = up)
        if not (0 <= row < size and 0 <= col < size):
            continue
        kind = ent.get("kind", "")
        glyph = kind_chars.get(kind, UNKNOWN)
        priority = float(ent.get("collision_radius", 0.0))
        if priority > cells[row][col][0]:
            cells[row][col] = (priority, glyph)

    # Stamp the player LAST so no entity overrides it.
    cells[radius][radius] = (float("inf"), PLAYER)

    return ["".join(ch for _, ch in row) for row in cells]
