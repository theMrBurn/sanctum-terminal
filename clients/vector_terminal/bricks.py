"""Brick Attack — wireframe targets on the front wall.

Renders un-destroyed bricks as colored wireframe AABBs. WIN message is
drawn 2D in HUD; this module is 3D world geometry only.

Per V1 close-out 2026-05-04.
"""
from __future__ import annotations

import pyray as rl


def _color_for(hp: int, max_hp: int) -> "rl.Color":
    """Color shifts based on remaining HP ratio.
    Full HP = bright red, low HP = pale orange. Multi-HP bricks get a
    higher base saturation so they read as 'tougher' visually."""
    if max_hp <= 0:
        max_hp = 1
    ratio = max(0.0, min(1.0, hp / max_hp))
    # Boss bricks (max_hp > 1): base color skews magenta so they're
    # visually distinct from regular pins.
    if max_hp > 1:
        r = int(200 + 55 * ratio)
        g = int(40 + 50 * ratio)
        b = int(140 + 40 * ratio)
    else:
        r = int(200 + 55 * ratio)
        g = int(80 + 60 * ratio)
        b = int(60 + 40 * ratio)
    return rl.Color(r, g, b, 255)


def render(manifest: dict) -> None:
    """Draw all un-destroyed bricks as wireframe boxes.

    Each brick carries its own AABB (x_min/max, y_min/max, z_min/max),
    so layout is free — floor pins, wall targets, ceiling hangs etc.
    """
    bricks_block = manifest.get("bricks") or {}
    items = bricks_block.get("items") or []
    if not items:
        return

    # Brain → raylib: brain (x, y, z) → raylib (x, z_up, y_forward)
    def V(bx, by, bz):
        return rl.Vector3(bx, bz, by)

    for b in items:
        if b.get("destroyed"):
            continue
        x_min = float(b.get("x_min", 0.0))
        x_max = float(b.get("x_max", 0.0))
        y_min = float(b.get("y_min", 0.0))
        y_max = float(b.get("y_max", 0.0))
        z_min = float(b.get("z_min", 0.0))
        z_max = float(b.get("z_max", 0.0))
        hp = int(b.get("hp", 1))
        max_hp = int(b.get("max_hp", 1))
        color = _color_for(hp, max_hp)

        # 8 corners of the brick AABB
        c000 = V(x_min, y_min, z_min)
        c100 = V(x_max, y_min, z_min)
        c110 = V(x_max, y_max, z_min)
        c010 = V(x_min, y_max, z_min)
        c001 = V(x_min, y_min, z_max)
        c101 = V(x_max, y_min, z_max)
        c111 = V(x_max, y_max, z_max)
        c011 = V(x_min, y_max, z_max)

        # 12 edges
        rl.draw_line_3d(c000, c100, color)
        rl.draw_line_3d(c100, c110, color)
        rl.draw_line_3d(c110, c010, color)
        rl.draw_line_3d(c010, c000, color)
        rl.draw_line_3d(c001, c101, color)
        rl.draw_line_3d(c101, c111, color)
        rl.draw_line_3d(c111, c011, color)
        rl.draw_line_3d(c011, c001, color)
        rl.draw_line_3d(c000, c001, color)
        rl.draw_line_3d(c100, c101, color)
        rl.draw_line_3d(c110, c111, color)
        rl.draw_line_3d(c010, c011, color)
