"""fov.py — 8-octant recursive shadowcasting field-of-view.

Algorithm: recursive shadowcasting by Bjorn Bergstrom (RogueBasin).
Reference: roguebasin.com/index.php/FOV_using_recursive_shadowcasting

Walls block FOV; floor/corridor/door/stairs pass light.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 3.
"""
from __future__ import annotations

from typing import Callable

from core.systems.make_brains.nethack.dungeon import FOV_BLOCKING, Tile

# ---------------------------------------------------------------------------
# 8-octant transform multipliers
# Each row is (xx, xy, yx, yy) for a specific octant rotation.
# ---------------------------------------------------------------------------

OCTANT_TRANSFORMS: tuple[tuple[int, int, int, int], ...] = (
    ( 1,  0,  0,  1),
    ( 0,  1,  1,  0),
    ( 0, -1,  1,  0),
    (-1,  0,  0,  1),
    (-1,  0,  0, -1),
    ( 0, -1, -1,  0),
    ( 0,  1, -1,  0),
    ( 1,  0,  0, -1),
)


def _cast_octant(
    visible: set[tuple[int, int]],
    origin_x: int,
    origin_y: int,
    radius: int,
    row: int,
    start_slope: float,
    end_slope: float,
    xx: int, xy: int, yx: int, yy: int,
    blocks: Callable[[int, int], bool],
) -> None:
    """Recursively reveal tiles in one octant.

    visible: mutated in-place — tiles added as they are revealed.
    blocks:  callable(x, y) -> bool — True if the tile blocks light.
    """
    if start_slope < end_slope:
        return

    next_start = start_slope
    for j in range(row, radius + 1):
        dx = -j - 1
        dy = -j

        blocked = False
        while dx <= 0:
            dx += 1
            # Map the octant-local (dx, dy) back to world coords.
            mx = origin_x + dx * xx + dy * yx
            my = origin_y + dx * xy + dy * yy

            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)

            if start_slope < r_slope:
                continue
            if end_slope > l_slope:
                break

            if dx * dx + dy * dy <= radius * radius:
                visible.add((mx, my))

            if blocked:
                if blocks(mx, my):
                    next_start = r_slope
                else:
                    blocked = False
                    start_slope = next_start
            else:
                if blocks(mx, my) and j < radius:
                    blocked = True
                    _cast_octant(
                        visible, origin_x, origin_y, radius,
                        j + 1, start_slope, l_slope,
                        xx, xy, yx, yy, blocks,
                    )
                    next_start = r_slope

        if blocked:
            break


def compute_fov(
    origin_x: int,
    origin_y: int,
    radius: int,
    is_blocking: Callable[[int, int], bool],
    map_w: int,
    map_h: int,
) -> set[tuple[int, int]]:
    """Return the set of (x, y) positions visible from (origin_x, origin_y).

    is_blocking: callable(x, y) -> bool — True if the tile blocks light.
    Origin cell is always visible.
    """
    visible: set[tuple[int, int]] = {(origin_x, origin_y)}

    for xx, xy, yx, yy in OCTANT_TRANSFORMS:
        _cast_octant(
            visible, origin_x, origin_y, radius,
            1, 1.0, 0.0,
            xx, xy, yx, yy,
            lambda x, y: (
                x < 0 or x >= map_w or y < 0 or y >= map_h
                or is_blocking(x, y)
            ),
        )

    # Clamp to map bounds
    return {(x, y) for x, y in visible if 0 <= x < map_w and 0 <= y < map_h}


def compute_fov_from_level(
    level,            # dungeon.Level — avoid circular import by duck-typing
    origin_x: int,
    origin_y: int,
    radius: int = 8,
) -> set[tuple[int, int]]:
    """Convenience wrapper that extracts blocking predicate from a Level."""
    def is_blocking(x: int, y: int) -> bool:
        return level.at(x, y) in FOV_BLOCKING

    return compute_fov(
        origin_x, origin_y, radius,
        is_blocking,
        len(level.grid),          # MAP_W
        len(level.grid[0]),       # MAP_H
    )
